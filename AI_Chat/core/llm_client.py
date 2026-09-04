"""
LLM 客户端 - 与 llama-server API 交互（同步版，用于 PyQt 线程）
"""
import json
import sys
import re
import requests
from typing import List, Dict, Generator, Optional


def _safe_decode(content_bytes: bytes) -> str:
    """安全解码字节串为字符串，优先 UTF-8，失败则用 chardet 检测"""
    if not content_bytes:
        return ""

    # 1. 优先 UTF-8
    try:
        return content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # 2. 用 chardet 检测
    try:
        import chardet
        result = chardet.detect(content_bytes)
        enc = result.get("encoding", "")
        conf = result.get("confidence", 0)
        if enc and conf > 0.5:
            try:
                return content_bytes.decode(enc)
            except (UnicodeDecodeError, LookupError):
                pass
    except ImportError:
        pass

    # 3. 尝试常见中文编码
    for enc in ["gbk", "gb18030", "gb2312", "big5"]:
        try:
            return content_bytes.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue

    # 4. 兜底
    return content_bytes.decode("utf-8", errors="replace")



# ---------- ChatML / Llama-3 / Qwen 等特殊 token 清理 ----------
# 模板边界 token / 控制 token：绝不能出现在模型回复内容里，否则就是泄漏/幻觉续写
_CHATML_SPECIAL = (
    "<|begin_of_text|>",
    "<|end_of_text|>",
    "<|end_of_turn|>",
    "<|eot_id|>",
    "<|start_header_id|>",
    "<|end_header_id|>",
    "<|im_end|>",
    "<|im_start|>",  # 本体也直接剔除（避免"裸"的半标签残留，虽然下面会处理）
    "<|reserved",  # 前缀：<|reserved_NNN|> 类
    "<|python_tag|>",
    "<|function_call",
    "<|fim_prefix|>",
    "<|fim_middle|>",
    "<|fim_suffix|>",
    "<|file_sep|>",
)

# "下一轮开始"检测：一旦出现，视为模型开始幻觉后续 user/assistant 轮，立即截断
_NEXT_TURN_MARKERS = (
    "<|im_start|>user",
    "<|im_start|>assistant",
    "<|start_header_id|>user<|end_header_id|>",
    "<|start_header_id|>assistant<|end_header_id|>",
)

# 兜底用正则：匹配任意 <|xxx|> 形式（但不与上面重复）——最终防线 4 也会重复处理
_RE_RESIDUAL = re.compile(r"<\|[^|]{1,80}\|>")


def _strip_special_tokens(text: str) -> str:
    """从流式 chunk 中剥离所有已知特殊 token / ChatML 边界标记。"""
    if not text:
        return text
    for tag in _CHATML_SPECIAL:
        # 无前缀闭合的直接替换；带 <|reserved 前缀的需要按 tag 匹配前缀
        if tag.endswith("|") or tag.endswith(">"):
            text = text.replace(tag, "")
        else:
            # 前缀形式：<|reserved...  找"从 tag 到 第一个 |>"
            i = 0
            while True:
                p = text.find(tag, i)
                if p == -1:
                    break
                # 找到结束 |>
                end = text.find("|>", p + len(tag))
                if end == -1:
                    # 没找到闭合：可能跨 chunk，只把已知前缀 tag 本体先切掉（如果前缀恰好完整出现）
                    text = text[:p] + text[p + len(tag):]
                    i = p
                    continue
                text = text[:p] + text[end + 2:]
                i = p
    # 再走一次兜底正则：任何 <|xxx|> 残留
    text = _RE_RESIDUAL.sub("", text)
    return text


def _find_next_turn_marker(combined: str):
    """在 combined 里找最早出现的"下一轮开始"标记；返回 (截断位置, 命中字符串) 或 (None, None)"""
    best_pos = None
    best_hit = None
    for m in _NEXT_TURN_MARKERS:
        p = combined.find(m)
        if p == -1:
            continue
        if best_pos is None or p < best_pos:
            best_pos = p
            best_hit = m
    # 再查 <|eot_id|>/<|end_of_text|>：真的结束 token 也直接截断
    for stop in ("<|end_of_text|>", "<|eot_id|>"):
        p = combined.find(stop)
        if p == -1:
            continue
        if best_pos is None or p < best_pos:
            best_pos = p
            best_hit = stop
    return best_pos, best_hit




def _strip_half_open_tags(text: str) -> str:
    """清除"半开 / 残缺"的 ChatML 管道标签（模型在"卡壳/重复循环"场景下狂吐的 <|im_start残缺、<| 后面文字、
    <|im_end...、|<| 右半残片等），避免这些乱码污染 UI 和历史。
    策略：
      1) 任何形如 <| 的左半标签：向后查找最近的 |> 闭合，如找不到（或中间包含换行/中文字符/空格长度异常），
         就把从 <| 开始到「第一个明确非标签名字符（中文/换行/常规标点）」之间的内容全部剔除。
      2) 孤立的 |> 右半闭合、单独出现的管道 | 等全部清掉。
    """
    if not text:
        return text
    # 先处理完整 <|xxx|>（以防上层没跑）
    text = _RE_RESIDUAL.sub("", text)
    out_chars = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        # 疑似左半标签：<|
        if ch == "<" and i + 1 < n and text[i+1] == "|":
            # 往后扫描：找 |>、换行、或超过 80 字符仍未闭合
            j = i + 2
            closed = False
            illegal_stop = False
            while j < n and (j - i) <= 80:
                if text[j] == "|" and j + 1 < n and text[j+1] == ">":
                    closed = True
                    break
                c = text[j]
                # 中文字符 / 换行 / 中文常见标点 → 认为标签已"走形"，非法终止
                if c in ("\n", "\r"):
                    illegal_stop = True; break
                cp = ord(c)
                if (cp >= 0x4E00 and cp <= 0x9FFF) or c in "，。！？、：；\"\'（）《》【】":
                    illegal_stop = True; break
                j += 1
            if closed:
                # 完整闭合：整段 <|xxx|> 丢弃（已在前面正则去一遍，这里再保险）
                i = j + 2
                continue
            if illegal_stop or (j - i) > 80:
                # 半开：丢弃从 i 到 j（含终止字符之前的疑似标签部分）
                # （终止字符本身保留，它是正常文字）
                i = j
                continue
            # j == n：标签到字符串末尾仍未闭合
            i = n
            continue
        # 孤立的管道残片：|> 单独出现（左半标签被丢了）
        if ch == "|" and i + 1 < n and text[i+1] == ">":
            i += 2
            continue
        # 单独出现的 <| 后面接换行
        if ch == "|" and i > 0 and text[i-1] == "<":
            # 理论上被上面 <| 分支吞了，不会来这里
            pass
        out_chars.append(ch)
        i += 1
    result = "".join(out_chars)
    # 再清一轮残余孤立 < 或 | 连在一起的垃圾
    result = re.sub(r"<\|{1,3}\s*[A-Za-z0-9_\-]*\s*$", "", result)  # 尾部残留 <|xxx...
    result = re.sub(r"^\s*\|>\s*", "", result)  # 开头 |> 残片（不吞正常 ">" 开头的文本）
    return result


# ---------- 供 UI 层 / Web 层复用的历史清洗与思考过滤 ----------

# "下一轮开始"检测集合（含真结束 token），用于流式 hold 前缀判断
_HOLD_MARKERS = _NEXT_TURN_MARKERS + ("<|end_of_text|>", "<|eot_id|>")
_MAX_MARKER_LEN = max(len(m) for m in _HOLD_MARKERS)

_THINK_BLOCK_RE = re.compile(r"<think(?:ing|_cont)?>[\s\S]*?</think(?:ing|_cont)?>", re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think(?:ing|_cont)?>[\s\S]*\Z", re.IGNORECASE)


def strip_think_blocks(text: str) -> str:
    """剥离成对的 <think>/<thinking>/<think_cont> 思考块；未闭合的从开标签删到结尾。"""
    if not text:
        return text
    text = _THINK_BLOCK_RE.sub("", text)
    text = _THINK_OPEN_RE.sub("", text)
    return text


def estimate_tokens(text: str) -> int:
    """无 tokenizer 时的粗略 Token 估算（兜底用，服务端 usage 优先）：
    CJK ≈ 1.0 token/字（实测中文 GGUF 分词普遍 1~2 token/字，取保守值防止低估导致超上下文），
    其他字符 ≈ 0.3 token/字符"""
    if not text:
        return 0
    cjk = 0
    total = 0
    for ch in text:
        total += 1
        if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f":
            cjk += 1
    other = total - cjk
    return max(1, int(cjk * 1.0 + other * 0.3))


def sanitize_history_text(text: str):
    """入史层深度清洗：剥离思考块 → 截断幻觉续写（下一轮标记）→ 剥离特殊 token。
    Returns (清洗后的文本, 是否触发过截断)
    """
    if not text:
        return text, False
    text = strip_think_blocks(text)
    best_pos = None
    for m in _NEXT_TURN_MARKERS:
        pos = text.find(m)
        if pos != -1 and (best_pos is None or pos < best_pos):
            best_pos = pos
    truncated = best_pos is not None
    if truncated:
        text = text[:best_pos]
    return _strip_half_open_tags(_strip_special_tokens(text)), truncated


class ThinkStreamFilter:
    """跨 chunk 安全的思考内容过滤器（Web 端用）：
    剥离 <think> / <thinking> / <think_cont> 包裹的思考段（含跨 chunk 拆分与未闭合尾巴）。
    feed() 返回本次可见文本增量；流结束后调用 flush() 取回残余。
    """
    _OPENS = ("<think_cont>", "<think>", "<thinking>")
    _CLOSES = ("</think_cont>", "</think>", "</thinking>")

    def __init__(self):
        self._buf = ""
        self._in_think = False

    def _longest_suffix_prefix(self, tags) -> int:
        """buf 末尾 k 个字符是某标签的前缀（标签本体除外）→ 返回最大 k"""
        buf = self._buf
        limit = min(len(buf), max(len(t) for t in tags) - 1)
        for k in range(limit, 0, -1):
            tail = buf[-k:]
            for t in tags:
                if t.startswith(tail):
                    return k
        return 0

    def feed(self, text: str) -> str:
        self._buf += text
        out = []
        while True:
            if self._in_think:
                pos, hit = -1, None
                for c in self._CLOSES:
                    p = self._buf.find(c)
                    if p != -1 and (pos == -1 or p < pos):
                        pos, hit = p, c
                if pos == -1:
                    # 全是思考内容；保留可能是关闭标签前缀的尾部，其余丢弃
                    keep = self._longest_suffix_prefix(self._CLOSES)
                    self._buf = self._buf[len(self._buf) - keep:] if keep else ""
                    return "".join(out)
                end = pos + len(hit)
                # 思考块后紧跟的空行一并吞掉，避免残留空行
                while end < len(self._buf) and self._buf[end] in "\r\n":
                    end += 1
                self._buf = self._buf[end:]
                self._in_think = False
                continue
            pos, hit = -1, None
            for o in self._OPENS:
                p = self._buf.find(o)
                if p != -1 and (pos == -1 or p < pos):
                    pos, hit = p, o
            if pos == -1:
                keep = self._longest_suffix_prefix(self._OPENS)
                emit_len = len(self._buf) - keep
                if emit_len > 0:
                    out.append(self._buf[:emit_len])
                    self._buf = self._buf[emit_len:]
                return "".join(out)
            out.append(self._buf[:pos])
            self._buf = self._buf[pos + len(hit):]
            self._in_think = True

    def flush(self) -> str:
        rest, self._buf = self._buf, ""
        if self._in_think:
            return ""  # 思考未闭合：残余内容全部丢弃
        return rest

class LLMClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8080", api_key: str = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        if api_key:
            self.session.headers.update({"Authorization": f"Bearer {api_key}"})
        # 最近一次请求的 token 用量（prompt_tokens / completion_tokens），
        # 流式由 stream_options.include_usage 的最后一个 chunk 填充
        self.last_usage = None

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        stream: bool = False,
        system_prompt: str = None,
    ) -> dict:
        """非流式聊天补全"""
        url = f"{self.base_url}/v1/chat/completions"

        msgs = messages
        if system_prompt and not any(m["role"] == "system" for m in messages):
            msgs = [{"role": "system", "content": system_prompt}] + messages

        payload = {
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
            "top_p": 0.90,
            "repeat_penalty": 1.10,
            "frequency_penalty": 0.06,
            "presence_penalty": 0.04,
            # 显式停止词：让 llama-server 真正遇到 EOT 就停（不再把 <|im_end|> 当普通文本吐回来）
            "stop": [
                "<|end_of_text|>",
                "<|end_of_turn|>",
                "<|eot_id|>",
                "<|im_end|>",
                "<|im_start|>",  # 极端：如果模型开始吐下一轮，立刻停
            ],
        }

        response = self.session.post(url, json=payload, timeout=(10, 180))
        response.raise_for_status()
        response.encoding = "utf-8"  # 强制 UTF-8
        data = response.json()
        if isinstance(data, dict):
            self.last_usage = data.get("usage")
        return data

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: str = None,
    ) -> Generator[str, None, None]:
        """流式聊天补全（生成器方式）
        说明：
          - 兼容 llama.cpp / Ollama / DeepSeek 等多种 SSE 服务端。
          - 如果 delta.reasoning_content 存在（推理链/思维链），会以 <think>..</think>
            的形式拼回来让上层 `<think>` 分流器正确识别，不丢 token。
          - 如果整体结构不是 {choices:[{delta:{}}]}（例如旧版 llama / 非 chat 接口），
            会退而求其次尝试各种常见字段名。
        """
        url = f"{self.base_url}/v1/chat/completions"

        msgs = messages
        if system_prompt and not any(m["role"] == "system" for m in messages):
            msgs = [{"role": "system", "content": system_prompt}] + messages

        payload = {
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "top_p": 0.90,
            "repeat_penalty": 1.10,
            "frequency_penalty": 0.06,
            "presence_penalty": 0.04,
            # 显式停止词：llama-server 遇到这些就立即停止 SSE，防止把 EOT / 下一轮标记当普通文本吐回来
            "stop": [
                "<|end_of_text|>",
                "<|end_of_turn|>",
                "<|eot_id|>",
                "<|im_end|>",
                "<|im_start|>",
            ],
            # 让 llama-server 在流末尾附带 token 用量（usage.prompt_tokens / completion_tokens）
            "stream_options": {"include_usage": True},
        }

        self.last_usage = None  # 重置本轮用量

        # 流式请求：
        #  connect_timeout=10   → 10秒内建不上连接立刻抛（而不是 5 分钟等无响应）
        #  read_timeout=55     → 首 token 之前最多等 55 秒（模型冷启动后首 token 可能慢）
        # 一旦开始流式，后续 token 之间只要 < 55 秒就行；避免 llama-server 卡住时 UI 5 分钟死等
        with self.session.post(url, json=payload, stream=True,
                               timeout=(10, 55)) as response:
            if response.status_code != 200:
                error_body = ""
                try:
                    error_body = response.text
                except Exception:
                    pass
                raise Exception(
                    f"HTTP {response.status_code} {response.reason}\n"
                    f"URL: {url}\n"
                    f"请求: {len(msgs)} 条消息\n"
                    f"响应: {error_body[:500]}"
                )

            response.encoding = "utf-8"
            _trailing_tail = ""  # 尚未发出的尾缓冲：仅用于跨 chunk"下一轮标记"检测（绝不重复输出）
            _in_rc = False       # 是否正处于 reasoning 思考流中（<think_cont> 只包裹一次）
            for line_bytes in response.iter_lines(decode_unicode=False):
                if not line_bytes:
                    continue
                line = _safe_decode(line_bytes)
                # SSE 事件：有时会是 `event: message` / `data: {...}` 成对
                if not line.startswith("data:"):
                    # 跳过 SSE event/retry/id 元信息行以及空注释
                    stripped = line.lstrip()
                    if stripped.startswith(":"):
                        continue  # SSE 注释
                    if any(stripped.startswith(prefix + ":") for prefix in ("event", "retry", "id")):
                        continue
                    # 最后兜底：有些服务器错误地没有 "data: " 前缀
                    if stripped.startswith("{"):
                        data = stripped
                    else:
                        continue
                else:
                    data = line[5:].strip()  # 兼容 "data:" / "data: " 及行尾 \r

                if not data:
                    continue
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    # 不再静默 pass：尝试输出到 stderr 以便调试，然后继续
                    sys.stderr.write(f"[llm_client] 无法解析 SSE data: {data[:160]!r}\n")
                    sys.stderr.flush()
                    continue

                # 捕获流末尾的 token 用量 chunk（choices 为空、仅含 usage）
                u = chunk.get("usage") if isinstance(chunk, dict) else None
                if isinstance(u, dict) and u.get("prompt_tokens") is not None:
                    self.last_usage = u

                # --- 兼容不同 SSE 结构 ---
                text = ""

                # 结构 A：标准 OpenAI：choices[0].delta.{content, reasoning_content}
                if isinstance(chunk.get("choices"), list) and chunk["choices"]:
                    delta = chunk["choices"][0].get("delta", {}) or {}
                    if isinstance(delta, str):
                        text = delta
                        delta = {}

                    rc = delta.get("reasoning_content") if isinstance(delta, dict) else None
                    cc = delta.get("content") if isinstance(delta, dict) else None

                    # 推理链：<think_cont> 只在思考流开始/结束时包裹一次（逐 token 包裹会让
                    # UI 反复 start/finish 思考态并闪烁计时器）
                    if rc:
                        if not _in_rc:
                            text += "<think_cont>"
                            _in_rc = True
                        text += rc
                    if cc:
                        if _in_rc:
                            text += "</think_cont>"
                            _in_rc = False
                        text += cc

                    # 有些服务可能放 message.content 而不是 delta
                    if not text and isinstance(chunk["choices"][0].get("message"), dict):
                        mc = chunk["choices"][0]["message"].get("content")
                        if isinstance(mc, str):
                            text = mc

                # 结构 B：Ollama: {response: "..."}
                if not text and isinstance(chunk.get("response"), str):
                    text = chunk["response"]

                # 结构 C: llama.cpp 非 chat：{content: "..."}
                if not text and isinstance(chunk.get("content"), str):
                    text = chunk["content"]

                if text:
                    # 跨 chunk 下一轮检测：把尚未发出的尾缓冲与本次文本合并检查
                    combined = _trailing_tail + text
                    cut_pos, _hit = _find_next_turn_marker(combined)
                    if cut_pos is not None:
                        # 命中"下一轮开始"：尾缓冲从未发出过，combined[:cut_pos] 全部是
                        # 未发送内容，清洗后发出然后立即终止，防止幻觉无限续写
                        safe_part = combined[:cut_pos]
                        if _in_rc:
                            safe_part += "</think_cont>"
                            _in_rc = False
                        safe_part = _strip_half_open_tags(_strip_special_tokens(safe_part))
                        if safe_part:
                            yield safe_part
                        return  # 强制结束
                    # 未命中：计算末尾有多少字符可能是"下一轮标记"的前缀（跨 chunk 拆分场景），
                    # 这几个字符扣住不发、并入下一轮检测；其余内容清洗后发出（只发一次，不重复）
                    hold = 0
                    for k in range(min(_MAX_MARKER_LEN, len(combined)), 0, -1):
                        cand = combined[-k:]
                        if any(m.startswith(cand) for m in _HOLD_MARKERS):
                            hold = k
                            break
                    emit_part = combined[:-hold] if hold else combined
                    cleaned = _strip_half_open_tags(_strip_special_tokens(emit_part))
                    if cleaned:
                        yield cleaned
                    _trailing_tail = combined[-hold:] if hold else ""

            # 流正常结束（非截断 return）：把扣住的尾缓冲和未闭合的思考流收尾发出去
            if _trailing_tail:
                cleaned = _strip_half_open_tags(_strip_special_tokens(_trailing_tail))
                _trailing_tail = ""
                if cleaned:
                    yield cleaned
            if _in_rc:
                _in_rc = False
                yield "</think_cont>"

    def code_action_stream(
        self,
        action: str,
        code: str,
        filename: str = "",
        description: str = "",
        error_message: str = "",
        goal: str = "",
        test_framework: str = "pytest",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: str = None,
    ) -> Generator[str, None, None]:
        """代码动作流式输出"""
        from .prompts import (
            CODE_EXPLAIN_TEMPLATE,
            CODE_REVIEW_TEMPLATE,
            CODE_REFACTOR_TEMPLATE,
            BUG_FIX_TEMPLATE,
            TEST_GENERATE_TEMPLATE,
            build_code_generate_prompt,
            build_system_prompt,
        )

        if action == "generate":
            user_message = build_code_generate_prompt(requirement=description)
        elif action == "explain":
            user_message = CODE_EXPLAIN_TEMPLATE.format(filename=filename, code=code)
        elif action == "review":
            user_message = CODE_REVIEW_TEMPLATE.format(filename=filename, code=code)
        elif action == "refactor":
            user_message = CODE_REFACTOR_TEMPLATE.format(
                filename=filename, code=code, goal=goal or "提升代码质量和可维护性"
            )
        elif action == "bugfix":
            user_message = BUG_FIX_TEMPLATE.format(
                filename=filename,
                description=description,
                error_message=error_message or "无",
                code=code,
            )
        elif action == "test":
            user_message = TEST_GENERATE_TEMPLATE.format(
                filename=filename, code=code, test_framework=test_framework
            )
        else:
            raise ValueError(f"未知动作：{action}")

        sys_prompt = system_prompt or build_system_prompt(action)
        messages = [{"role": "user", "content": user_message}]

        yield from self.chat_stream(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=sys_prompt,
        )

    def get_models(self) -> dict:
        """获取模型列表"""
        try:
            response = self.session.get(f"{self.base_url}/v1/models", timeout=5)
            response.encoding = "utf-8"
            return response.json()
        except Exception:
            return {"data": [], "error": "无法连接到 llama-server"}

    def get_health(self) -> dict:
        """健康检查"""
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=3)
            response.encoding = "utf-8"
            return {"status": "ok" if response.status_code == 200 else "error"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def close(self):
        self.session.close()
