"""
角色管理器 - 管理角色扮演功能（游戏世界模式）

角色文件夹结构：
  characters/<角色名>/
    角色基础模板.txt     ← AI 角色模板（背景 + 核心属性值 + 行为逻辑 + 互动）
    玩家模板.txt         ← 玩家背景模板（仅背景）
    游戏背景_编号.txt     ← 生成的游戏世界设定（编号=创建时间）
    icon.png
    sessions/
      <角色名_编号>/      ← 对话文件夹（编号=创建时间）
        游戏背景.txt      ← 从角色级 游戏背景_编号.txt 复制
        对话历史.txt      ← 第N轮:>玩家输入=xxx / >AI=输出xxx
        角色属性.txt      ← 最新角色属性值（纯数字，每轮由 AI 输出更新）
        history.txt       ← 旧格式历史（兼容旧会话）
"""
import os
import re
import time
import json
import shutil
from typing import List, Dict, Optional


def _ts() -> str:
    """时间戳编号：YYYYMMDD_HHMMSS"""
    return time.strftime("%Y%m%d_%H%M%S")


def extract_attr_numbers(text: str) -> str:
    """从 AI 回复中提取 '角色属性:11 22 33 ...' 纯数字属性行。
    Returns:
        纯数字属性字符串（如 "85 60 90"），未找到返回 ""
    """
    if not text:
        return ""
    # 匹配 角色属性[:：] 后面跟数字/空格/小数点/换行的串
    m = re.search(r"角色属性\s*[:：]\s*([\d][\d\s.，,\-]*)", text)
    if not m:
        return ""
    raw = m.group(1)
    # 提取所有数字（支持中英文逗号分隔）
    nums = re.findall(r"\d+(?:\.\d+)?", raw)
    if not nums:
        return ""
    return " ".join(nums)


def build_world_prompt(template: str, player_template: str) -> List[Dict]:
    """构建『生成对话世界』的消息（第一步：让 AI 构建玩家与角色共同生活的世界）"""
    prompt = (
        f"角色定义:n\n{template}\n\n"
        f"玩家定义:n\n{player_template}\n\n"
        f"请根据以上角色定义（含其核心属性值）和玩家定义，构建一个玩家和角色共同生活的完整世界，"
        f"必须包含以下全部内容：\n"
        f"1. 玩家的日常生活\n"
        f"2. 角色的日常生活\n"
        f"3. 玩家的交际圈（家人、朋友、同事等具体人物）\n"
        f"4. 角色的交际圈（家人、朋友、同事等具体人物）\n"
        f"5. 玩家和角色所生活地区的所有可以互动的场所、地点\n"
        f"6. 玩家和角色所有的社交方式\n\n"
        f"直接输出这个世界设定本身，不要任何解释、前言或格式说明。世界设定描述的总字数不能超过1000字，输出内容只能包含汉字，字母，逗号，句号和、。"
    )
    return [{"role": "user", "content": prompt}]


def _clip_prev_outputs_by_token_budget(
    prev_ai_outputs: List[str],
    budget_tokens: int = 5000,
) -> List[str]:
    """按 token 预算从最早的开始丢弃 prev_ai_outputs，直到累计 token ≤ budget_tokens

    使用 estimate_tokens（CJK≈0.65 token/字）估算。游戏模式 AI 单轮输出通常 3000-5000 tokens，
    预算 5000 能稳定保留最近 1-2 轮，防止历史爆炸。
    """
    try:
        from core.llm_client import estimate_tokens
    except Exception:
        estimate_tokens = lambda t: len(t) // 2  # 兜底估算

    # 从最新到最早累加，超限就丢弃更早的
    kept: List[str] = []
    used = 0
    for out in reversed(prev_ai_outputs):
        t = estimate_tokens(out)
        if used + t <= budget_tokens or not kept:
            # 至少保留最新的 1 轮（即使超预算也不能丢光）
            kept.insert(0, out)
            used += t
        else:
            break
    return kept


def _est(text: str) -> float:
    """估算 tokens（延迟导入避免循环依赖；失败时按 2 字符/token 兜底）"""
    try:
        from core.llm_client import estimate_tokens
    except Exception:
        return len(text or "") / 2.0
    return float(estimate_tokens(text or ""))


def _clip_text_keep_head_tail(text: str, budget_tokens: int, safety: float = 1.0) -> str:
    """把文本裁到估算 tokens ≤ budget_tokens：保留开头与结尾，去掉中段（游戏背景用）"""
    if not text or _est(text) * safety <= budget_tokens:
        return text
    target_chars = max(0, int(len(text) * budget_tokens / max(1.0, _est(text) * safety)))
    head_len = int(target_chars * 0.4)
    tail_len = target_chars - head_len
    clipped = text[:head_len] + "……" + (text[-tail_len:] if tail_len > 0 else "")
    while clipped and _est(clipped) * safety > budget_tokens and target_chars > 20:
        target_chars = int(target_chars * 0.8)
        head_len = int(target_chars * 0.4)
        tail_len = target_chars - head_len
        clipped = text[:head_len] + "……" + (text[-tail_len:] if tail_len > 0 else "")
    return clipped


def _clip_text_keep_tail(text: str, budget_tokens: int, safety: float = 1.0) -> str:
    """把文本裁到估算 tokens ≤ budget_tokens：只保留尾部
    （最新一轮对话的 游戏内时间/行为选择/角色属性 都在尾部）"""
    if not text or _est(text) * safety <= budget_tokens:
        return text
    target_chars = max(0, int(len(text) * budget_tokens / max(1.0, _est(text) * safety)))
    clipped = text[-target_chars:] if target_chars > 0 else ""
    while clipped and _est(clipped) * safety > budget_tokens and target_chars > 20:
        target_chars = int(target_chars * 0.8)
        clipped = text[-target_chars:]
    return clipped


# 行为选项行：&1.xxx / & 2、xxx 等（可带 < 结尾）
_OPT_LINE_RE = re.compile(r"^\s*&\s*\d+\s*[.、．]?")
# 内联选项段：&1.xxx 直到 < 或行尾（避免误伤"你选择了&1.xxx"由调用处排除）
_OPT_INLINE_RE = re.compile(r"&\s*\d+\s*[.、．]?[^&\n<]{0,120}(?=<|$)")


def _strip_ai_options(text: str) -> str:
    """剔除历史 AI 输出中的行为选项列表，减少 prompt 冗余

    - 删除以 &数字 开头的选项行（选项列表，无论单行还是多行排列）
    - 其余行中的内联选项段（&数字.内容 接 < 或行尾）也剔除
    - 保留玩家选择记录行（"你选择了&1.xxx"），因为包含玩家实际选择的内容
    """
    if not text:
        return text
    kept: List[str] = []
    for ln in text.splitlines():
        if _OPT_LINE_RE.match(ln):
            continue
        if "你选择了" in ln or "你选了" in ln:
            kept.append(ln)
            continue
        cleaned = _OPT_INLINE_RE.sub("", ln)
        if cleaned != ln:
            # 去掉剔除后残留的悬空分隔符（如行首的 < 、连续逗号）
            cleaned = re.sub(r"^[\s<>，,、]+", "", cleaned)
        if cleaned.strip():
            kept.append(cleaned.rstrip())
    return "\n".join(kept)


def build_game_round_prompt(
    char_name: str,
    template: str,
    player_template: str,
    background: str,
    prev_ai_outputs: List[str],
    current_attrs: str,
    user_input: str,
    history_token_budget: int = 5000,
    total_token_budget: int = 0,
) -> List[Dict]:
    """构建游戏内每轮对话的消息（严格按玩家定义的格式）

    Args:
        char_name: AI 角色名
        template: 角色基础模板内容（角色定义）
        player_template: 玩家模板内容（玩家定义）
        background: 游戏背景内容
        prev_ai_outputs: 前面 N 次对话里 AI 返回的内容（按时间顺序，由玩家指定轮数）
        current_attrs: 最新角色属性值（纯数字；首轮为空，用模板初始属性）
        user_input: 玩家本轮输入
        history_token_budget: 历史 AI 输出的 token 预算上限（默认 5000），超了就从最早丢弃
        total_token_budget: 整条 prompt 的 token 总预算（估算×安全系数）。
            >0 时依次裁剪：游戏背景(保留头尾) → 丢弃更早历史轮 → 保留最新一轮的尾部。
            角色定义/玩家定义/输出指令永不裁剪，保证角色与输出格式完整。
            需求来源：llama-server 的 ctx 是 prompt+output 共享，
            prompt 超限会报 "request (N tokens) exceeds the available context size"。
    """
    # 先剔除历史 AI 输出中的行为选项列表（保留玩家选择记录），再按预算截断
    prev_ai_outputs = [_strip_ai_options(o) for o in prev_ai_outputs]
    # token 预算保护：历史 AI 输出按预算截断，防止 token 爆炸
    prev_ai_outputs = _clip_prev_outputs_by_token_budget(prev_ai_outputs, history_token_budget)

    instruction = (
        f"你是角色定义内容描述的角色，你据有角色定义内容内定义的属性，"
        f"我是与你互动的角色，我的背景是游戏背景中的内容描述的，"
        f"我俩共同生活在游戏背景中的内容描述的世界里。"
        f"你需要参照之前的对话和角色定义、玩家定义、游戏背景与游戏内当前时间"
        f"继续构建一个与之前对话的故事情节紧密的故事环节，"
        f"在角色定义中行为逻辑与互动预设的基础上，要非常频繁地拓展续写新的虚拟场景与情节。"
        f"你需要输出的内容的格式如下:\n"
        f"你选择了&n.XXXX(玩家给你的行为选择，如果玩家没有给出选择，请视为玩家做出了自定义选择，即输入了自定义的内容)"
        f"场景的描写(包括地点，所有人物，发生的情景，玩家和你扮演的角色的互动内容)，你扮演的角色的行为和对玩家行为的反应，你扮演的角色的身体外观，心理活动,身体生理情况,四肢情况，衣服服装情况，表情情况，性器官情况(表征性渴望),单项不少于100字，不超过200字。整体应该使得故事剧情总体连贯合理，对玩家有心理冲击，角色塑造对玩家具有极高的性吸引力和心理吸引力，可以让玩家沉浸式体验与角色互动。游戏后期随着与角色互动可以解锁性行为和女主角怀孕生子，结婚等剧情。总字数不少于2500字，不多于3000字。输出格式为￥开头接选项的数字序号接输出内容接<"
        f"游戏内当前时间(按照上个对话场景和玩家的选择推演时间)\n"
        f"玩家的所有可以的行为选择:数量要求为不少于20种，不多于30种。(按照 &1.XXXX< &2.XXX< 这样排列[&开头接选项的数字序号接选项内容接< 注意每行一个选项])\n"
        f"角色属性:(你扮演的角色的属性，按照11 22 .... 这样的纯数字输出，用于下次对话读取)"
    )

    def _assemble(bg_text: str, outputs: List[str]) -> str:
        parts = [f"角色定义:n\n{template}"]
        if current_attrs:
            parts.append(f"角色当前属性值:n\n{current_attrs}")
        parts.append(f"玩家定义:n\n{player_template}")
        parts.append(f"游戏背景:n\n{bg_text}")
        for i, out in enumerate(outputs, 1):
            parts.append(f"前面第{i}次对话:n\n{out}")
        parts.append(f"{instruction}\n\n玩家输入:n\n{user_input}")
        return "\n\n".join(parts)

    safety = 1.2  # 估算系数偏乐观时的安全余量（真实分词普遍比估算多 10%~30%）

    content = _assemble(background, prev_ai_outputs)

    if total_token_budget > 0:
        # ① 游戏背景按预算保留头尾（角色定义/玩家定义/指令不动）
        fixed_wo_bg = _est(_assemble("", prev_ai_outputs)) * safety
        bg_use = _clip_text_keep_head_tail(
            background, max(0, int(total_token_budget - fixed_wo_bg)), safety
        ) if background else background
        content = _assemble(bg_use, prev_ai_outputs)

        # ② 仍超 → 从最早一轮开始丢弃（至少保留最新 1 轮）
        while len(prev_ai_outputs) > 1 and _est(content) * safety > total_token_budget:
            prev_ai_outputs.pop(0)
            content = _assemble(bg_use, prev_ai_outputs)

        # ③ 仍超 → 保留最新一轮的尾部（时间/行为选择/角色属性在尾部）
        if _est(content) * safety > total_token_budget and prev_ai_outputs:
            newest = prev_ai_outputs[-1]
            tail_budget = max(
                200, int(total_token_budget - (_est(content) - _est(newest)) * safety)
            )
            prev_ai_outputs[-1] = _clip_text_keep_tail(newest, tail_budget, safety)
            content = _assemble(bg_use, prev_ai_outputs)

    return [{"role": "user", "content": content}]


# 对话历史.txt 新格式解析：第N轮:>玩家输入=xxx\n>AI=输出xxx
_RE_ROUND = re.compile(
    r"第(\d+)轮\s*[:：]?\s*>玩家输入=([\s\S]*?)\n>AI=输出([\s\S]*?)(?=\n第\d+轮\s*[:：]?\s*>玩家输入=|\Z)"
)


class Character:
    """角色类"""

    def __init__(self, name: str, folder_path: str):
        self.name = name
        self.folder_path = folder_path
        self.template_file = os.path.join(folder_path, "角色基础模板.txt")
        self.initial_attrs_file = os.path.join(folder_path, "initial_attrs.txt")
        self.player_template_file = os.path.join(folder_path, "玩家模板.txt")
        self.voice_file = os.path.join(folder_path, "音色.txt")
        self.clone_audio_file = os.path.join(folder_path, "音色音频.txt")
        self.icon_file = os.path.join(folder_path, "icon.png")
        self.sessions_dir = os.path.join(folder_path, "sessions")

    # ---------- 音色（CosyVoice TTS 配音） ----------

    def get_voice(self) -> str:
        """角色音色（音色.txt），未设置返回空字符串"""
        if os.path.exists(self.voice_file):
            try:
                with open(self.voice_file, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            except Exception:
                pass
        return ""

    def set_voice(self, voice: str):
        """保存角色音色（空字符串=删除文件，回退全局默认）"""
        try:
            voice = (voice or "").strip()
            if not voice:
                if os.path.exists(self.voice_file):
                    os.remove(self.voice_file)
                return
            os.makedirs(self.folder_path, exist_ok=True)
            with open(self.voice_file, 'w', encoding='utf-8') as f:
                f.write(voice)
        except Exception:
            pass

    def get_clone_audio(self) -> str:
        """角色克隆参考音频路径（音色音频.txt），未设置返回空字符串"""
        if os.path.exists(self.clone_audio_file):
            try:
                with open(self.clone_audio_file, 'r', encoding='utf-8') as f:
                    p = f.read().strip()
                if p and os.path.isfile(p):
                    return p
            except Exception:
                pass
        return ""

    def set_clone_audio(self, path: str):
        """保存角色克隆参考音频路径（空字符串=删除文件，回退全局默认）"""
        try:
            path = (path or "").strip()
            if not path:
                if os.path.exists(self.clone_audio_file):
                    os.remove(self.clone_audio_file)
                return
            os.makedirs(self.folder_path, exist_ok=True)
            with open(self.clone_audio_file, 'w', encoding='utf-8') as f:
                f.write(path)
        except Exception:
            pass

    # ---------- 模板 / 游戏背景 ----------

    def get_template(self) -> str:
        """AI 角色基础模板（新角色：角色基础模板.txt；旧角色回退 initial_attrs.txt）"""
        if os.path.exists(self.template_file):
            try:
                with open(self.template_file, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception:
                pass
        return self.initial_attrs  # 旧角色兼容

    def get_player_template(self) -> str:
        """玩家模板（仅玩家背景）"""
        if os.path.exists(self.player_template_file):
            try:
                with open(self.player_template_file, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception:
                pass
        return ""

    def get_latest_world_file(self) -> str:
        """角色级最新的 游戏背景_编号.txt 路径（无则返回 ""）"""
        if not os.path.isdir(self.folder_path):
            return ""
        best, best_ts = "", ""
        for fn in os.listdir(self.folder_path):
            if fn.startswith("游戏背景_") and fn.endswith(".txt"):
                ts = fn[len("游戏背景_"):-len(".txt")]
                if ts >= best_ts:  # 字典序=时间序
                    best_ts, best = ts, os.path.join(self.folder_path, fn)
        return best

    def save_world_file(self, world_text: str) -> str:
        """保存生成的游戏世界为 角色文件夹/游戏背景_编号.txt，返回路径"""
        path = os.path.join(self.folder_path, f"游戏背景_{_ts()}.txt")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(world_text)
        return path

    # ---------- 游戏会话（对话文件夹） ----------

    def create_game_session(self, world_src: str = None) -> str:
        """创建游戏对话文件夹 <角色名_编号>/：复制游戏背景.txt + 空 对话历史.txt

        Args:
            world_src: 游戏背景_编号.txt 源文件；None 时自动取最新，仍无则写空背景
        """
        os.makedirs(self.sessions_dir, exist_ok=True)
        session_path = os.path.join(self.sessions_dir, f"{self.name}_{_ts()}")
        os.makedirs(session_path, exist_ok=True)

        src = world_src or self.get_latest_world_file()
        bg_file = os.path.join(session_path, "游戏背景.txt")
        if src and os.path.exists(src):
            shutil.copy2(src, bg_file)
        else:
            with open(bg_file, 'w', encoding='utf-8') as f:
                f.write("")

        # 空对话历史
        hist_file = os.path.join(session_path, "对话历史.txt")
        if not os.path.exists(hist_file):
            with open(hist_file, 'w', encoding='utf-8') as f:
                f.write("")

        # 初始角色属性：从模板提取（首轮用模板属性；后续轮由 AI 输出覆盖）
        attrs_file = os.path.join(session_path, "角色属性.txt")
        if not os.path.exists(attrs_file):
            with open(attrs_file, 'w', encoding='utf-8') as f:
                f.write("")
        return session_path

    def get_game_background(self, session_path: str) -> str:
        """读取会话的游戏背景"""
        bg_file = os.path.join(session_path, "游戏背景.txt")
        if os.path.exists(bg_file):
            try:
                with open(bg_file, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception:
                pass
        return ""

    def is_game_session(self, session_path: str) -> bool:
        """是否为游戏式会话（含 对话历史.txt）"""
        return os.path.exists(os.path.join(session_path, "对话历史.txt"))

    # ---------- 对话历史（新格式） ----------

    def append_dialog_round(self, session_path: str, round_no: int, user_text: str, ai_text: str):
        """追加一轮对话到 对话历史.txt：第N轮:>玩家输入=xxx\n>AI=输出xxx"""
        hist_file = os.path.join(session_path, "对话历史.txt")
        os.makedirs(os.path.dirname(hist_file), exist_ok=True)
        user_text = (user_text or "").strip().replace("\r", "")
        ai_text = (ai_text or "").strip().replace("\r", "")
        with open(hist_file, 'a', encoding='utf-8') as f:
            f.write(f"第{round_no}轮:>玩家输入={user_text}\n")
            f.write(f">AI=输出{ai_text}\n")

    def get_dialog_history(self, session_path: str) -> List[Dict]:
        """解析 对话历史.txt → [{round, user, ai}]（新格式）"""
        hist_file = os.path.join(session_path, "对话历史.txt")
        rounds = []
        if not os.path.exists(hist_file):
            return rounds
        try:
            with open(hist_file, 'r', encoding='utf-8') as f:
                content = f.read()
            for m in _RE_ROUND.finditer(content):
                rounds.append({
                    "round": int(m.group(1)),
                    "user": m.group(2).strip(),
                    "ai": m.group(3).strip(),
                })
        except Exception:
            pass
        return rounds

    def save_dialog_history(self, session_path: str, messages: List[Dict]):
        """把 user/assistant 消息列表整写到 对话历史.txt（新格式）"""
        hist_file = os.path.join(session_path, "对话历史.txt")
        os.makedirs(os.path.dirname(hist_file), exist_ok=True)
        lines = []
        round_no = 0
        pending_user = None
        for msg in messages:
            if msg["role"] == "user":
                pending_user = msg["content"]
            elif msg["role"] == "assistant":
                round_no += 1
                user_text = (pending_user or "").strip().replace("\r", "")
                ai_text = (msg["content"] or "").strip().replace("\r", "")
                lines.append(f"第{round_no}轮:>玩家输入={user_text}\n>AI=输出{ai_text}\n")
                pending_user = None
        with open(hist_file, 'w', encoding='utf-8') as f:
            f.write("".join(lines))

    # ---------- 角色属性（游戏式：每轮替换为最新值） ----------

    def get_game_attrs(self, session_path: str) -> str:
        """读取会话最新角色属性值（纯数字）"""
        attrs_file = os.path.join(session_path, "角色属性.txt")
        if os.path.exists(attrs_file):
            try:
                with open(attrs_file, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            except Exception:
                pass
        return ""

    def set_game_attrs(self, session_path: str, attrs: str):
        """写入最新角色属性值（整写替换：属性随每轮变化，最新值生效）"""
        attrs_file = os.path.join(session_path, "角色属性.txt")
        os.makedirs(os.path.dirname(attrs_file), exist_ok=True)
        with open(attrs_file, 'w', encoding='utf-8') as f:
            f.write((attrs or "").strip())

    # ---------- 旧版接口（兼容） ----------

    @property
    def initial_attrs(self) -> str:
        """获取初始属性（旧版兼容）"""
        if os.path.exists(self.initial_attrs_file):
            with open(self.initial_attrs_file, 'r', encoding='utf-8') as f:
                return f.read()
        return ""

    @property
    def has_icon(self) -> bool:
        """是否有自定义图标"""
        return os.path.exists(self.icon_file)

    def get_sessions(self) -> List[Dict]:
        """获取所有会话列表"""
        sessions = []
        if not os.path.exists(self.sessions_dir):
            return sessions

        for session_name in os.listdir(self.sessions_dir):
            session_path = os.path.join(self.sessions_dir, session_name)
            if os.path.isdir(session_path):
                history_file = os.path.join(session_path, "history.txt")
                dialog_file = os.path.join(session_path, "对话历史.txt")
                attrs_file = os.path.join(session_path, "character_attrs.txt")
                game_attrs_file = os.path.join(session_path, "角色属性.txt")
                sessions.append({
                    "name": session_name,
                    "path": session_path,
                    "has_history": os.path.exists(history_file),
                    "has_attrs": os.path.exists(attrs_file),
                    "is_game": os.path.exists(dialog_file),
                    "has_game_attrs": os.path.exists(game_attrs_file),
                    "created_time": os.path.getctime(session_path) if os.path.exists(session_path) else 0,
                })

        # 按创建时间排序（最新的在前）
        sessions.sort(key=lambda x: x["created_time"], reverse=True)
        return sessions

    def create_session(self, session_name: str = None) -> str:
        """创建旧式会话（兼容保留；游戏式请用 create_game_session）"""
        if not session_name:
            session_name = _ts()

        session_path = os.path.join(self.sessions_dir, session_name)
        os.makedirs(session_path, exist_ok=True)

        # 复制初始属性作为会话的角色属性
        attrs_file = os.path.join(session_path, "character_attrs.txt")
        if os.path.exists(self.initial_attrs_file):
            shutil.copy2(self.initial_attrs_file, attrs_file)
        else:
            with open(attrs_file, 'w', encoding='utf-8') as f:
                f.write("")

        # 创建空的历史记录文件
        history_file = os.path.join(session_path, "history.txt")
        if not os.path.exists(history_file):
            with open(history_file, 'w', encoding='utf-8') as f:
                f.write("")

        return session_path

    def get_session_history(self, session_path: str) -> List[Dict]:
        """读取会话历史（优先新格式 对话历史.txt，回退旧格式 history.txt）"""
        # 新格式
        if self.is_game_session(session_path):
            msgs = []
            for r in self.get_dialog_history(session_path):
                msgs.append({"role": "user", "content": r["user"]})
                msgs.append({"role": "assistant", "content": r["ai"]})
            return msgs

        # 旧格式
        history_file = os.path.join(session_path, "history.txt")
        messages = []

        if not os.path.exists(history_file):
            return messages

        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                content = f.read()

            lines = content.split('\n')
            current_role = None
            current_content = []

            for line in lines:
                if line.strip() == "=== USER ===":
                    if current_role and current_content:
                        messages.append({"role": current_role, "content": "\n".join(current_content).strip()})
                    current_role = "user"
                    current_content = []
                elif line.strip() == "=== ASSISTANT ===":
                    if current_role and current_content:
                        messages.append({"role": current_role, "content": "\n".join(current_content).strip()})
                    current_role = "assistant"
                    current_content = []
                else:
                    current_content.append(line)

            if current_role and current_content:
                messages.append({"role": current_role, "content": "\n".join(current_content).strip()})

        except Exception:
            pass

        return messages

    def save_session_history(self, session_path: str, messages: List[Dict]):
        """保存会话历史（游戏式写 对话历史.txt，旧式写 history.txt）"""
        if self.is_game_session(session_path):
            self.save_dialog_history(session_path, messages)
            return

        history_file = os.path.join(session_path, "history.txt")
        os.makedirs(os.path.dirname(history_file), exist_ok=True)

        with open(history_file, 'w', encoding='utf-8') as f:
            for msg in messages:
                role_tag = "=== USER ===" if msg["role"] == "user" else "=== ASSISTANT ==="
                f.write(f"{role_tag}\n")
                f.write(f"{msg['content']}\n\n")

    def get_session_attrs(self, session_path: str) -> str:
        """读取会话的角色属性（游戏式优先 角色属性.txt）"""
        if self.is_game_session(session_path):
            game_attrs = self.get_game_attrs(session_path)
            if game_attrs:
                return game_attrs
        attrs_file = os.path.join(session_path, "character_attrs.txt")
        if os.path.exists(attrs_file):
            with open(attrs_file, 'r', encoding='utf-8') as f:
                return f.read()
        return self.initial_attrs

    def update_session_attrs(self, session_path: str, new_attrs: str):
        """更新会话的角色属性（游戏式：整写最新值；旧式：追加）"""
        if self.is_game_session(session_path):
            self.set_game_attrs(session_path, new_attrs)
            return

        attrs_file = os.path.join(session_path, "character_attrs.txt")
        os.makedirs(os.path.dirname(attrs_file), exist_ok=True)

        existing = self.get_session_attrs(session_path)
        if existing:
            combined = existing + "\n\n" + new_attrs
        else:
            combined = new_attrs

        with open(attrs_file, 'w', encoding='utf-8') as f:
            f.write(combined)

    def delete_session(self, session_path: str) -> bool:
        """删除会话"""
        try:
            if os.path.exists(session_path):
                shutil.rmtree(session_path)
                return True
        except Exception:
            pass
        return False


class CharacterManager:
    """角色管理器"""

    def __init__(self, charter_dir: str):
        self.charter_dir = charter_dir
        os.makedirs(charter_dir, exist_ok=True)

    def get_characters(self) -> List[Character]:
        """获取所有角色列表"""
        characters = []
        if not os.path.exists(self.charter_dir):
            return characters

        for name in os.listdir(self.charter_dir):
            char_path = os.path.join(self.charter_dir, name)
            if os.path.isdir(char_path):
                characters.append(Character(name, char_path))

        return characters

    def get_character(self, name: str) -> Optional[Character]:
        """根据名字获取角色"""
        char_path = os.path.join(self.charter_dir, name)
        if os.path.isdir(char_path):
            return Character(name, char_path)
        return None

    def create_character(
        self,
        name: str,
        initial_attrs: str = None,
        icon_path: str = None,
        template_path: str = None,
        player_template_path: str = None,
    ) -> Character:
        """创建新角色

        Args:
            name: 角色名字（也是文件夹名；= 角色基础模板文件名）
            initial_attrs: 旧版初始属性文本（兼容）
            icon_path: 图标文件路径（可选）
            template_path: 角色基础模板 txt（复制为 角色基础模板.txt）
            player_template_path: 玩家模板 txt（复制为 玩家模板.txt）
        """
        char_folder = os.path.join(self.charter_dir, name)
        os.makedirs(char_folder, exist_ok=True)

        # 复制角色基础模板 / 玩家模板
        if template_path and os.path.exists(template_path):
            shutil.copy2(template_path, os.path.join(char_folder, "角色基础模板.txt"))
        if player_template_path and os.path.exists(player_template_path):
            shutil.copy2(player_template_path, os.path.join(char_folder, "玩家模板.txt"))

        # 保存初始属性（旧版兼容字段：无模板时必需）
        attrs_file = os.path.join(char_folder, "initial_attrs.txt")
        if initial_attrs is not None or not os.path.exists(attrs_file):
            with open(attrs_file, 'w', encoding='utf-8') as f:
                f.write(initial_attrs or "")

        # 复制图标
        if icon_path and os.path.exists(icon_path):
            dest_icon = os.path.join(char_folder, "icon.png")
            shutil.copy2(icon_path, dest_icon)

        # 创建会话文件夹
        sessions_dir = os.path.join(char_folder, "sessions")
        os.makedirs(sessions_dir, exist_ok=True)

        return Character(name, char_folder)

    def update_character(
        self,
        name: str,
        initial_attrs: str = None,
        icon_path: str = None,
        template_path: str = None,
        player_template_path: str = None,
    ) -> bool:
        """更新角色信息"""
        char = self.get_character(name)
        if not char:
            return False

        if template_path and os.path.exists(template_path):
            shutil.copy2(template_path, char.template_file)
            # 同步旧版 initial_attrs（保持一致）
            with open(char.initial_attrs_file, 'w', encoding='utf-8') as f:
                f.write(char.get_template())

        if player_template_path and os.path.exists(player_template_path):
            shutil.copy2(player_template_path, char.player_template_file)

        if initial_attrs is not None:
            with open(char.initial_attrs_file, 'w', encoding='utf-8') as f:
                f.write(initial_attrs)

        if icon_path and os.path.exists(icon_path):
            shutil.copy2(icon_path, char.icon_file)

        return True

    def delete_character(self, name: str) -> bool:
        """删除角色"""
        char_path = os.path.join(self.charter_dir, name)
        try:
            if os.path.exists(char_path):
                shutil.rmtree(char_path)
                return True
        except Exception:
            pass
        return False

    def character_exists(self, name: str) -> bool:
        """检查角色是否存在"""
        char_path = os.path.join(self.charter_dir, name)
        return os.path.isdir(char_path)


_character_manager = None


def get_character_manager(charter_dir: str = None) -> CharacterManager:
    """获取全局角色管理器"""
    global _character_manager
    if _character_manager is None or (charter_dir and _character_manager.charter_dir != charter_dir):
        _character_manager = CharacterManager(charter_dir)
    return _character_manager
