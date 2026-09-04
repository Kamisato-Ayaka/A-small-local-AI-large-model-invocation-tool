"""
AI 助手面板 - 右侧聊天面板
"""
import os
import re
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QComboBox, QSpinBox, QCheckBox,
    QFileDialog, QMenu, QMessageBox
)
from PyQt5.QtCore import Qt as _Qt_Core_Const, Qt, QThread, pyqtSignal, QObject, QTimer
from PyQt5 import QtCore, QtGui
import time
from PyQt5.QtGui import QFont, QTextCursor, QColor, QTextCharFormat, QFontMetrics


def fix_mojibake(text: str) -> str:
    """自动检测并修复乱码（UTF-8 文本被错误解码的情况）

    常见乱码类型：
    - UTF-8 字节被按 Latin-1/ISO-8859-1 解码：ä½ å¥½ -> 你好
    - UTF-8 字节被按 cp1252 解码
    """
    if not text:
        return text

    # 快速判断：如果已经有大量中文字符，说明不是乱码
    chinese_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if chinese_count > len(text) * 0.2:  # 超过 20% 是中文
        return text

    # 尝试修复方案：encode 回去再 decode
    # 常见的"原编码 -> 错误解码"组合
    fix_pairs = [
        # (错误显示的编码, 正确的原始编码)
        ("latin-1", "utf-8"),
        ("iso-8859-1", "utf-8"),
        ("cp1252", "utf-8"),
        ("latin-1", "gbk"),
        ("cp1252", "gbk"),
        ("gbk", "utf-8"),
        ("gb18030", "utf-8"),
    ]

    best_text = text
    best_score = _text_chinese_score(text)

    for from_enc, to_enc in fix_pairs:
        try:
            # 先用错误编码 encode 回字节，再用正确编码 decode
            raw = text.encode(from_enc)
            fixed = raw.decode(to_enc)
            score = _text_chinese_score(fixed)
            if score > best_score:
                best_score = score
                best_text = fixed
        except (UnicodeEncodeError, UnicodeDecodeError, LookupError):
            continue

    return best_text


def _text_chinese_score(text: str) -> float:
    """评估文本的"中文质量"分数（0-1），中文字符越多分数越高"""
    if not text:
        return 0.0
    # 中文字符
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    # 常见中文标点
    cn_punct = sum(1 for c in text if c in '，。！？、；：""''（）【】《》……—')
    # 乱码特征字符（扣分）
    bad_chars = sum(1 for c in text if c in 'Ã¤Ã¥Ã©Ã¨Ã¼Ã¶Ãâ')
    # 替换字符（严重扣分）
    replacement = sum(1 for c in text if c == '\ufffd')

    total = len(text)
    score = (chinese + cn_punct * 0.5) / total
    score -= bad_chars / total * 0.5
    score -= replacement / total * 2
    return max(0.0, score)


class StreamWorker(QObject):
    """流式输出工作线程"""
    chunk_received = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, llm_client, messages, action_type=None, code_data=None, max_tokens=4096):
        super().__init__()
        self.llm_client = llm_client
        self.messages = messages
        self.action_type = action_type
        self.code_data = code_data
        self.max_tokens = max_tokens
        self._running = True

    def run(self):
        try:
            if self.action_type and self.code_data:
                # 代码动作
                for chunk in self.llm_client.code_action_stream(
                    action=self.action_type,
                    code=self.code_data.get("code", ""),
                    filename=self.code_data.get("filename", ""),
                    description=self.code_data.get("description", ""),
                    error_message=self.code_data.get("error_message", ""),
                    goal=self.code_data.get("goal", ""),
                ):
                    if not self._running:
                        break
                    self.chunk_received.emit(chunk)
            else:
                # 普通聊天 / 角色扮演（游戏轮次输出很长：场景+心理+生理+30个选项，需要更大 max_tokens）
                for chunk in self.llm_client.chat_stream(
                    messages=self.messages,
                    temperature=0.7,
                    max_tokens=self.max_tokens,
                ):
                    if not self._running:
                        break
                    self.chunk_received.emit(chunk)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        self._running = False


class TTSSynthesizeWorker(QObject):
    """TTS 合成工作对象 — 同时支持 CosyVoice 和 GPT-SoVITS"""
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, text, voice="", speed=1.0, ref_path="", engine="cosyvoice", gs_params=None):
        super().__init__()
        self.text = text
        self.voice = voice
        self.speed = speed
        self.ref_path = ref_path
        self.engine = engine  # "cosyvoice" or "gpt_sovits"
        self.gs_params = gs_params or {}

    def run(self):
        try:
            if getattr(self, "_skip", False):
                return
            if self.engine == "gpt_sovits":
                from core.gpt_sovits_client import GptSovitsClient
                client = GptSovitsClient()
                # 不传 refer_wav_path/prompt_text — 让服务用启动时 -dr/-dt 设置的 default_refer
                # 每次合成都传参考参数会导致 zero-shot 重新克隆，长参考音频会把"海灯节..."学进去当固定前缀
                path = client.synthesize(
                    self.text,
                    text_language=self.gs_params.get("text_language", "zh"),
                    refer_wav_path="",
                    prompt_text="",
                    prompt_language=self.gs_params.get("refer_lang", "zh"),
                    top_k=self.gs_params.get("top_k", 5),
                    top_p=self.gs_params.get("top_p", 1.0),
                    temperature=self.gs_params.get("temperature", 1.0),
                    speed=self.speed,
                )
            else:
                from core.tts_client import TTSClient, clean_text_for_tts
                text = clean_text_for_tts(self.text)
                if not text:
                    self.failed.emit("没有可朗读的文本")
                    return
                path = TTSClient().synthesize(text, voice=self.voice, speed=self.speed,
                                              ref_path=self.ref_path)
            self.finished_ok.emit(path)
        except Exception as e:
            self.failed.emit(str(e))

# ---------- ChatML / 特殊 token 兜底清洗 ----------
# 与 llm_client 内部一致；这里再走一遍做 UI 层与入史层双保险，避免 llm_client 漏掉跨 chunk 极端情况
_RE_CHATML_TAGS = re.compile(r"<\|(?:begin_of_text|end_of_text|eot_id|start_header_id|end_header_id|im_end|im_start|reserved_\d+|python_tag|function_call[^\|]*?)\|>")
# 更泛：任何 <|...|>
_RE_ANY_PIPE = re.compile(r"<\|[^|]{1,120}\|>")






def _strip_half_open_tags_ui(text: str) -> str:
    r"""UI 显示层半开/残缺管道标签清洗。避免 \n 字符编码问题：使用 chr(10) / chr(13)。"""
    if not text:
        return text
    LF = chr(10); CR = chr(13)
    CN_PUNCT = ("\u3001\uff0c\u3002\uff01\uff1f\uff1a\uff1b\u201c\u201d\u2018\u2019"
                "\uff08\uff09\u3010\u3011\u300a\u300b\u2026\u2014")
    out = []
    i = 0; n = len(text)
    while i < n:
        ch = text[i]
        if ch == "<" and i + 1 < n and text[i + 1] == "|":
            j = i + 2
            closed = False; bad_stop = False
            while j < n and (j - i) <= 80:
                if text[j] == "|" and j + 1 < n and text[j + 1] == ">":
                    closed = True; break
                c = text[j]
                if c == LF or c == CR:
                    bad_stop = True; break
                cp = ord(c)
                if 0x4E00 <= cp <= 0x9FFF or c in CN_PUNCT:
                    bad_stop = True; break
                j += 1
            if closed:
                i = j + 2; continue
            if bad_stop or (j - i) > 80:
                i = j; continue
            i = n; continue
        if ch == "|" and i + 1 < n and text[i + 1] == ">":
            i += 2; continue
        if ch == "<" and i + 1 < n and text[i + 1] in (LF, CR):
            i += 1; continue
        if ch == "|" and i + 1 < n and text[i + 1] in (LF, CR):
            i += 1; continue
        out.append(ch)
        i += 1
    result = "".join(out)
    result = re.sub(r"<\|[A-Za-z0-9_ \-]{0,40}$", "", result)
    result = re.sub(r"^[ \t]*\|>[ \t]*", "", result)
    return result


def _strip_chatml_ui(text: str) -> str:
    """UI 显示层：完整标签 -> 半开残缺，最后收尾。"""
    if not text:
        return text
    t = _RE_CHATML_TAGS.sub("", text)
    t = _RE_ANY_PIPE.sub("", t)
    t = _strip_half_open_tags_ui(t)
    return t

def _sanitize_for_history(text: str):
    """入史层深度清洗：剥离思考块 → 截断幻觉续写（下一轮标记）→ 剥离特殊 token。
    思考内容（<think>/<think_cont>）绝不能进入 history，否则会污染下一轮上下文。
    Returns (清洗后的文本, 是否触发过截断)
    """
    try:
        from core.llm_client import sanitize_history_text
        return sanitize_history_text(text)
    except Exception:
        # 兜底实现（与 llm_client 内部一致）
        if not text:
            return text, False
        text = re.sub(r"<think(?:ing|_cont)?>[\s\S]*?</think(?:ing|_cont)?>", "", text, flags=re.I)
        text = re.sub(r"<think(?:ing|_cont)?>[\s\S]*\Z", "", text, flags=re.I)
        best_pos = None
        for m in (
            "<|im_start|>user",
            "<|im_start|>assistant",
            "<|start_header_id|>user<|end_header_id|>",
            "<|start_header_id|>assistant<|end_header_id|>",
        ):
            pos = text.find(m)
            if pos != -1 and (best_pos is None or pos < best_pos):
                best_pos = pos
        cut = best_pos is not None
        if cut:
            text = text[:best_pos]
        return _strip_chatml_ui(text), cut

class ChatMessage(QFrame):
    """单条聊天消息（支持思考过程折叠）+ 自动根据宽度计算多行气泡高度"""

    def __init__(self, role: str, content: str = "", icon_path: str = "", parent=None):
        super().__init__(parent)
        self.role = role
        self.icon_path = icon_path
        self._action_buttons = []
        self._thinking_active = False
        self._thinking_start_time = None
        self._thinking_timer = None
        self._last_width_for_layout = -1  # 记录上次算高度用的宽度，避免重复计算
        self._init_ui(content)

    def _init_ui(self, content):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # 头像
        self.avatar = QLabel()
        self.avatar.setFixedSize(28, 28)
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setStyleSheet("""
            QLabel {
                background: #2d2d30;
                border-radius: 14px;
                font-size: 16px;
            }
        """)
        self._set_avatar()

        # 右侧内容容器
        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        # 思考状态（AI 消息才有，只显示"思考中..."，不展示具体内容）
        self.thinking_label = QLabel("⏳ 思考中...")
        self.thinking_label.setVisible(False)
        self.thinking_label.setStyleSheet("""
            QLabel {
                color: #6ba3d6;
                background: rgba(107, 163, 214, 0.08);
                padding: 4px 10px;
                font-size: 12px;
                font-family: "Microsoft YaHei";
                border-radius: 8px;
                border: 1px solid rgba(107, 163, 214, 0.2);
            }
        """)
        content_layout.addWidget(self.thinking_label)

        # 消息内容
        self.content_edit = QTextEdit()
        self.content_edit.setReadOnly(True)
        self.content_edit.setFrameShape(QFrame.NoFrame)
        from core.config import get_config_manager
        _text_color = get_config_manager().get("theme.chat_text_color", "#cccccc")
        self.content_edit.setStyleSheet(f"""
            QTextEdit {{
                background: #252530;
                color: {_text_color};
                border-radius: 12px;
                padding: 10px 12px;
                font-size: 13px;
                border: 1px solid rgba(255, 255, 255, 0.06);
            }}
        """)
        self.content_edit.setFont(QFont("Microsoft YaHei", 10))
        self.content_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content_layout.addWidget(self.content_edit)

        # 按钮区域（默认隐藏）
        self.button_row = QHBoxLayout()
        self.button_row.setSpacing(6)
        self.button_row.addStretch()
        self.button_widget = QWidget()
        self.button_widget.setLayout(self.button_row)
        self.button_widget.setVisible(False)
        content_layout.addWidget(self.button_widget)

        # Token 用量标签（角色扮演模式显示，默认隐藏）
        self._token_label = None

        if self.role == "user":
            layout.addStretch()
            layout.addWidget(content_container, 1)
            layout.addWidget(self.avatar)
            self.content_edit.setStyleSheet("""
                QTextEdit {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0d47a1, stop:1 #0a3575);
                    color: #ffffff;
                    border-radius: 12px;
                    padding: 10px 12px;
                    font-size: 13px;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                }
            """)
        else:
            layout.addWidget(self.avatar)
            layout.addWidget(content_container, 1)

        if content:
            self.set_content(content)

        self._adjust_height()

    def _set_avatar(self):
        """设置头像（支持自定义图标）"""
        import os
        from PyQt5.QtGui import QPixmap

        if self.icon_path and os.path.exists(self.icon_path):
            pixmap = QPixmap(self.icon_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.avatar.setPixmap(scaled)
                self.avatar.setStyleSheet("""
                    QLabel {
                        background: #2d2d30;
                        border-radius: 14px;
                    }
                """)
                return

        # 默认 emoji 头像
        self.avatar.setPixmap(QPixmap())
        self.avatar.setText("🤖" if self.role == "ai" else "👤")
        self.avatar.setStyleSheet("""
            QLabel {
                background: #2d2d30;
                border-radius: 14px;
                font-size: 16px;
            }
        """)

    def set_text_color(self, color: str):
        """更新消息文字颜色（仅 AI 消息；用户消息保持白字蓝底）"""
        if self.role != "ai":
            return
        self.content_edit.setStyleSheet(f"""
            QTextEdit {{
                background: #252530;
                color: {color};
                border-radius: 12px;
                padding: 10px 12px;
                font-size: 13px;
                border: 1px solid rgba(255, 255, 255, 0.06);
            }}
        """)

    def set_token_usage(self, input_tokens: int, output_tokens: int):
        """角色扮演模式：显示本轮 输入/输出 Token 统计
        输入 = 发给 AI 的全部信息（角色设定+属性+历史+玩家输入），输出 = AI 回复
        """
        if self._token_label is None:
            self._token_label = QLabel()
            self._token_label.setVisible(False)
            self._token_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._token_label.setStyleSheet("""
                QLabel {
                    color: #8a8a8a;
                    font-size: 11px;
                    padding: 1px 4px;
                    font-family: Consolas, "Microsoft YaHei";
                }
            """)
            lay = self.content_edit.parentWidget().layout()
            idx = lay.indexOf(self.content_edit)
            lay.insertWidget(idx + 1, self._token_label)
        self._token_label.setText(f"⇅ 输入 {input_tokens} tokens · 输出 {output_tokens} tokens")
        self._token_label.setVisible(True)
        self._adjust_height()

    def start_thinking(self):
        """开始显示思考中状态（带计时器）"""
        self._thinking_active = True
        self._thinking_start_time = time.time()
        self.thinking_label.setVisible(True)
        self._update_thinking_time()

        # 启动计时器，每秒更新一次
        if self._thinking_timer is None:
            self._thinking_timer = QTimer(self)
            self._thinking_timer.timeout.connect(self._update_thinking_time)
        self._thinking_timer.start(1000)

        self._adjust_height()

    def _update_thinking_time(self):
        """更新思考计时显示"""
        if not self._thinking_active or self._thinking_start_time is None:
            return
        elapsed = int(time.time() - self._thinking_start_time)
        mins = elapsed // 60
        secs = elapsed % 60
        time_str = f"{mins:02d}:{secs:02d}"
        self.thinking_label.setText(f"⏳ 思考中... {time_str}")

    def append_thinking(self, text: str):
        """追加思考内容（只显示计时，不显示内容）"""
        if not self._thinking_active:
            self.start_thinking()

    def finish_thinking(self):
        """思考完成，隐藏思考状态"""
        self._thinking_active = False
        if self._thinking_timer:
            self._thinking_timer.stop()
        # 记录总思考时间
        total_str = ""
        if self._thinking_start_time:
            elapsed = int(time.time() - self._thinking_start_time)
            mins = elapsed // 60
            secs = elapsed % 60
            total_str = f"{mins:02d}:{secs:02d}"
        self.thinking_label.setVisible(False)
        self._thinking_start_time = None
        self._adjust_height()

    def set_content(self, text):
        # 防御：None 或 非字符串 不要让 setHtml 挂掉
        if text is None:
            text = ""
        if not isinstance(text, str):
            try:
                text = str(text)
            except Exception:
                text = ""

        # 自动修复乱码
        text = fix_mojibake(text)

        # 如果没有 HTML 特殊标记（换行/代码块/加粗/行内代码），优化：直接用 PlainText
        #  （防止 setHtml 在短内容时 Qt 渲染 bug 导致首帧空白/行高三异常）
        need_html = (
            ("\n" in text) or
            ("```" in text) or
            ("**" in text) or
            ("`" in text) or
            ("<br" in text.lower()) or
            ("<think" in text.lower())
        )

        ce = self.content_edit

        # 先清掉旧内容（避免旧 HTML 残留影响尺寸计算）
        ce.clear()

        if need_html:
            html = self._markdown_to_html(text)
            ce.setHtml(html)
        else:
            ce.setPlainText(text)

        # 强制刷新 documentLayout 与 viewport
        doc = ce.document()
        try:
            doc.documentLayout().documentChanged(0, 0, max(1, doc.characterCount()))
        except Exception:
            pass
        ce.updateGeometry()
        ce.update()
        if ce.viewport():
            ce.viewport().update()

        self._adjust_height()

    def append_content(self, text):
        if text is None or text == "":
            return
        if not isinstance(text, str):
            try:
                text = str(text)
            except Exception:
                return
        # 自动修复乱码
        text = fix_mojibake(text)
        # 直接追加，不重新 setContent：避免每次都重跑 markdown_to_html + setHtml
        #  —— 直接用 QTextCursor 在末尾插入，速度更快也不会触发 Qt 偶尔的「首帧空白」bug
        ce = self.content_edit
        cursor = ce.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        # 没有特殊字符就插 plainText；否则按 chunk 粗略处理：纯文本插入，换行转回车
        plain = text
        # 把一些已经被 HTML 转义/占位的 think_cont/<think> 标签等都按文本显示 ——
        #  但上层 _process_chunk 不会真的把这些标签送入 append_content，所以这里不需要特殊处理。
        cursor.insertText(plain)
        ce.setTextCursor(cursor)
        ce.ensureCursorVisible()
        ce.update()
        if ce.viewport():
            ce.viewport().update()
        self._adjust_height()

    def append_action_button(self, label: str, callback):
        """添加动作按钮"""
        btn = QPushButton(label)
        btn.setStyleSheet("""
            QPushButton {
                background: #007acc;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 12px;
                font-family: "Microsoft YaHei";
            }
            QPushButton:hover { background: #1177bb; }
            QPushButton:pressed { background: #005a9e; }
        """)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(callback)
        # 插入到 addStretch 之前
        self.button_row.insertWidget(self.button_row.count() - 1, btn)
        self._action_buttons.append(btn)
        self.button_widget.setVisible(True)

    def _markdown_to_html(self, text):
        # 转义 HTML
        text = (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))

        # 代码块
        text = re.sub(
            r"```([\s\S]*?)```",
            r'<pre style="background:#1e1e1e;padding:8px;border-radius:4px;overflow-x:auto;font-family:Consolas,monospace;font-size:12px;color:#d4d4d4;">\1</pre>',
            text
        )

        # 行内代码
        text = re.sub(
            r"`([^`]+)`",
            r'<code style="background:rgba(255,255,255,0.1);padding:1px 4px;border-radius:3px;font-family:Consolas,monospace;">\1</code>',
            text
        )

        # 加粗
        text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)

        # 换行
        text = text.replace("\n", "<br>")

        text = _RE_ANY_PIPE.sub("", text)
        return text

    def _adjust_height(self):
        """
        根据内容自动调整气泡高度：
          - 先把文档的 textWidth 固定为「当前 viewport 真实宽度」，
            这样 document.size() 才会给出「按该宽度换行」后的真实高度。
          - 再加上 padding(20~24)、margin 和 minimum 60 / maximum 800 的限制。
          - 如果还拿不到宽度（构造阶段），就推迟到下一次 showEvent。
        """
        from PyQt5.QtCore import QSize

        ce = self.content_edit
        doc = ce.document()
        doc_layout = doc.documentLayout()

        # 真实可用宽度：优先取 content_edit 已经布局后的宽度
        viewport_w = ce.viewport().width() if ce.viewport() else 0
        frame_w = ce.width() - viewport_w  # 边框等开销

        # 如果当前还不可见/无宽度，尝试用父容器 content_container 的宽度估算
        if viewport_w <= 10:
            parent_w = ce.parent().width() if ce.parent() else 0
            if parent_w > frame_w:
                viewport_w = parent_w - frame_w

        # 如果还太小（首次构造时），走估算：取窗口的 60% 做兜底，避免第一帧只有一行
        if viewport_w <= 10:
            window = self.window()
            screen_w = window.width() if window and window.width() > 100 else 800
            # 聊天气泡大概占可用宽度的 70%，扣除两侧 padding 和 avatar
            viewport_w = int(max(320, screen_w * 0.70 - 24 - 24 - 40))

        # 设定文档宽度，强制重排版
        doc.setTextWidth(viewport_w)

        # 触发整页 layout：把 documentLayout 当作抽象类。PyQt5 没有 requestUpdate，
        # 直接 document().size() 会触发内部 layout；这里做一次手动的 block 高度累计
        # 再和 doc.size() 比较，保证高度正确。
        h_a = doc.size().height()

        # 兜底：逐 block 累加布局高度（应对 QTextDocument.size() 偶尔未刷新的情况）
        h_b = 0.0
        try:
            blk = doc.begin()
            while blk.isValid():
                layout = blk.layout()
                if layout is not None:
                    h_b += layout.boundingRect().height()
                else:
                    # 没 layout 的 block 按一行估算
                    fm = QtGui.QFontMetrics(doc.defaultFont())
                    h_b += fm.lineSpacing()
                blk = blk.next()
        except Exception:
            pass

        # 取两者较大值；再乘 1.02 留点余量，避免刚好挤到一行被裁
        doc_height = max(h_a, h_b, 1.0) * 1.02

        # 加上 padding 的上下（QSS padding: 10px 12px 对应 上下合计 20px）
        padding_v = 24
        # 再给 documentHeight 留 2px 安全边距，避免刚好挤到一行被裁
        raw_h = doc_height + padding_v
        height = int(raw_h + 2)

        min_h = 56
        max_h = 900
        if height < min_h:
            height = min_h
        if height > max_h:
            height = max_h
            ce.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        else:
            ce.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        ce.setFixedHeight(height)

    # ---- sizeHint / 宽度变化时重新触发高度计算 --------------------------------
    def showEvent(self, event):
        """首次显示时，真实宽度已知 → 立刻重新算高度"""
        super().showEvent(event)
        # 用单次 invokeMethod，让这一帧的 layout 先稳定
        QTimer.singleShot(0, self._adjust_height)

    def resizeEvent(self, event):
        """整个气泡 row 的宽度变了（例如窗口变宽）→ 重算换行和高度"""
        super().resizeEvent(event)
        new_w = event.size().width()
        # 宽度变化超过 10px 才触发，避免微调重复计算
        if self._last_width_for_layout == -1 or abs(new_w - self._last_width_for_layout) > 10:
            self._last_width_for_layout = new_w
            QTimer.singleShot(0, self._adjust_height)

    def sizeHint(self):
        """给 Qt 布局一个「基于当前文本计算得出的理想高度」，缓解首帧偏差"""
        hint = super().sizeHint()
        h = self.content_edit.height()
        margins = self.layout().contentsMargins() if self.layout() else None
        if margins:
            h += margins.top() + margins.bottom()
        if self.button_widget and self.button_widget.isVisible():
            h += self.button_widget.height() + 4
        return QtCore.QSize(max(hint.width(), 300), max(hint.height(), h, 80))


class AIPanel(QWidget):
    """AI 助手面板"""

    roleplay_requested = pyqtSignal()  # 普通对话面板：请求跳转到角色扮演选项卡新建角色
    gs_config_requested = pyqtSignal()

    def __init__(self, llm_client, workspace_path: str, server_manager=None, system_monitor=None,
                 charter_dir: str = None, parent=None, roleplay_mode: bool = False):
        super().__init__(parent)
        self.llm_client = llm_client
        self.workspace_path = workspace_path
        self.server_manager = server_manager
        self.system_monitor = system_monitor
        self.roleplay_mode = bool(roleplay_mode)  # 角色扮演专用面板：启用角色栏，禁用普通模式选项
        self.chat_history = []
        self.current_editor_code = ""
        self.current_filename = ""
        self.stream_thread = None
        self.stream_worker = None
        self.is_streaming = False
        self._pending_message = None  # 等待服务启动后发送的消息
        self._pending_user_text = None  # 本轮等待成对入史的用户消息
        self._in_thinking = False  # 是否在思考模式中
        self._think_buffer = ""  # 思考标签缓冲

        # 角色扮演相关
        self.charter_dir = charter_dir
        self.character_manager = None
        self.current_character = None  # 当前选中的角色
        self._tts_busy = False          # TTS 合成/播放进行中
        self._tts_thread = None
        self._tts_worker = None
        self._tts_cancelled = False
        self._tts_auto = False          # 开始AI语音输出开关：开启后每轮回复自动朗读
        self.current_session_path = None  # 当前会话路径
        self.current_character_icon = ""  # 当前角色图标路径

        from core.config import get_config_manager
        self.config = get_config_manager()

        # 初始化角色管理器（仅角色扮演专用面板启用角色栏；普通对话面板不创建）
        if self.charter_dir and self.roleplay_mode:
            from core.character_manager import get_character_manager
            self.character_manager = get_character_manager(self.charter_dir)

        self._init_ui()
        self._refresh_model_combo()
        self._refresh_character_combo()

        # 监听服务状态变化
        if self.server_manager:
            self.server_manager.status_changed.connect(self._on_server_status_changed)

        # 监听系统监控
        if self.system_monitor:
            self.system_monitor.stats_updated.connect(self._on_stats_updated)

        # 初始化状态显示
        self._update_start_button()

        # 订阅 CosyVoice 语音服务状态（单例管理器；对话框/其他面板启停也会同步刷新本按钮）
        try:
            from core.tts_server_manager import get_tts_server_manager
            _tts_mgr = get_tts_server_manager()
            _tts_mgr.status_changed.connect(self._on_tts_svc_status, Qt.UniqueConnection)
            self._on_tts_svc_status(_tts_mgr.status)
        except Exception:
            pass

    def _init_ui(self):
        from widgets.animated_bg import AnimatedBackground

        self.setObjectName("aiPanelRoot")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 背景层（放在最底层）
        self._bg_widget = AnimatedBackground(self)
        self._bg_widget.lower()

        # 主内容容器（透明背景）
        self._content_widget = QWidget(self)
        self._content_widget.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # 把主内容加到 layout
        layout.addWidget(self._content_widget)

        # 后续的 header 等都加到 content_layout
        # 聊天消息区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QWidget#scrollAreaWidgetContents { background: transparent; }
            QScrollBar:vertical {
                background: transparent; width: 6px; margin: 2px;
            }
            QScrollBar::handle:vertical {
                background: rgba(120,120,120,80); border-radius: 3px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(120,120,120,130);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0; background: none;
            }
        """)

        self.messages_container = QWidget()
        self.messages_container.setStyleSheet("background: transparent;")
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(0, 8, 0, 8)
        self.messages_layout.setSpacing(0)
        self.messages_layout.addStretch()

        self.scroll_area.setWidget(self.messages_container)
        content_layout.addWidget(self.scroll_area, 1)

        # 监听聊天区宽度变化 → 让每条消息重算换行高度
        self._chat_resize_debounce = QTimer(self)
        self._chat_resize_debounce.setSingleShot(True)
        self._chat_resize_debounce.setInterval(60)
        self._chat_resize_debounce.timeout.connect(self._relayout_all_bubbles)
        self.messages_container.installEventFilter(self)

        # 角色选择栏（如果启用了角色扮演）
        if self.character_manager:
            char_bar = QWidget()
            char_bar.setFixedHeight(44)
            char_bar.setStyleSheet("""
                QWidget {
                    background: rgba(37, 37, 38, 180);
                    border-bottom: 1px solid rgba(30, 30, 30, 200);
                    border-top: 1px solid rgba(30, 30, 30, 200);
                }
            """)
            char_layout = QHBoxLayout(char_bar)
            char_layout.setContentsMargins(10, 6, 10, 6)
            char_layout.setSpacing(6)

            char_label = QLabel("🎭 角色:")
            char_label.setStyleSheet("color: #888; font-size: 12px;")
            char_layout.addWidget(char_label)

            self.character_combo = QComboBox()
            self.character_combo.setMinimumWidth(150)
            self.character_combo.setStyleSheet("""
                QComboBox {
                    background: #2d2d30;
                    color: #cccccc;
                    border: 1px solid #3c3c3c;
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 12px;
                }
                QComboBox:hover { border-color: #007acc; }
                QComboBox QAbstractItemView {
                    background: #252526;
                    color: #cccccc;
                    border: 1px solid #3c3c3c;
                    selection-background-color: #094771;
                }
            """)
            self.character_combo.currentIndexChanged.connect(self._on_character_changed)
            char_layout.addWidget(self.character_combo)

            self.new_session_btn = QPushButton("🔄 新会话")
            self.new_session_btn.setFixedSize(72, 26)
            self.new_session_btn.setCursor(Qt.PointingHandCursor)
            self.new_session_btn.setStyleSheet("""
                QPushButton {
                    background: #3c3c3c;
                    color: #cccccc;
                    border: none;
                    border-radius: 4px;
                    font-size: 11px;
                }
                QPushButton:hover { background: #4a4a4a; }
                QPushButton:disabled { background: #2d2d30; color: #666; }
            """)
            self.new_session_btn.clicked.connect(self._new_character_session)
            self.new_session_btn.setEnabled(False)
            char_layout.addWidget(self.new_session_btn)

            self.add_char_btn = QPushButton("➕ 新建角色")
            self.add_char_btn.setFixedSize(78, 26)
            self.add_char_btn.setCursor(Qt.PointingHandCursor)
            self.add_char_btn.setStyleSheet("""
                QPushButton {
                    background: #007acc;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-size: 11px;
                }
                QPushButton:hover { background: #1177bb; }
            """)
            self.add_char_btn.clicked.connect(self._add_character)
            char_layout.addWidget(self.add_char_btn)

            self.manage_char_btn = QPushButton("⚙️")
            self.manage_char_btn.setFixedSize(26, 26)
            self.manage_char_btn.setCursor(Qt.PointingHandCursor)
            self.manage_char_btn.setToolTip("管理角色")
            self.manage_char_btn.setStyleSheet("""
                QPushButton {
                    background: #3c3c3c;
                    color: #cccccc;
                    border: none;
                    border-radius: 4px;
                    font-size: 12px;
                }
                QPushButton:hover { background: #4a4a4a; }
            """)
            self.manage_char_btn.clicked.connect(self._manage_characters)
            char_layout.addWidget(self.manage_char_btn)

            # 角色配音开关：角色扮演模式下 AI 回复完自动用 CosyVoice 朗读
            self.auto_tts_check = QCheckBox("🔊配音")
            self.auto_tts_check.setToolTip("角色扮演模式下，AI 回复完成后自动语音朗读")
            self.auto_tts_check.setStyleSheet("color: #888; font-size: 11px;")
            self.auto_tts_check.setChecked(bool(self.config.get("roleplay.auto_tts", False)))
            self.auto_tts_check.toggled.connect(self._on_auto_tts_toggled)
            char_layout.addWidget(self.auto_tts_check)

            char_layout.addStretch()

            # 历史轮数（游戏式角色扮演：发给 AI 的『前面第N次对话』轮数，由玩家指定）
            self.rounds_label = QLabel("历史轮数:")
            self.rounds_label.setStyleSheet("color: #888; font-size: 11px;")
            char_layout.addWidget(self.rounds_label)

            self.rounds_spin = QSpinBox()
            self.rounds_spin.setRange(0, 50)
            self.rounds_spin.setValue(1)
            self.rounds_spin.setFixedWidth(52)
            self.rounds_spin.setToolTip("每轮发给 AI 的『前面第N次对话』数量（角色扮演模式）。设为 0 表示不发送历史（仅角色定义+玩家输入）")
            self.rounds_spin.setStyleSheet("""
                QSpinBox {
                    background: #2d2d30; color: #cccccc; border: 1px solid #3c3c3c;
                    border-radius: 4px; padding: 2px 6px; font-size: 11px;
                }
            """)
            try:
                # 优先读取设置对话框里的"对话记忆轮数"（玩家统一配置），回退旧的 roleplay 专用配置，最后默认 1
                _cfg_rounds = int(self.config.get("chat.memory_rounds", 1))
                if not _cfg_rounds:
                    _cfg_rounds = int(self.config.get("roleplay.memory_rounds", 1))
                self.rounds_spin.setValue(max(0, min(50, _cfg_rounds)))
            except Exception:
                pass
            self.rounds_spin.valueChanged.connect(self._on_rounds_changed)
            char_layout.addWidget(self.rounds_spin)
            self.rounds_label.setVisible(False)
            self.rounds_spin.setVisible(False)

            # 当前角色状态显示
            self.char_status_label = QLabel("")
            self.char_status_label.setStyleSheet("color: #888; font-size: 11px;")
            char_layout.addWidget(self.char_status_label)

            content_layout.insertWidget(0, char_bar)

        # 输入区域
        input_area = QWidget()
        input_area.setStyleSheet("background: rgba(37, 37, 38, 200); border-top: 1px solid #1e1e1e;")
        input_layout = QVBoxLayout(input_area)
        input_layout.setContentsMargins(10, 8, 10, 8)
        input_layout.setSpacing(6)

        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText("输入你的问题... (Enter 发送，Shift+Enter 换行)")
        self.input_edit.setFixedHeight(110)
        self.input_edit.setStyleSheet("""
            QTextEdit {
                background: #2d2d30;
                color: #cccccc;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
            }
            QTextEdit:focus { border-color: #007acc; }
            QTextEdit[placeholderText] { color: #5a5a5a; }
        """)
        self.input_edit.installEventFilter(self)
        input_layout.addWidget(self.input_edit)

        # 底部行1：模型选择 + 启动 + 共享AI + 快捷键提示
        model_row = QHBoxLayout()
        model_row.setSpacing(6)

        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(180)
        self.model_combo.setStyleSheet("""
            QComboBox {
                background: #2d2d30;
                color: #cccccc;
                border: 1px solid #3c3c3c;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 12px;
                min-height: 22px;
            }
            QComboBox:hover { border-color: #007acc; }
            QComboBox QAbstractItemView {
                background: #252526;
                color: #cccccc;
                border: 1px solid #3c3c3c;
                selection-background-color: #094771;
                selection-color: #ffffff;
                outline: none;
            }
        """)
        self.model_combo.currentIndexChanged.connect(self._on_model_combo_changed)
        model_row.addWidget(self.model_combo)

        self.start_btn = QPushButton("🚀 启动")
        self.start_btn.setFixedSize(78, 28)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background: #007acc;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover { background: #1177bb; }
            QPushButton:disabled { background: #3c3c3c; color: #808080; }
        """)
        self.start_btn.clicked.connect(self._toggle_server)
        model_row.addWidget(self.start_btn)

        # 对外共享 AI：把本程序的模型以 OpenAI Chat Completions 格式提供给外部程序接入
        self.share_btn = QPushButton("🔗 共享AI")
        self.share_btn.setFixedSize(86, 28)
        self.share_btn.setToolTip("把本程序的 AI 以 OpenAI Chat Completions 格式提供给外部程序接入使用")
        self.share_btn.setStyleSheet("""
            QPushButton {
                background: #2d2d30;
                color: #cccccc;
                border: 1px solid #3c3c3c;
                border-radius: 8px;
                font-size: 12px;
            }
            QPushButton:hover { border-color: #007acc; color: #ffffff; }
        """)
        self.share_btn.clicked.connect(self._open_share_ai_dialog)
        model_row.addWidget(self.share_btn)

        hint = QLabel("Enter 发送 · Shift+Enter 换行")
        hint.setStyleSheet("color: #5a5a5a; font-size: 11px;")
        model_row.addWidget(hint)
        model_row.addStretch()

        # 底部行2：语音服务 + 朗读 + 声音 + 新建角色 + 发送
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(6)

        # 共享样式
        _svc_style = (
            "QPushButton {background:#2d2d30;color:#cccccc;border:1px solid #3c3c3c;"
            "border-radius:8px;font-size:12px;}"
            "QPushButton:hover {border-color:#007acc;color:#ffffff;}"
            "QPushButton:disabled {background:#2d2d30;color:#808080;}"
        )
        _tts_style = (
            "QPushButton {background:#2d2d30;color:#cccccc;border:1px solid #3c3c3c;"
            "border-radius:8px;font-size:12px;}"
            "QPushButton:hover {border-color:#007acc;color:#ffffff;}"
        )

        # 配置 GPT-SoVITS — 只有 GS 模式才显示，点击跳转到语音系统页面
        self.gs_config_btn = QPushButton("⚙️ 配置 GPT-SoVITS")
        self.gs_config_btn.setFixedSize(136, 28)
        self.gs_config_btn.setCursor(Qt.PointingHandCursor)
        self.gs_config_btn.setToolTip("跳转到语音系统页面配置 GPT-SoVITS-v2pro")
        self.gs_config_btn.setStyleSheet(_tts_style)
        self.gs_config_btn.clicked.connect(self._on_gs_config_btn)
        bottom_row.addWidget(self.gs_config_btn)

        # 语音服务启停 — 对应当前引擎
        self.tts_svc_btn = QPushButton("🎤 启动语音服务")
        self.tts_svc_btn.setFixedSize(112, 28)
        self.tts_svc_btn.setToolTip("启动语音服务；运行中点击停止服务")
        self.tts_svc_btn.setStyleSheet(_svc_style)
        self.tts_svc_btn.clicked.connect(self._on_tts_svc_btn_clicked)
        bottom_row.addWidget(self.tts_svc_btn)

        # 开始AI语音输出
        self.tts_btn = QPushButton("🔊 开始AI语音输出")
        self.tts_btn.setFixedSize(136, 28)
        self.tts_btn.setToolTip("开启后保持：每有一轮新对话自动朗读 AI 回复；再点一次停止")
        self.tts_btn.setStyleSheet(_tts_style)
        self.tts_btn.clicked.connect(self._on_tts_btn_clicked)
        bottom_row.addWidget(self.tts_btn)

        # 声音文件 — 只有 CosyVoice 模式才显示
        self.voice_clone_btn = QPushButton("🎙 声音")
        self.voice_clone_btn.setFixedSize(72, 28)
        self.voice_clone_btn.setToolTip("指定克隆声音文件（只应用于当前对话）")
        self.voice_clone_btn.setStyleSheet(_tts_style)
        self.voice_clone_btn.clicked.connect(self._on_voice_clone_btn_clicked)
        bottom_row.addWidget(self.voice_clone_btn)

        # 新建角色
        self.new_char_btn = QPushButton("➕ 新建角色")
        self.new_char_btn.setFixedSize(92, 28)
        self.new_char_btn.setCursor(Qt.PointingHandCursor)
        self.new_char_btn.setToolTip("创建新角色（角色模板 → 玩家模板 → 生成对话世界）")
        self.new_char_btn.setStyleSheet(_tts_style)
        if getattr(self, "roleplay_mode", False):
            self.new_char_btn.clicked.connect(self._add_character)
        else:
            self.new_char_btn.clicked.connect(self.roleplay_requested.emit)
        bottom_row.addWidget(self.new_char_btn)

        bottom_row.addStretch()
        # — 初始按引擎模式刷新按钮可见性（GS 模式：显示配置按钮、隐藏声音按钮；CV 模式：隐藏配置按钮、显示声音按钮）
        self._refresh_tts_btn_row()

        self.send_btn = QPushButton("发送")
        self.send_btn.setFixedSize(72, 28)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background: #007acc;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover { background: #1177bb; }
            QPushButton:disabled { background: #3c3c3c; color: #808080; }
        """)
        self.send_btn.clicked.connect(self.send_message)
        bottom_row.addWidget(self.send_btn)

        input_layout.addLayout(model_row)
        input_layout.addLayout(bottom_row)
        content_layout.addWidget(input_area)

        # 添加欢迎消息（不入 history：避免未配对的 assistant 破坏 user/assistant 严格交替）
        if getattr(self, "roleplay_mode", False):
            self._add_ai_message(
                "🎭 欢迎来到角色扮演对话模式\n\n"
                "• 上方下拉框选择角色，或点「➕ 新建角色」创建新角色\n"
                "• 每个角色拥有独立的会话记录、角色属性与克隆音色\n"
                "• 勾选「🔊配音」可让 AI 回复自动语音朗读\n"
                "• 「历史轮数」控制每轮携带给 AI 的前文轮数\n\n"
                "选择或创建一个角色，开始你的故事吧！",
                add_to_history=False
            )
        else:
            self._add_ai_message(
                "你好！我是本地 AI 助手 🤖\n\n"
                "我可以帮你：\n"
                "• 生成代码 — 描述需求即可\n"
                "• 解释代码 — 打开文件后点\"解释\"\n"
                "• 审查代码 — 检查质量和问题\n"
                "• 重构优化 — 提升代码质量\n"
                "• 修复 Bug — 定位和修复问题\n"
                "• 生成测试 — 编写单元测试\n\n"
                "有什么我可以帮你的吗？",
                add_to_history=False
            )

    def eventFilter(self, obj, event):
        # 注意：本类只允许有一个 eventFilter（之前两个同名定义相互覆盖导致 Enter 发送失效）
        if obj == self.input_edit and event.type() == event.KeyPress:
            if event.key() == Qt.Key_Return and not (event.modifiers() & Qt.ShiftModifier):
                self.send_message()
                return True
        if obj is self.messages_container and event.type() == QtCore.QEvent.Resize:
            self._chat_resize_debounce.start()
        return super().eventFilter(obj, event)

    def set_current_editor(self, code: str, filename: str):
        """设置当前编辑器的代码（保留接口，当前普通对话不注入提示词）"""
        self.current_editor_code = code
        self.current_filename = filename

    def _add_user_message(self, text: str, add_to_history: bool = True):
        msg = ChatMessage("user", text)
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, msg)
        if add_to_history:
            self.chat_history.append({"role": "user", "content": text})
        self._scroll_to_bottom()

    def _add_ai_message(self, text: str = "", add_to_history: bool = True) -> ChatMessage:
        # 使用角色图标（如果有）
        icon = self.current_character_icon if self.current_character_icon else ""
        msg = ChatMessage("ai", text, icon_path=icon)
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, msg)
        if add_to_history and text:
            self.chat_history.append({"role": "assistant", "content": text})
        self._scroll_to_bottom()
        return msg

    def _add_action_buttons_to_last(self, *buttons):
        """向最后一条 AI 消息气泡添加动作按钮；buttons 为 (label, callback) 元组"""
        if self.messages_layout.count() <= 1:
            return
        item = self.messages_layout.itemAt(self.messages_layout.count() - 2)
        w = item.widget() if item else None
        if isinstance(w, ChatMessage):
            for label, cb in buttons:
                w.append_action_button(label, cb)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        )

    def _relayout_all_bubbles(self):
        """遍历聊天区里所有 ChatMessage，强制重新计算高度（用于宽度变化后）"""
        for i in range(self.messages_layout.count() - 1):  # 末尾是 stretch
            item = self.messages_layout.itemAt(i)
            if not item:
                continue
            w = item.widget()
            if isinstance(w, ChatMessage):
                try:
                    w._adjust_height()
                except Exception:
                    pass
        self._scroll_to_bottom()

    def new_chat(self):
        self.chat_history = []
        self._pending_user_text = None
        # 清空消息
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._add_ai_message(
            "新对话已开始！有什么我可以帮你的吗？",
            add_to_history=False
        )

    # ========== 模型服务控制 ==========

    def _start_server_from_panel(self):
        """从 AI 面板启动模型服务"""
        if self.server_manager:
            # 检查是否已设置模型
            from core.config import get_config_manager
            cfg = get_config_manager()
            model_path = cfg.get("llm.model_path", "")

            if not model_path:
                # 没设置模型，让用户先选
                self._add_ai_message(
                    "⚠️ 请先选择模型文件\n\n"
                    "点击下方按钮打开设置，选择你的 .gguf 模型文件："
                )
                self._add_action_buttons_to_last(
                    ("⚙️ 模型设置", self._open_settings_from_panel),
                )
                return

            self._add_ai_message("⏳ 正在启动模型服务，请稍候...")
            self._pending_message = None  # 清除等待的消息
            self.server_manager.start_server()

    def _open_settings_from_panel(self):
        """从 AI 面板打开设置"""
        # 通过父窗口打开设置
        parent = self.parent()
        while parent:
            if hasattr(parent, 'open_settings'):
                parent.open_settings()
                return
            parent = parent.parent()
        # 兜底：直接创建设置对话框
        from widgets.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self.window())
        if dialog.exec_():
            self._refresh_model_combo()
            self._update_start_button()

    def set_workspace_path(self, path: str):
        """设置项目文件夹路径"""
        import os
        self.workspace_path = os.path.abspath(path)

    def apply_theme(self):
        """主题：壁纸由主窗口的窗口级背景层统一渲染（铺满全窗），
        有壁纸时本面板透明让壁纸透出；无壁纸时回退纯色底。"""
        import os
        from core.config import get_config_manager
        theme = get_config_manager().get("theme", {})
        bg_image = theme.get("chat_bg_image", "")
        self.setStyleSheet("#aiPanelRoot { background: transparent; }")
        if hasattr(self, '_bg_widget') and self._bg_widget:
            if bg_image and os.path.exists(bg_image):
                self._bg_widget.clear_to_transparent()
            else:
                self._bg_widget.set_background(
                    "", theme.get("chat_bg_color", "#252526"),
                    1.0)  # 壁纸/底色始终不透明
        self.apply_text_colors()

    def set_ui_opacity(self, opacity: float):
        """界面要素透明度（0.0-1.0）：由设置「界面前端透明度」驱动，100% 时整个前端隐藏"""
        if not hasattr(self, '_content_widget') or not self._content_widget:
            return
        from PyQt5.QtWidgets import QGraphicsOpacityEffect
        if not hasattr(self, '_ui_opacity_effect'):
            self._ui_opacity_effect = QGraphicsOpacityEffect(self._content_widget)
            self._content_widget.setGraphicsEffect(self._ui_opacity_effect)
        self._ui_opacity_effect.setOpacity(max(0.0, min(1.0, opacity)))

    def apply_text_colors(self):
        """把对话字体颜色（叠加补偿后的文字透明度）应用到所有已存在的 AI 消息"""
        from core.config import get_config_manager
        color = get_config_manager().get("theme.chat_text_color", "#cccccc")
        try:
            from core.text_opacity import with_alpha, effective_text_alpha
            color = with_alpha(color, effective_text_alpha())
        except Exception:
            pass
        if not hasattr(self, 'messages_layout'):
            return
        for i in range(self.messages_layout.count()):
            item = self.messages_layout.itemAt(i)
            w = item.widget() if item else None
            if w is not None and hasattr(w, 'set_text_color'):
                w.set_text_color(color)

    def resizeEvent(self, event):
        """调整大小时同步背景层大小"""
        super().resizeEvent(event)
        if hasattr(self, '_bg_widget') and self._bg_widget:
            self._bg_widget.setGeometry(self.rect())
        if hasattr(self, '_content_widget') and self._content_widget:
            self._content_widget.setGeometry(self.rect())

    def _send_pending_message(self, text: str):
        """发送之前等待的消息"""
        if not self.is_streaming:
            self._add_user_message(text)
            self._start_chat_stream(text)

    # ========== 模型管理 ==========

    def _open_share_ai_dialog(self):
        """对外开放 AI：把本程序的模型以 OpenAI Chat Completions 兼容接口提供给外部程序。
        外部程序（如 TRAE 的「自定义模型」）填入对话框给出的 请求地址 / 模型ID / API密钥 即可使用。
        """
        try:
            from widgets.api_server_dialog import ApiServerDialog
            dlg = ApiServerDialog(self, server_manager=self.server_manager)
            dlg.exec_()
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "错误", f"无法打开共享 AI 对话框：{e}")

    def _refresh_model_combo(self):
        """刷新模型下拉列表。
        规则：
          1) 预置占位模型（带 match_keywords 的本地预置）未就绪 → 直接隐藏，不再显示⭕；
          2) custom-local / sdk-model 两个「添加入口」始终保留：未就绪时显示 ➕，可点击跳转设置；
          3) 重复的空壳副本（同 name、同 type、路径/API 空）→ 隐藏；
          4) auto-imported / 已就绪的其它模型正常显示✅；
          5) SDK 其它模型（非 sdk-model）若未填 base_url → 隐藏。
        """
        import os
        self.model_combo.blockSignals(True)
        self.model_combo.clear()

        models = self.config.get_models()
        current_id = self.config.get("current_model_id", "")

        if not models:
            self.model_combo.addItem("➕ 添加模型...", "__add__")
            self.model_combo.blockSignals(False)
            return

        ENTRY_IDS = {"custom-local", "sdk-model"}

        # 先算一遍每个模型的就绪状态
        def _ready(m):
            if m.get("type") == "sdk":
                return bool(m.get("base_url"))
            mp = m.get("model_path", "")
            return bool(mp and os.path.exists(mp))

        # 真正显示的条目顺序（保持原顺序，只过滤）
        shown_ids = set()
        for m in models:
            mid = m.get("id")
            # 自身去重（极端兜底）
            if mid and mid in shown_ids:
                continue
            ready = _ready(m)
            icon = "💻" if m.get("type") == "local" else "☁️"
            mtype = m.get("type")
            match_kw = m.get("match_keywords") or []
            auto_imported = bool(m.get("_auto_imported"))

            # ---- Case 1：添加入口（custom-local / sdk-model）→ 始终保留 ----
            if mid in ENTRY_IDS:
                shown_ids.add(mid)
                if ready:
                    badge = "✅"
                    label = f"{badge} {icon} {m['name']}"
                else:
                    # 未就绪：➕ 前缀 + 正常文字色，表示点这里可以添加配置
                    prefix = "➕" if mtype == "local" else "☁️➕"
                    label = f"{prefix} {m['name']}（点击配置...）"
                    ready = False  # 保持未就绪标记，但前景颜色正常（可点击入口，不灰）
                self.model_combo.addItem(label, mid)
                if not ready:
                    # 不是灰，给个稍微浅一点的提示色（仍清晰可见，不混淆灰字⭕）
                    idx = self.model_combo.count() - 1
                    self.model_combo.setItemData(idx, QtGui.QColor("#a7c7e7"), QtCore.Qt.ForegroundRole)
                if mid == current_id:
                    self.model_combo.setCurrentIndex(self.model_combo.count() - 1)
                continue

            # ---- Case 2：本地预置占位模型（有 match_keywords、非 auto-imported、非 entry）----
            if mtype == "local" and match_kw and not auto_imported:
                if not ready:
                    # 未就绪 → 直接隐藏，不显示⭕
                    continue
                # 就绪 → 正常显示
                shown_ids.add(mid)
                label = f"✅ {icon} {m['name']}"
                self.model_combo.addItem(label, mid)
                if mid == current_id:
                    self.model_combo.setCurrentIndex(self.model_combo.count() - 1)
                continue

            # ---- Case 3：auto-imported 模型 → 始终显示（必然是已匹配文件的）----
            if auto_imported:
                shown_ids.add(mid)
                badge = "✅" if ready else "⭕"
                label = f"{badge} {icon} {m['name']}"
                self.model_combo.addItem(label, mid)
                if not ready:
                    idx = self.model_combo.count() - 1
                    self.model_combo.setItemData(idx, QtGui.QColor("#888888"), QtCore.Qt.ForegroundRole)
                if mid == current_id:
                    self.model_combo.setCurrentIndex(self.model_combo.count() - 1)
                continue

            # ---- Case 4：其它 SDK 模型（非 sdk-model id、type=sdk）----
            if mtype == "sdk":
                if not ready:
                    # base_url 空的空壳 SDK 模型 → 隐藏（用户用 sdk-model 添加入口即可）
                    continue
                shown_ids.add(mid)
                self.model_combo.addItem(f"✅ {icon} {m['name']}", mid)
                if mid == current_id:
                    self.model_combo.setCurrentIndex(self.model_combo.count() - 1)
                continue

            # ---- Case 5：其它本地模型（用户手填路径、无 match_kw、非 entry、非 auto）----
            if mtype == "local":
                # 同 name+type 且为空路径的「重复空壳」：隐藏（只保留 ENTRY 的 custom-local）
                if not ready:
                    # 检查是否和某个 ENTRY_ID 项同 name：若是重复空壳，隐藏
                    dup_of_entry = False
                    for em in models:
                        if em.get("id") in ENTRY_IDS and em.get("name") == m.get("name") and em.get("type") == mtype:
                            dup_of_entry = True
                            break
                    if dup_of_entry:
                        continue
                    # 其它非 entry 同名空壳（用户之前多次添加导致的副本）也隐藏
                    dup = False
                    for j, m2 in enumerate(models):
                        if id(m2) == id(m):
                            continue
                        if (m2.get("name") == m.get("name") and m2.get("type") == mtype
                                and (m2.get("match_keywords") or []) == (m.get("match_keywords") or [])
                                and _ready(m2)):
                            dup = True; break
                    if dup:
                        continue
                    # 兜底：未就绪、有 path 但文件不存在的：灰字显示，告知不可用
                    badge = "⭕"
                    label = f"{badge} {icon} {m['name']}"
                    self.model_combo.addItem(label, mid)
                    idx = self.model_combo.count() - 1
                    self.model_combo.setItemData(idx, QtGui.QColor("#888888"), QtCore.Qt.ForegroundRole)
                    shown_ids.add(mid)
                    if mid == current_id:
                        self.model_combo.setCurrentIndex(self.model_combo.count() - 1)
                    continue
                # 就绪：正常显示
                shown_ids.add(mid)
                self.model_combo.addItem(f"✅ {icon} {m['name']}", mid)
                if mid == current_id:
                    self.model_combo.setCurrentIndex(self.model_combo.count() - 1)
                continue

            # ---- 兜底：其他罕见类型直接保留 ----
            shown_ids.add(mid)
            badge = "✅" if ready else "⭕"
            self.model_combo.addItem(f"{badge} {icon} {m['name']}", mid)
            if not ready:
                idx = self.model_combo.count() - 1
                self.model_combo.setItemData(idx, QtGui.QColor("#888888"), QtCore.Qt.ForegroundRole)
            if mid == current_id:
                self.model_combo.setCurrentIndex(self.model_combo.count() - 1)

        self.model_combo.addItem("⚙️ 管理模型...", "__manage__")
        self.model_combo.blockSignals(False)

    def _on_model_combo_changed(self, idx: int):
        """模型下拉选择变化。
        对 custom-local / sdk-model 未就绪的「添加入口」：点击即打开设置对话框，
        不再只 set_current_model（否则用户不知道怎么填路径→"导入不了了"）。
        """
        if idx < 0:
            return
        data = self.model_combo.itemData(idx)
        if not data:
            return
        if data == "__add__" or data == "__manage__":
            # 打开设置
            self._open_settings_from_panel()
            # 恢复到当前选中
            self._refresh_model_combo()
            return

        ENTRY_IDS = {"custom-local", "sdk-model"}
        if data in ENTRY_IDS:
            # 检查该入口是否已就绪
            import os
            m = None
            for cand in self.config.get_models():
                if cand.get("id") == data:
                    m = cand
                    break
            if m is None:
                return
            if m.get("type") == "sdk":
                ready = bool(m.get("base_url"))
            else:
                mp = m.get("model_path", "")
                ready = bool(mp and os.path.exists(mp))
            if not ready:
                # 未就绪：打开设置让用户配置
                self._open_settings_from_panel()
                # 配置完后刷新模型列表（路径若填好，下次会显示为✅）
                self._refresh_model_combo()
                return
            # 已经就绪：正常切换当前模型
            if self.config.set_current_model(data):
                self._update_start_button()
            return

        # 普通模型：切换当前模型
        if self.config.set_current_model(data):
            self._update_start_button()
            # 服务正在运行/启动中：自动重启以加载新模型
            # （否则 llama-server 仍加载旧模型，对话还是旧模型在回答）
            self._restart_server_if_running()

    def _restart_server_if_running(self):
        """切换模型后，若模型服务正在运行/启动中，自动重启加载新模型"""
        if not self.server_manager:
            return
        if self.server_manager.status not in ("running", "starting"):
            return  # 服务未运行：下次点『启动』自然加载新模型
        model = self.config.get_current_model()
        if not model or model.get("type") != "local":
            return
        # 正在生成先停流，避免旧模型续写混入
        if self.is_streaming:
            self._stop_stream(reason="server_stopped")
        name = model.get("name", "新模型")
        self.server_manager.restart_server()
        self._add_ai_message(
            f"🔄 已切换模型：{name}\n服务正在自动重启加载新模型，请等状态显示『运行中』后再发送消息。",
            add_to_history=False
        )

    def _toggle_server(self):
        """切换模型服务启动/停止"""
        if not self.server_manager:
            return

        model = self.config.get_current_model()
        if not model:
            self._open_settings_from_panel()
            return

        if model["type"] != "local":
            # SDK 模型不需要启动
            return

        if self.server_manager.status in ("starting", "running"):
            # 停止路径：先停流式生成，再停服务（修复：之前停止后会误走 start_server 立即重启）
            if self.is_streaming:
                self._stop_stream(reason="server_stopped")
            self.server_manager.stop_server()
        else:
            self.server_manager.start_server()

    def _update_start_button(self):
        """更新启动按钮状态和文字"""
        model = self.config.get_current_model()
        if not model:
            self.start_btn.setText("➕ 添加模型")
            self.start_btn.setEnabled(True)
            return

        if model["type"] == "sdk":
            self.start_btn.setText("☁️ SDK 模式")
            self.start_btn.setEnabled(False)
            return

        # 本地模型
        status = self.server_manager.status if self.server_manager else "stopped"
        if status == "running":
            self.start_btn.setText("⏹ 停止")
            self.start_btn.setEnabled(True)
        elif status == "starting":
            self.start_btn.setText("⏳ 启动中...")
            self.start_btn.setEnabled(False)
        else:
            self.start_btn.setText("🚀 启动")
            self.start_btn.setEnabled(True)

    def _on_server_status_changed(self, status: str):
        """服务状态变化回调"""
        # 服务停止/异常/失败：若正在流式生成，立即中止（否则会继续显示幻觉/死等）
        if status in ("stopped", "error") and self.is_streaming:
            self._stop_stream(reason="server_stopped")
        if status == "running":
            # 服务启动成功，如果有待发送的消息就发送
            if self._pending_message:
                msg = self._pending_message
                self._pending_message = None
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(1000, lambda: self._send_pending_message(msg))

        self._update_start_button()

    # ========== 系统监控 ==========

    def _on_stats_updated(self, stats: dict):
        """系统状态更新（保留接口，状态显示在主窗口状态栏）"""
        pass

    def send_message(self):
        if self.is_streaming:
            # 流式中再次点击 = 「停止生成」
            self._stop_stream(reason="user_stop")
            return

        text = self.input_edit.toPlainText().strip()
        if not text:
            return

        # 角色扮演专用面板：未选择角色时提示，不进入普通对话逻辑
        if getattr(self, "roleplay_mode", False) and not self.current_character:
            self._add_ai_message(
                "🎭 请先在上方选择或新建角色，再开始角色扮演对话。",
                add_to_history=False
            )
            return

        # ---- 本地模型状态检查：避免 starting/error/stopped 时硬等 read timeout ----
        model = self.config.get_current_model()
        if model and model.get("type") == "local" and self.server_manager:
            s = self.server_manager.status
            if s == "starting":
                self._add_ai_message(
                    "⏳ 模型服务还在加载中，暂时无法回答。\n\n"
                    "请先等左下角状态栏的 『启动中...』 变成 『已连接』，"
                    "或换更小的模型（例如 Gemma 4 E4B）重试。"
                )
                return
            if s == "error":
                self._add_ai_message(
                    "❌ 模型服务启动失败。请尝试：\n"
                    "  1) 关掉占内存的其他软件；\n"
                    "  2) 在下拉框换更小的模型；\n"
                    "  3) 点击左侧『⚙️ 模型设置』重新配置启动参数。"
                )
                self._add_action_buttons_to_last(
                    ("🚀 启动模型服务", self._start_server_from_panel),
                    ("⚙️ 模型设置", self._open_settings_from_panel),
                )
                return
            if s != "running":
                # stopped：先启动服务，把消息存到 pending，等 running 自动发送
                self._add_ai_message("⏳ 正在启动模型服务，请稍候…")
                self._pending_message = text
                self.server_manager.start_server()
                self.input_edit.clear()
                return

        self.input_edit.clear()
        self._add_user_message(text, add_to_history=False)  # UI 先显示，等 AI 回完再成对入 history
        self._pending_user_text = text
        self._start_chat_stream(text)

    def _build_messages(self, user_message: str, total_token_budget: int = 0):
        """构建消息列表，包含上下文

        total_token_budget: 游戏模式整条 prompt 的 token 总预算（0 = 不限制）
        """
        msgs = []

        # 角色扮演模式（游戏世界模式）
        if self.current_character and self.current_session_path:
            char = self.current_character
            template = char.get_template()
            player_tpl = char.get_player_template()
            background = char.get_game_background(self.current_session_path)

            # 游戏式会话（有模板+游戏背景）：严格按游戏轮次格式构建
            if template.strip() and player_tpl.strip() and background.strip():
                from core.character_manager import build_game_round_prompt
                # 前面 N 次 AI 输出（N 由玩家在界面上指定）
                rounds = self._get_roleplay_rounds()
                ai_outputs = [m["content"] for m in self.chat_history if m.get("role") == "assistant"]
                prev_outputs = ai_outputs[-rounds:] if rounds > 0 else []
                # 最新角色属性值（首轮为空 → AI 按模板属性；之后轮由 AI 输出更新）
                current_attrs = char.get_game_attrs(self.current_session_path)
                return build_game_round_prompt(
                    char_name=char.name,
                    template=template,
                    player_template=player_tpl,
                    background=background,
                    prev_ai_outputs=prev_outputs,
                    current_attrs=current_attrs,
                    user_input=user_message,
                    total_token_budget=total_token_budget,
                )

            # 旧式角色（无模板/无游戏背景）：回退简单设定
            char_ctx = self._build_character_context()
            if char_ctx:
                msgs.append({"role": "user", "content": char_ctx})
                msgs.append({"role": "assistant", "content": f"好的，我是{char.name}。"})
            memory_rounds = self.config.get("chat.memory_rounds", 10)
            memory_rounds = max(1, min(100, int(memory_rounds)))
            history = self.chat_history[-memory_rounds:] if len(self.chat_history) > memory_rounds else self.chat_history
            msgs.extend(history)
            msgs.append({"role": "user", "content": user_message})
            return msgs

        # 普通模式：不注入任何内置提示词（无项目上下文/无系统角色设定），直接对话。
        # 仅添加历史消息（按配置的记忆轮数）
        memory_rounds = self.config.get("chat.memory_rounds", 10)
        memory_rounds = max(1, min(100, int(memory_rounds)))
        msgs.extend(self.chat_history[-memory_rounds:])
        msgs.append({"role": "user", "content": user_message})
        return msgs

    def _is_game_roleplay(self) -> bool:
        """当前是否为游戏式角色扮演会话（模板+玩家模板+游戏背景齐全）"""
        if not self.current_character or not self.current_session_path:
            return False
        char = self.current_character
        return bool(
            char.get_template().strip()
            and char.get_player_template().strip()
            and char.get_game_background(self.current_session_path).strip()
        )

    def _get_roleplay_rounds(self) -> int:
        """玩家指定的『前面第N次对话』轮数（游戏式角色扮演）

        统一读取 chat.memory_rounds（玩家在设置里的"对话记忆轮数"），
        回退旧的 roleplay.memory_rounds，确保普通对话和角色扮演共享同一个"记忆轮数"概念。
        """
        try:
            n = int(self.config.get("chat.memory_rounds", 1))
            if not n:
                n = int(self.config.get("roleplay.memory_rounds", 1))
        except Exception:
            n = 1
        return max(0, min(50, n))

    def _game_token_budget(self) -> tuple:
        """游戏模式的 (max_tokens, prompt总预算)（与网页端同一策略）：
        llama-server 的 -c 是 prompt+output 共享，需给 prompt 留出空间"""
        ctx_size = 8192
        try:
            cur = self.config.get_current_model() or {}
            ctx_size = max(2048, int(cur.get("ctx_size") or 8192))
        except Exception:
            pass
        if ctx_size >= 32768:
            max_tokens = 6144
        elif ctx_size >= 16384:
            max_tokens = 4096
        else:
            max_tokens = 2048
        total_budget = max(1024, ctx_size - max_tokens - 384)
        return max_tokens, total_budget

    def _start_chat_stream(self, user_message: str):
        self.is_streaming = True
        # 流式中发送按钮切换为「停止生成」，用户可随时打断
        self.send_btn.setText("⏹ 停止生成")
        self.send_btn.setEnabled(True)
        self.ai_msg = self._add_ai_message()
        self.full_response = ""
        self._in_thinking = False
        self._think_buffer = ""

        # 游戏式角色扮演：max_tokens 按模型上下文分级，prompt 设总预算（防止超过 llama-server 的 ctx）
        _game_mt, _game_budget = self._game_token_budget()
        _is_game = self._is_game_roleplay()
        max_tokens = _game_mt if _is_game else 4096

        messages = self._build_messages(
            user_message, total_token_budget=_game_budget if _is_game else 0
        )
        self._last_built_msgs = messages  # 供 Token 统计（输入=全部发给AI的信息）

        self.stream_thread = QThread()
        self.stream_worker = StreamWorker(self.llm_client, messages, max_tokens=max_tokens)
        self.stream_worker.moveToThread(self.stream_thread)

        self.stream_worker.chunk_received.connect(self._on_stream_chunk)
        self.stream_worker.finished.connect(self._on_stream_finished)
        self.stream_worker.error.connect(self._on_stream_error)
        self.stream_thread.started.connect(self.stream_worker.run)

        self.stream_thread.start()

    def _on_stream_chunk(self, chunk: str):
        self.full_response += chunk
        self._process_chunk(chunk)
        self._scroll_to_bottom()

    def _process_chunk(self, chunk: str):
        """处理流式输出，识别 <think> / <think_cont> 标签分流思考内容和回答内容
        - <think>...</think>                传统整段思考
        - <think_cont>...</think_cont>      逐 token 流式思考（llm_client 把 reasoning_content 包成这个）
        """
        if not chunk:
            return

        # 处理缓冲（上一次可能有不完整的标签）
        if self._think_buffer:
            chunk = self._think_buffer + chunk
            self._think_buffer = ""

        i = 0
        while i < len(chunk):
            if not self._in_thinking:
                # --- 不在思考中：找 <think 或 <think_cont ---
                idx_think = chunk.find("<think", i)
                idx_cont = chunk.find("<think_cont>", i)
                idx = -1
                if idx_think == -1:
                    idx = idx_cont
                elif idx_cont == -1:
                    idx = idx_think
                else:
                    idx = min(idx_think, idx_cont)

                if idx == -1:
                    remaining = chunk[i:]
                    partial = False
                    # 两种可能的开头需要缓冲（k 从 1 开始，避免 k=0 空串必命中）
                    for open_tag in ("<think", "<think_cont>"):
                        max_k = min(len(remaining), len(open_tag))
                        for k in range(max_k, 0, -1):
                            tail = remaining[-k:] if k > 0 else ""
                            if tail and open_tag.startswith(tail):
                                self._think_buffer = tail
                                chunk_to_append = remaining[:-k]
                                partial = True
                                break
                        if partial:
                            break
                    if not partial:
                        chunk_to_append = remaining
                    if chunk_to_append:
                        # 显示层二次清洗：防 llm_client 极端漏网
                        chunk_to_append = _strip_chatml_ui(chunk_to_append)
                        if chunk_to_append:
                            self.ai_msg.append_content(chunk_to_append)
                    break

                # 输出标签前的内容
                if idx > i:
                    self.ai_msg.append_content(chunk[i:idx])

                # 区分是 <think 还是 <think_cont>
                is_cont_tag = chunk.startswith("<think_cont>", idx)
                if is_cont_tag:
                    # <think_cont> 一定是 13 字节
                    tag_end = idx + len("<think_cont>")
                    # 进入思考模式（如果还没）
                    if not self._in_thinking:
                        self._in_thinking = True
                        self.ai_msg.start_thinking()
                    i = tag_end
                    continue

                # 普通 <think：找 > 结束
                end_tag = chunk.find(">", idx)
                if end_tag == -1:
                    self._think_buffer = chunk[idx:]
                    break
                # 进入思考模式（已在思考中则不重置计时器）
                if not self._in_thinking:
                    self._in_thinking = True
                    self.ai_msg.start_thinking()
                i = end_tag + 1
            else:
                # --- 在思考模式中：找 </think> 或 </think_cont> ---
                idx_end = chunk.find("</think>", i)
                idx_end_cont = chunk.find("</think_cont>", i)
                if idx_end == -1:
                    end_idx = idx_end_cont
                elif idx_end_cont == -1:
                    end_idx = idx_end
                else:
                    end_idx = min(idx_end, idx_end_cont)
                close_tag_len = (
                    len("</think>") if end_idx == idx_end else len("</think_cont>")
                ) if end_idx != -1 else 0

                if end_idx == -1:
                    remaining = chunk[i:]
                    partial = False
                    # 缓冲可能的关闭标签开头（k 从 1 开始，避免 k=0 空串必命中）
                    for close_tag in ("</think>", "</think_cont>"):
                        max_k = min(len(remaining), len(close_tag))
                        for k in range(max_k, 0, -1):
                            tail = remaining[-k:] if k > 0 else ""
                            if tail and close_tag.startswith(tail):
                                self._think_buffer = tail
                                chunk_to_append = remaining[:-k]
                                partial = True
                                break
                        if partial:
                            break
                    if not partial:
                        chunk_to_append = remaining
                    if chunk_to_append:
                        chunk_to_append = _strip_chatml_ui(chunk_to_append)
                        if chunk_to_append:
                            self.ai_msg.append_thinking(chunk_to_append)
                    break

                if end_idx > i:
                    self.ai_msg.append_thinking(chunk[i:end_idx])

                self._in_thinking = False
                self.ai_msg.finish_thinking()
                i = end_idx + close_tag_len
                continue
    def _stop_stream(self, reason: str = ""):
        """立即停止当前流式生成（用户主动停止 / 服务被关闭时调用）。
                i = end_idx + close_tag_len
        不把这一次不完整的 full_response 入史，避免把"半截内容"或"模型继续幻觉"污染下一轮。
        """
        was_streaming = self.is_streaming
        # 先停 worker（如果还在），避免后续 chunk 继续往气泡写
        if getattr(self, "stream_worker", None):
            try:
                self.stream_worker.stop()
            except Exception:
                pass
        if getattr(self, "stream_thread", None):
            try:
                self.stream_thread.quit()
                self.stream_thread.wait(1500)
            except Exception:
                pass
        self.stream_thread = None
        self.stream_worker = None

        self.is_streaming = False
        self._pending_user_text = None  # 本轮 user 也不入史：未完成对话视为取消
        # 恢复按钮
        self.send_btn.setText("发送")
        self.send_btn.setEnabled(True)
        # 如果气泡还在"思考中"状态，结束它
        if getattr(self, "ai_msg", None) is not None:
            if getattr(self, "_in_thinking", False):
                try:
                    self.ai_msg.finish_thinking()
                except Exception:
                    pass
            # 给气泡末尾加个状态说明（只在确实处于流式且有明显中断原因时）
            if was_streaming and reason == "user_stop":
                try:
                    self.ai_msg.append_content("\n\n⏹️ 已手动停止生成。")
                except Exception:
                    pass
            elif was_streaming and reason == "server_stopped":
                try:
                    self.ai_msg.append_content("\n\n⚠️ 模型服务已停止，生成本次回复中断。")
                except Exception:
                    pass
        self._in_thinking = False
        self._think_buffer = ""


    def _on_stream_finished(self):
        # ---- 入史前深度清洗（防 模型幻觉续写 / ChatML 标签 / 思考内容 污染上下文）----
        # 先剥离思考块，再和"剥离后"的文本比较长度（思考内容 legitimately 很长，
        # 不能计入长度差，否则会误报"异常续写"）
        try:
            from core.llm_client import strip_think_blocks
            no_think = strip_think_blocks(self.full_response)
        except Exception:
            no_think = re.sub(r"<think(?:ing|_cont)?>[\s\S]*?</think(?:ing|_cont)?>", "", self.full_response, flags=re.I)
        cleaned_resp, hallucinated = _sanitize_for_history(no_think)
        truncated = False
        if hallucinated or len(cleaned_resp) + 50 < len(no_think):
            # 清理掉了显著内容（说明模型之前在幻觉续写多轮），标记并给用户轻提示
            truncated = True
        self.full_response = cleaned_resp
        # 本轮 user + AI 回复成对入 history，保证严格 user/assistant 交替
        if getattr(self, "_pending_user_text", None):
            self.chat_history.append({"role": "user", "content": self._pending_user_text})
            self._pending_user_text = None
        # 统一入最终完整回复（最后一条重复则跳过）
        if self.full_response and (not self.chat_history or self.chat_history[-1].get("role") != "assistant" or self.chat_history[-1].get("content") != self.full_response):
            self.chat_history.append({"role": "assistant", "content": self.full_response})
        self.is_streaming = False
        self.send_btn.setText("发送")
        self.send_btn.setEnabled(True)
        # 如果思考还在进行中，强制结束
        if self._in_thinking:
            self._in_thinking = False
            self.ai_msg.finish_thinking()
        self._think_buffer = ""
        if self.stream_thread:
            self.stream_thread.quit()
            self.stream_thread.wait()
        self.stream_thread = None
        self.stream_worker = None

        # ---- 最终展示：用清洗后的完整文本走一次 markdown 渲染 ----
        # （流式期间 append_content 是纯文本追加，```代码块 / **加粗** 等只是原样字符；
        #   回复完成后重渲染一次，代码块、行内代码、加粗、换行才会正确显示）
        if getattr(self, "ai_msg", None) is not None and self.full_response:
            try:
                self.ai_msg.set_content(self.full_response)
            except Exception:
                pass

        if truncated and getattr(self, "ai_msg", None):
            try:
                self.ai_msg.append_content("\n\n⚠️ （本次回复检测到异常续写内容，已自动清理；如果不完整请重新提问。）")
            except Exception:
                pass

        # 角色扮演模式：显示输入/输出 Token 统计
        # 输入 = 发给 AI 的全部信息（角色设定+属性文件+历史+玩家输入），输出 = AI 回复
        if self.current_character and getattr(self, "ai_msg", None) is not None:
            try:
                from core.llm_client import estimate_tokens
                usage = getattr(self.llm_client, "last_usage", None) or {}
                input_tokens = usage.get("prompt_tokens") or 0
                output_tokens = usage.get("completion_tokens") or 0
                if not input_tokens:
                    # 服务端未返回用量时本地估算（含角色属性文件的完整上下文）
                    input_tokens = sum(
                        estimate_tokens(m.get("content", ""))
                        for m in (getattr(self, "_last_built_msgs", None) or [])
                    )
                if not output_tokens:
                    output_tokens = estimate_tokens(self.full_response)
                self.ai_msg.set_token_usage(int(input_tokens), int(output_tokens))
            except Exception:
                pass

        # 保存角色会话历史
        self._save_character_session()
        # 尝试从回复中提取角色属性更新（用清洗后的文本，避免匹配到思考内容里的标记）
        self._update_character_attrs_from_response(self.full_response)

        # 自动语音输出：「开始AI语音输出」开关开启，或角色扮演勾选了配音 → 朗读本轮回复
        if self.full_response and not truncated:
            rp_auto = (self._is_game_roleplay() and self.current_character
                       and self.config.get("roleplay.auto_tts", False))
            if self._tts_auto or rp_auto:
                voice, ref_path = self._tts_resolve()
                self._speak_text(self.full_response, voice=voice, ref_path=ref_path)

    def _on_stream_error(self, error_msg: str):
        self.ai_msg.append_content(f"\n\n❌ 连接失败")

        # 显示详细错误信息（截断避免太长）
        short_error = error_msg[:200] + "..." if len(error_msg) > 200 else error_msg
        self.ai_msg.append_content(f"\n\n📝 错误详情：{short_error}")

        # 如果是连接错误且有服务管理器，显示启动按钮
        is_connection_error = any(
            kw in error_msg.lower()
            for kw in ["connection", "refused", "failed to establish", "max retries", "winerror 10061", "连接", "拒绝"]
        )

        if is_connection_error and self.server_manager:
            self.ai_msg.append_content("\n\n🔌 模型服务未启动")
            self.ai_msg.append_content("\n点击下方按钮启动本地模型服务：")
            self.ai_msg.append_action_button("🚀 启动模型服务", self._start_server_from_panel)
            self.ai_msg.append_action_button("⚙️ 模型设置", self._open_settings_from_panel)

        self.is_streaming = False
        self.send_btn.setText("发送")
        self.send_btn.setEnabled(True)
        if self.stream_thread:
            self.stream_thread.quit()
            self.stream_thread.wait()
            self.stream_thread = None
            self.stream_worker = None

    # ========== 语音朗读（CosyVoice TTS） ==========

    def _refresh_tts_btn_row(self):
        """按当前 tts_engine 刷新按钮可见性 + 按钮文字"""
        try:
            engine = self.config.get("tts_engine", "gpt_sovits")
        except Exception:
            engine = "gpt_sovits"
        is_gs = engine == "gpt_sovits"
        self.gs_config_btn.setVisible(is_gs)
        self.voice_clone_btn.setVisible(not is_gs)
        # 更新启停按钮文字
        self._update_tts_svc_btn_text()

    def _on_gs_config_btn(self):
        """⚙️ 配置 GPT-SoVITS 按钮 — 发送信号让 main_window 切换到语音系统页面"""
        self.gs_config_requested.emit()

    def _update_tts_svc_btn_text(self):
        """按当前引擎 + 服务状态刷新启停按钮文字"""
        try:
            engine = self.config.get("tts_engine", "gpt_sovits")
        except Exception:
            engine = "gpt_sovits"
        name = "GPT-SoVITS" if engine == "gpt_sovits" else "CosyVoice"
        # 探测状态
        status = "stopped"
        try:
            if engine == "gpt_sovits":
                from core.gpt_sovits_server_manager import get_gpt_sovits_server_manager
                status = get_gpt_sovits_server_manager().status
            else:
                from core.tts_server_manager import get_tts_server_manager
                status = get_tts_server_manager().status
        except Exception:
            pass
        if status == "running":
            self.tts_svc_btn.setText(f"⏹ 停止{name}")
        elif status == "starting":
            self.tts_svc_btn.setText(f"⏳ {name}启动中")
        else:
            self.tts_svc_btn.setText(f"🎤 启动{name}")
        self.tts_svc_btn.setToolTip(f"当前语音引擎: {name}\n点击启动/停止服务")

    def _on_tts_svc_btn_clicked(self):
        """🎤 语音服务开关：对应当前引擎启停"""
        try:
            engine = self.config.get("tts_engine", "gpt_sovits")
        except Exception:
            engine = "gpt_sovits"

        if engine == "gpt_sovits":
            from core.gpt_sovits_server_manager import get_gpt_sovits_server_manager
            mgr = get_gpt_sovits_server_manager()
            name = "GPT-SoVITS"
        else:
            from core.tts_server_manager import get_tts_server_manager
            mgr = get_tts_server_manager()
            name = "CosyVoice"

        if mgr.status == "running":
            mgr.stop_service()
            self._update_tts_svc_btn_text()
        elif mgr.status == "starting":
            QMessageBox.information(self, "请稍候", f"{name} 正在启动（加载模型约 30-90 秒）...")
        else:
            if not mgr.start_service():
                QMessageBox.warning(self, "启动失败", f"{name} 启动失败，请查看语音系统页面日志")
            else:
                self._update_tts_svc_btn_text()
                # 120s 超时检查
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(120000, lambda: self._check_svc_timeout(engine))

    def _check_svc_timeout(self, engine: str):
        if engine == "gpt_sovits":
            from core.gpt_sovits_server_manager import get_gpt_sovits_server_manager
            mgr = get_gpt_sovits_server_manager()
            name = "GPT-SoVITS-v2pro"
        else:
            from core.tts_server_manager import get_tts_server_manager
            mgr = get_tts_server_manager()
            name = "CosyVoice"
        if mgr.status in ("starting",):
            QMessageBox.warning(
                self, "启动超时",
                f"{name} 启动超过 120 秒仍未就绪。\n\n"
                f"请检查 {name} 配置是否正确。")

    def _on_tts_svc_status(self, status: str):
        """按服务状态刷新语音服务按钮"""
        btn = getattr(self, "tts_svc_btn", None)
        if btn is None:
            return
        if status == "running":
            btn.setText("⏹ 停止语音服务")
            btn.setToolTip("语音服务运行中，点击停止服务")
        elif status == "starting":
            btn.setText("⏳ 语音服务启动中")
            btn.setToolTip("正在加载语音模型（约 10-60 秒），请稍候...")
        elif status == "error":
            btn.setText("🎤 重启语音服务")
            btn.setToolTip("语音服务出错，点击重试启动")
        else:
            btn.setText("🎤 启动语音服务")
            btn.setToolTip("启动 CosyVoice 本地语音服务（首次加载模型约 10-60 秒）；运行中点击停止服务")

    def _on_tts_btn_clicked(self):
        """开始AI语音输出开关：点击开启并保持，之后每轮 AI 回复自动朗读；再点停止"""
        self._tts_auto = not self._tts_auto
        if self._tts_auto:
            self._update_tts_btn_text()
        else:
            # 关闭：停止保持开启，同时停止当前合成/播放
            self._cancel_speak()

    def _update_tts_btn_text(self):
        """按当前状态刷新语音输出按钮文字"""
        if getattr(self, "_tts_busy", False):
            self.tts_btn.setText("⏸ 停止")
        elif getattr(self, "_tts_auto", False):
            self.tts_btn.setText("⏸ AI语音输出中")
        else:
            self.tts_btn.setText("🔊 开始AI语音输出")

    def _tts_default_voice(self) -> str:
        """全局默认音色（config models[] 的 tts 条目）"""
        try:
            m = self.config.get_tts_ready_model() or (
                self.config.get_tts_models() or [{}])[0]
            return m.get("voice", "中文女") if m else "中文女"
        except Exception:
            return "中文女"

    def _global_clone_audio(self) -> str:
        """全局默认克隆音频路径（config tts.default_ref_audio）"""
        try:
            p = self.config.get_tts_config().get("default_ref_audio", "")
            return p if (p and os.path.isfile(p)) else ""
        except Exception:
            return ""

    def _tts_resolve(self) -> tuple:
        """→ (voice, ref_path)：克隆音频只应用于指定时的对话
        普通模式 → 普通模式指定的克隆音频；角色扮演 → 当前角色指定的克隆音频（互不串用）
        """
        voice = self._tts_default_voice()
        ref_path = ""
        try:
            if self.current_character:
                ref_path = self.current_character.get_clone_audio()
                voice = self.current_character.get_voice() or voice
            else:
                ref_path = self._global_clone_audio()
        except Exception:
            pass
        # 指定了克隆音频时音色名交给服务端忽略即可（ref_path 优先级最高）
        return voice, ref_path

    # ---------- 克隆声音文件指定 ----------

    def _on_voice_clone_btn_clicked(self):
        """🎙 声音按钮：为当前对话指定/清除克隆音频（普通模式一份，角色扮演每个角色一份）"""
        menu = QMenu(self)
        if self.current_character:
            scope = f"角色「{self.current_character.name}」的对话"
        else:
            scope = "普通模式对话"

        cur = ""
        if self.current_character:
            cur = self.current_character.get_clone_audio()
        else:
            cur = self._global_clone_audio()

        cur_action = menu.addAction(f"生效范围：{scope}" if not cur else f"当前音频：{os.path.basename(cur)}（{scope}）")
        cur_action.setEnabled(False)
        menu.addSeparator()
        act_pick = menu.addAction("📁 选择克隆音频文件...")
        act_clear = menu.addAction("🗑️ 清除克隆音频")
        act_clear.setEnabled(bool(cur))

        chosen = menu.exec_(self.voice_clone_btn.mapToGlobal(self.voice_clone_btn.rect().bottomLeft()))
        if chosen == act_pick:
            path, _ = QFileDialog.getOpenFileName(
                self, "选择克隆参考音频（5-10 秒清晰人声效果最佳）", "",
                "音频文件 (*.wav *.mp3 *.flac *.ogg *.m4a);;所有文件 (*.*)")
            if not path:
                return
            if self.current_character:
                self.current_character.set_clone_audio(path)
                QMessageBox.information(
                    self, "已指定",
                    f"已为角色「{self.current_character.name}」指定克隆声音：\n{path}\n\n"
                    f"提示：旁挂同名 .txt 文件（写入音频中说的话）可提升克隆相似度。")
            else:
                self.config.set("tts.default_ref_audio", path)
                QMessageBox.information(
                    self, "已指定",
                    f"已为普通模式对话指定克隆声音：\n{path}\n\n"
                    f"提示：旁挂同名 .txt 文件（写入音频中说的话）可提升克隆相似度。")
            self._update_voice_clone_tip()
        elif chosen == act_clear:
            if self.current_character:
                self.current_character.set_clone_audio("")
            else:
                self.config.set("tts.default_ref_audio", "")
            self._update_voice_clone_tip()

    def _update_voice_clone_tip(self):
        """更新声音按钮 tooltip 显示当前对话生效的克隆音频"""
        if self.current_character:
            cur = self.current_character.get_clone_audio()
            scope = f"角色「{self.current_character.name}」的对话"
        else:
            cur = self._global_clone_audio()
            scope = "普通模式对话"
        if cur:
            self.voice_clone_btn.setToolTip(f"克隆声音已指定（{scope}）：\n{cur}\n点击可更换/清除")
            self.voice_clone_btn.setText("🎙 已指定")
        else:
            self.voice_clone_btn.setToolTip("指定克隆声音文件（只应用于当前对话）：\n普通模式 → 普通对话一份；角色扮演 → 每个角色各一份")
            self.voice_clone_btn.setText("🎙 声音")

    def _speak_text(self, text: str, voice: str = "", ref_path: str = ""):
        """朗读文本：按当前引擎 → 确保服务 → 后台线程合成 → 播放"""
        if not text.strip():
            return
        if self._tts_busy:
            self._cancel_speak()

        self._tts_busy = True
        self._tts_cancelled = False
        self._update_tts_btn_text()

        # 读取当前引擎
        try:
            engine = self.config.get("tts_engine", "gpt_sovits")
        except Exception:
            engine = "gpt_sovits"

        speed = 1.0
        gs_params = {}
        try:
            if engine == "cosyvoice":
                m = self.config.get_tts_ready_model() or (self.config.get_tts_models() or [{}])[0]
                speed = float(m.get("speed", 1.0)) if m else 1.0
            else:
                # 从 config 读 GPT-SoVITS 参数
                sovits_cfg = self.config.get("gpt_sovits", {})
                gs_params = {
                    "text_language": sovits_cfg.get("default_refer_lang", "zh"),
                    "refer_wav": sovits_cfg.get("default_refer_wav", ""),
                    "refer_text": sovits_cfg.get("default_refer_text", ""),
                    "refer_lang": sovits_cfg.get("default_refer_lang", "zh"),
                    "top_k": int(sovits_cfg.get("top_k", 5)),
                    "top_p": float(sovits_cfg.get("top_p", 1.0)),
                    "temperature": float(sovits_cfg.get("temperature", 1.0)),
                }
                speed = float(sovits_cfg.get("speed", 1.0))
        except Exception:
            pass

        # 服务未运行则自动拉起
        def _ensure():
            nonlocal engine
            if engine == "gpt_sovits":
                from core.gpt_sovits_server_manager import get_gpt_sovits_server_manager
                mgr = get_gpt_sovits_server_manager()
                if mgr.status != "running":
                    if not mgr.start_service():
                        worker._skip = True
                        worker.failed.emit("GPT-SoVITS 服务启动失败")
                        return
                    # 等待就绪
                    import time as _t
                    deadline = _t.time() + 120
                    while _t.time() < deadline:
                        if mgr.status == "running":
                            break
                        if mgr.status == "error":
                            worker._skip = True
                            worker.failed.emit("GPT-SoVITS 服务启动错误")
                            return
                        _t.sleep(1)
            else:
                from core.tts_client import ensure_tts_service
                if not ensure_tts_service(max_wait=60):
                    worker._skip = True
                    worker.failed.emit("语音服务未就绪，请启动 CosyVoice")

        worker = TTSSynthesizeWorker(text, voice=voice, speed=speed, ref_path=ref_path,
                                     engine=engine, gs_params=gs_params)
        thread = QThread(self)
        worker.moveToThread(thread)

        worker.finished_ok.connect(self._on_tts_finished)
        worker.failed.connect(self._on_tts_failed)
        thread.started.connect(_ensure, type=Qt.QueuedConnection)
        thread.started.connect(worker.run)
        worker.finished_ok.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_tts_thread_done)

        self._tts_worker = worker
        self._tts_thread = thread
        thread.start()

    def _on_tts_finished(self, wav_path: str):
        if self._tts_cancelled:
            return
        from core.audio_player import get_audio_player
        self._tts_busy = False
        get_audio_player().play(wav_path)
        self._update_tts_btn_text()

    def _on_tts_failed(self, err: str):
        if self._tts_cancelled:
            return
        self._tts_busy = False
        self._update_tts_btn_text()
        if getattr(self, "ai_msg", None) is not None:
            try:
                self.ai_msg.append_content(f"\n\n🔇 朗读失败：{err[:120]}")
            except Exception:
                pass

    def _on_tts_thread_done(self):
        self._tts_thread = None

    def _cancel_speak(self):
        """停止合成与播放"""
        from core.audio_player import get_audio_player
        self._tts_cancelled = True
        get_audio_player().stop()
        worker = getattr(self, "_tts_worker", None)
        thread = getattr(self, "_tts_thread", None)
        if worker is not None:
            worker._skip = True
        if thread is not None:
            thread.quit()
        self._tts_worker = None
        self._tts_busy = False
        self._update_tts_btn_text()

    def _on_auto_tts_toggled(self, checked: bool):
        self.config.set("roleplay.auto_tts", bool(checked))

    # ========== 角色扮演功能 ==========

    def _on_rounds_changed(self, value: int):
        """玩家修改历史轮数（发给 AI 的前面第N次对话数量）——同步到 chat.memory_rounds"""
        try:
            v = max(0, min(50, int(value)))
            # 同时写 chat.memory_rounds（主）和 roleplay.memory_rounds（兼容旧配置）
            self.config.set("chat.memory_rounds", v if v > 0 else 1)
            self.config.set("roleplay.memory_rounds", v)
        except Exception:
            pass

    def _refresh_character_combo(self):
        """刷新角色下拉列表"""
        if not self.character_manager:
            return

        self.character_combo.blockSignals(True)
        self.character_combo.clear()

        # 首项：角色扮演专用面板 →「— 选择角色 —」；混合面板 →「— 普通模式 —」
        first_text = "— 选择角色 —" if getattr(self, "roleplay_mode", False) else "— 普通模式 —"
        self.character_combo.addItem(first_text, "")

        characters = self.character_manager.get_characters()
        for char in characters:
            self.character_combo.addItem(f"🎭 {char.name}", char.name)

        self.character_combo.addItem("➕ 新建角色...", "__add__")

        self.character_combo.blockSignals(False)

    def _on_character_changed(self, idx: int):
        """角色选择变化"""
        if not self.character_manager or idx < 0:
            return

        data = self.character_combo.itemData(idx)
        if data == "__add__":
            self._add_character()
            self._refresh_character_combo()
            # 恢复到之前的选择（屏蔽信号：避免重复弹窗/重复加载会话）
            self.character_combo.blockSignals(True)
            restored = False
            if self.current_character:
                for i in range(self.character_combo.count()):
                    if self.character_combo.itemData(i) == self.current_character.name:
                        self.character_combo.setCurrentIndex(i)
                        restored = True
                        break
            if not restored:
                self.character_combo.setCurrentIndex(0)
            self.character_combo.blockSignals(False)
            return

        if data == "":
            # 未选择角色（角色扮演面板首项）：清空会话并提示先选角色
            self.current_character = None
            self.current_session_path = None
            self.current_character_icon = ""
            self.new_session_btn.setEnabled(False)
            self.char_status_label.setText("")
            self.rounds_label.setVisible(False)
            self.rounds_spin.setVisible(False)
            self.chat_history = []
            self._pending_user_text = None
            self._clear_messages()
            self._update_voice_clone_tip()
            self._add_ai_message(
                "🎭 角色扮演对话模式\n\n"
                "请先在上方选择一个角色，或点「➕ 新建角色」创建新角色，"
                "再开始角色扮演对话。",
                add_to_history=False
            )
            return

        # 切换到角色
        char = self.character_manager.get_character(data)
        if char:
            self.current_character = char
            self.current_character_icon = char.icon_file if char.has_icon else ""
            self.new_session_btn.setEnabled(True)
            self.char_status_label.setText(f"角色: {char.name}")
            self._update_voice_clone_tip()
            self.rounds_label.setVisible(True)
            self.rounds_spin.setVisible(True)

            # 加载最近的会话，如果没有则创建新会话
            sessions = char.get_sessions()
            if sessions:
                self._load_character_session(sessions[0]["path"])
            else:
                self._new_character_session()

    def _add_character(self):
        """添加新角色（游戏世界创建向导）"""
        from widgets.character_dialog import CharacterDialog
        dialog = CharacterDialog(
            self.character_manager, parent=self,
            server_manager=self.server_manager, config=self.config,
        )
        if dialog.exec_():
            self._refresh_character_combo()
            # 选中新角色并加载刚创建的对话文件夹
            session_path = getattr(dialog, "created_session_path", "")
            name = getattr(dialog, "character_name", "")
            if name:
                for i in range(self.character_combo.count()):
                    if self.character_combo.itemData(i) == name:
                        self.character_combo.blockSignals(True)
                        self.character_combo.setCurrentIndex(i)
                        self.character_combo.blockSignals(False)
                        break
                char = self.character_manager.get_character(name)
                if char:
                    self.current_character = char
                    self.current_character_icon = char.icon_file if char.has_icon else ""
                    self.new_session_btn.setEnabled(True)
                    if session_path and os.path.exists(session_path):
                        self._load_character_session(session_path)
                    else:
                        sessions = char.get_sessions()
                        if sessions:
                            self._load_character_session(sessions[0]["path"])
                        else:
                            self._new_character_session()

    def _manage_characters(self):
        """管理角色"""
        from PyQt5.QtWidgets import QInputDialog, QMessageBox

        characters = self.character_manager.get_characters()
        if not characters:
            QMessageBox.information(self, "提示", "还没有创建任何角色")
            return

        # 简单的管理：选择一个角色进行编辑或删除
        char_names = [c.name for c in characters]
        name, ok = QInputDialog.getItem(
            self, "管理角色", "选择角色:", char_names, 0, False
        )
        if ok and name:
            char = self.character_manager.get_character(name)
            if char:
                # 提供编辑/删除选项
                from PyQt5.QtWidgets import QDialog, QVBoxLayout, QPushButton
                dlg = QDialog(self)
                dlg.setWindowTitle(f"角色: {name}")
                dlg.setFixedSize(200, 120)
                layout = QVBoxLayout(dlg)
                layout.setSpacing(8)

                edit_btn = QPushButton("✏️ 编辑角色")
                edit_btn.clicked.connect(dlg.accept)
                layout.addWidget(edit_btn)

                delete_btn = QPushButton("🗑️ 删除角色")
                delete_btn.setStyleSheet("""
                    QPushButton {
                        background: #c62828;
                        color: white;
                        border: none;
                        border-radius: 4px;
                        padding: 8px;
                    }
                    QPushButton:hover { background: #d32f2f; }
                """)
                delete_btn.clicked.connect(lambda: self._delete_character(name, dlg))
                layout.addWidget(delete_btn)

                cancel_btn = QPushButton("取消")
                cancel_btn.clicked.connect(dlg.reject)
                layout.addWidget(cancel_btn)

                if dlg.exec_():
                    # 编辑角色
                    from widgets.character_dialog import CharacterDialog
                    edit_dialog = CharacterDialog(
                        self.character_manager, character_name=name, parent=self,
                        server_manager=self.server_manager, config=self.config,
                    )
                    if edit_dialog.exec_():
                        self._refresh_character_combo()
                        # 如果是当前角色，刷新图标
                        if self.current_character and self.current_character.name == name:
                            self.current_character = self.character_manager.get_character(name)
                            self.current_character_icon = self.current_character.icon_file if self.current_character.has_icon else ""

    def _delete_character(self, name: str, parent_dialog):
        """删除角色"""
        from PyQt5.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除角色 '{name}' 吗？\n所有会话记录也将被删除，此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.character_manager.delete_character(name)
            parent_dialog.reject()
            self._refresh_character_combo()
            # 如果删除的是当前角色，切换到普通模式
            if self.current_character and self.current_character.name == name:
                self.character_combo.setCurrentIndex(0)

    def _new_character_session(self):
        """创建新的角色会话（游戏式：角色名_编号 对话文件夹）"""
        if not self.current_character:
            return

        # 游戏式：用最新游戏背景创建对话文件夹（角色名_编号 + 游戏背景.txt + 对话历史.txt）
        if self.current_character.get_latest_world_file():
            session_path = self.current_character.create_game_session()
        else:
            session_path = self.current_character.create_session()
        self._load_character_session(session_path)

    def _load_character_session(self, session_path: str):
        """加载角色会话"""
        if not self.current_character:
            return

        self.current_session_path = session_path
        self.chat_history = []
        self._clear_messages()

        # 读取历史消息
        history = self.current_character.get_session_history(session_path)
        for msg in history:
            if msg["role"] == "user":
                self._add_user_message(msg["content"])
            else:
                self._add_ai_message(msg["content"])

        # 如果没有历史，显示欢迎消息（不入 history：避免未配对 assistant 单项破坏交替）
        if not history:
            if self.current_character.is_game_session(session_path):
                bg = self.current_character.get_game_background(session_path)
                player_tpl = self.current_character.get_player_template()
                self._add_ai_message(
                    f"🎮 **游戏世界已就绪**\n\n"
                    f"角色: **{self.current_character.name}**\n"
                    + (f"玩家背景: {player_tpl.strip()[:80]}{'…' if len(player_tpl.strip()) > 80 else ''}\n" if player_tpl.strip() else "")
                    + (f"世界设定: {bg.strip()[:120]}{'…' if len(bg.strip()) > 120 else ''}\n\n" if bg.strip() else "")
                    + f"输入你的第一个行为选择或自定义行动，开始游戏！\n"
                    f"（可输入 &n 选择 AI 给出的行为选项，或直接输入自定义内容）",
                    add_to_history=False
                )
            else:
                attrs = self.current_character.initial_attrs
                self._add_ai_message(
                    f"🎭 已进入角色扮演模式\n\n"
                    f"角色: **{self.current_character.name}**\n\n"
                    f"初始设定:\n{attrs[:200]}{'...' if len(attrs) > 200 else ''}\n\n"
                    f"让我们开始对话吧！",
                    add_to_history=False
                )

        # 更新状态
        import os
        session_name = os.path.basename(session_path)
        self.char_status_label.setText(f"{self.current_character.name} · {session_name}")

    def _clear_messages(self):
        """清空消息区域"""
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _save_character_session(self):
        """保存当前角色会话"""
        if not self.current_character or not self.current_session_path:
            return

        self.current_character.save_session_history(
            self.current_session_path,
            self.chat_history
        )

    def _update_character_attrs_from_response(self, response: str):
        """从 AI 回复中提取最新角色属性值

        游戏式会话：AI 按格式在回复末尾输出 '角色属性:11 22 33 ...'（纯数字），
        提取后整写为会话最新属性值（属性随每轮变化，下一轮发给 AI）。
        旧式会话：兼容 [属性更新]...[/属性更新] 标记（追加）。
        """
        if not self.current_character or not self.current_session_path:
            return

        import re

        # 游戏式：提取 '角色属性:' 纯数字行
        from core.character_manager import extract_attr_numbers
        nums = extract_attr_numbers(response)
        if nums:
            self.current_character.update_session_attrs(self.current_session_path, nums)
            return

        # 旧式：显式属性更新标记
        pattern = r'\[属性更新\]([\s\S]*?)\[/属性更新\]'
        matches = re.findall(pattern, response)

        if matches:
            for match in matches:
                attrs_text = match.strip()
                if attrs_text:
                    self.current_character.update_session_attrs(
                        self.current_session_path,
                        attrs_text
                    )
            return

        # 如果没有显式标记，不自动更新（避免误判）

    def _build_character_context(self) -> str:
        """构建角色上下文（用于发送给AI）"""
        if not self.current_character or not self.current_session_path:
            return ""

        # 读取当前会话的角色属性
        attrs = self.current_character.get_session_attrs(self.current_session_path)

        # 精简版提示词，节省 token
        context = (
            f"【角色扮演】\n"
            f"你是{self.current_character.name}。\n"
            f"设定：{attrs}\n\n"
            f"规则：始终以{self.current_character.name}的身份和口吻回复。"
            f"如果角色状态变化，回复末尾用[属性更新]...[/属性更新]记录变化。"
        )
        return context
