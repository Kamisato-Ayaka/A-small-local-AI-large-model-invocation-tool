"""
CosyVoice 分步安装面板 - 克隆仓库 / conda 环境 / 下载模型
"""
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QGroupBox,
)

from core.tts_installer import TTSInstaller, STEP_NAMES


class CosyVoiceInstallPanel(QWidget):
    """三步安装面板（嵌入设置对话框的 TTS 模型表单）"""

    state_changed = pyqtSignal()   # 就绪状态变化，通知设置对话框刷新徽标

    def __init__(self, parent=None):
        super().__init__(parent)
        self._installer: TTSInstaller = None
        self._step_buttons = {}
        self._step_labels = {}
        self._init_ui()

    # 惰性创建 installer（QObject 需要 QApplication 就绪）
    @property
    def installer(self) -> TTSInstaller:
        if self._installer is None:
            self._installer = TTSInstaller(self)
            self._installer.step_started.connect(self._on_step_started)
            self._installer.step_finished.connect(self._on_step_finished)
            self._installer.log_received.connect(self._append_log)
            self._installer.install_state_changed.connect(self.refresh_state)
            self._installer.install_state_changed.connect(self.state_changed.emit)
        return self._installer

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 环境提示
        self.env_hint = QLabel("")
        self.env_hint.setWordWrap(True)
        self.env_hint.setStyleSheet("color: #e0a000; font-size: 11px;")
        layout.addWidget(self.env_hint)

        group = QGroupBox("分步安装（文件安装到 models/CosyVoice/）")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(8)

        # 三个步骤行
        self._step_rows = []
        for step in (0, 1, 2):
            row = QHBoxLayout()
            icon = QLabel("⬜")
            icon.setFixedWidth(20)
            name = QLabel(f"步骤 {step}：{STEP_NAMES[step]}"
                          + ("（torch 体积大，需磁盘 ≥20GB、10-30 分钟）" if step == 1 else ""))
            row.addWidget(icon)
            row.addWidget(name, 1)
            btn = QPushButton("开始")
            btn.setObjectName("secondaryBtn")
            btn.setFixedSize(64, 24)
            btn.clicked.connect(lambda _, s=step: self.installer.run_step(s))
            row.addWidget(btn)
            group_layout.addLayout(row)
            self._step_rows.append((icon, btn))

        # 一键 + 取消
        all_row = QHBoxLayout()
        btn_all = QPushButton("🚀 一键安装")
        btn_all.setFixedSize(120, 32)
        btn_all.setCursor(Qt.PointingHandCursor)
        btn_all.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #ff6b35, stop:0.5 #ff4444, stop:1 #e94560);
                color: white;
                border: none;
                border-radius: 6px;
                font-weight: 700;
                font-size: 13px;
                padding: 6px 16px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #ff8550, stop:0.5 #ff6060, stop:1 #ff5a7a);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #e55a2b, stop:0.5 #d63030, stop:1 #c73752);
            }
            QPushButton:disabled {
                background: rgba(100,100,100,0.4);
                color: rgba(200,200,200,0.4);
            }
        """)
        btn_all.clicked.connect(self._run_all)
        all_row.addWidget(btn_all)
        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("secondaryBtn")
        btn_cancel.setFixedSize(64, 26)
        btn_cancel.clicked.connect(self._cancel)
        all_row.addWidget(btn_cancel)
        all_row.addStretch()
        group_layout.addLayout(all_row)

        layout.addWidget(group)

        # 日志
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(140)
        self.log_view.setStyleSheet(
            "QTextEdit { background: #151520; color: #b8b8b8; border: 1px solid #3a3a44;"
            " border-radius: 8px; font-family: Consolas; font-size: 11px; }")
        layout.addWidget(self.log_view, 1)

        self.refresh_state()

    # ---------- 状态刷新 ----------

    def refresh_state(self):
        """检测环境刷新按钮/图标/提示"""
        info = self.installer.check_environment()

        hints = []
        if not info["git"]:
            hints.append("未检测到 git（步骤 0 需要）：https://git-scm.com/download/win")
        if not info["conda"]:
            hints.append("未检测到 conda（步骤 1 需要）：https://docs.conda.io/en/latest/miniconda.html")
        self.env_hint.setText("\n".join(hints))

        states = [
            ("✅" if info["cloned"] else "⬜", bool(info["git"])),
            ("✅" if info["requirements_ok"] else "⬜", bool(info["conda"])),
            ("✅" if info["model_ready"] else "⬜", True),
        ]
        for i, (icon_label, btn) in enumerate(self._step_rows):
            icon_label.setText(states[i][0])
            btn.setEnabled(states[i][1] and not self.installer.is_running())

    # ---------- 事件 ----------

    def _run_all(self):
        self._append_log("========== 一键安装开始 ==========")
        self.installer.run_all()

    def _cancel(self):
        self.installer.cancel()
        self._append_log("[用户] 已请求取消当前步骤...")

    def _on_step_started(self, step: int):
        icon, btn = self._step_rows[step]
        icon.setText("⏳")
        for _, b in self._step_rows:
            b.setEnabled(False)
        self._append_log(f"---------- 步骤 {step}：{STEP_NAMES.get(step, '')} 开始 ----------")

    def _on_step_finished(self, step: int, ok: bool, message: str):
        icon, _ = self._step_rows[step]
        icon.setText("✅" if ok else "❌")
        self._append_log(f"---------- 步骤 {step} {'完成' if ok else '失败'}: {message} ----------")
        self.refresh_state()

    def _append_log(self, line: str):
        self.log_view.append(line)
        # 限制行数防止内存膨胀
        doc = self.log_view.document()
        if doc.blockCount() > 500:
            cursor = self.log_view.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.movePosition(cursor.Down, cursor.KeepAnchor, doc.blockCount() - 400)
            cursor.removeSelectedText()
