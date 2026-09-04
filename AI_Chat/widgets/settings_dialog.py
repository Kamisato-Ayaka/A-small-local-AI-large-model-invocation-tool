"""
设置对话框 - 多模型管理、服务配置、通用设置
"""
import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QPushButton, QFileDialog, QSpinBox,
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QMessageBox,
    QDoubleSpinBox, QListWidget, QListWidgetItem, QSplitter,
    QStackedWidget, QSizePolicy
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont, QIcon, QColor

from core.config import get_config_manager


class SettingsDialog(QDialog):
    """设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = get_config_manager()
        self._editing_model_id = None
        self.setWindowTitle("设置")
        self.setMinimumSize(720, 520)
        self.setModal(True)
        self._init_ui()
        self._load_models()
        self._load_appearance_settings()
        self._load_server_settings()
        self._load_app_settings()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        # 标签页
        tabs = QTabWidget()
        tabs.addTab(self._create_models_tab(), "模型管理")
        tabs.addTab(self._create_appearance_tab(), "外观主题")
        tabs.addTab(self._create_server_tab(), "服务设置")
        tabs.addTab(self._create_app_tab(), "通用设置")
        layout.addWidget(tabs, 1)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("secondaryBtn")
        btn_cancel.setFixedSize(80, 32)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_ok = QPushButton("保存")
        btn_ok.setFixedSize(100, 32)
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._on_save)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

        self.setStyleSheet("""
            QDialog { background: #0f0f14; }
            QLabel { color: #d4d4d4; font-family: "Microsoft YaHei"; font-size: 12px; }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                background: #1a1a24; color: #e0e0e0;
                border: 1px solid #3a3a44; border-radius: 8px;
                padding: 8px 12px; font-family: "Consolas"; font-size: 12px;
                selection-background-color: #00d4ff;
            }
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
                border-color: #00d4ff; background: #1f1f2a;
            }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox::down-arrow {
                width: 0; height: 0;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #00d4ff;
            }
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #007acc, stop:1 #00d4ff);
                color: white; border: none;
                border-radius: 8px; font-family: "Microsoft YaHei"; font-size: 12px;
                padding: 6px 16px; font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1a8ad6, stop:1 #33ddff);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #005a9e, stop:1 #00a8cc);
            }
            QPushButton:disabled {
                background: #2d2d3a; color: #6b6b7b;
            }
            QPushButton#deleteBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #cc3333, stop:1 #ff4444);
            }
            QPushButton#deleteBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #dd4444, stop:1 #ff6666);
            }
            QPushButton#deleteBtn:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #aa2222, stop:1 #cc3333);
            }
            QPushButton#secondaryBtn {
                background: transparent; color: #d4d4d4; border: 1px solid #3a3a44;
                border-radius: 8px; font-family: "Microsoft YaHei"; font-size: 12px;
                font-weight: normal;
            }
            QPushButton#secondaryBtn:hover {
                background: #252530; border-color: #00d4ff; color: #00d4ff;
            }
            QPushButton#secondaryBtn:pressed {
                background: #1a1a24;
            }
            QPushButton#secondaryBtn:checked {
                background: #252530; border-color: #00d4ff; color: #00d4ff;
            }
            QGroupBox {
                color: #e0e0e0; border: 1px solid #3a3a44; border-radius: 10px;
                margin-top: 14px; padding: 12px 14px 14px 14px;
                font-family: "Microsoft YaHei"; font-size: 12px; font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 14px; padding: 0 10px;
                color: #00d4ff;
            }
            QCheckBox { color: #d4d4d4; font-family: "Microsoft YaHei"; font-size: 12px; spacing: 8px; }
            QCheckBox::indicator {
                width: 16px; height: 16px; border: 1px solid #3a3a44;
                border-radius: 4px; background: #1a1a24;
            }
            QCheckBox::indicator:checked {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #007acc, stop:1 #00d4ff);
                border-color: #00d4ff;
            }
            QListWidget {
                background: #151520; color: #d4d4d4;
                border: 1px solid #3a3a44; border-radius: 10px;
                font-family: "Microsoft YaHei"; font-size: 12px;
                outline: none; padding: 4px;
            }
            QListWidget::item {
                padding: 10px 12px; border-bottom: none;
                border-left: 3px solid transparent;
                border-radius: 6px; margin: 2px 4px;
            }
            QListWidget::item:selected {
                background: #1a2a3a; color: #00d4ff;
                border-left: 3px solid #00d4ff;
            }
            QListWidget::item:hover {
                background: #1f1f2e;
                border-left: 3px solid rgba(0, 212, 255, 80);
            }
            QTabWidget::pane {
                border: 1px solid #3a3a44; background: #0f0f14;
                top: -1px; border-radius: 6px;
            }
            QTabBar::tab {
                background: #1a1a24; color: #a0a0b0; padding: 10px 20px;
                border: 1px solid #3a3a44; border-bottom: none;
                border-top-left-radius: 8px; border-top-right-radius: 8px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #007acc, stop:1 #00d4ff);
                color: white; font-weight: bold;
            }
            QTabBar::tab:hover { background: #252530; color: #d4d4d4; }
            QSplitter::handle { background: #3a3a44; }
            QSpinBox::up-button, QSpinBox::down-button,
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                background: #252530; border: none; width: 16px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover,
            QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
                background: #00d4ff;
            }
        """)

    # ========== 模型管理标签页 ==========

    def _create_models_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 左侧：模型列表
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        left_header = QHBoxLayout()
        title = QLabel("模型列表")
        title.setStyleSheet("font-size: 13px; font-weight: bold; color: #cccccc;")
        left_header.addWidget(title)
        left_header.addStretch()

        btn_add = QPushButton("+ 添加")
        btn_add.setObjectName("secondaryBtn")
        btn_add.setFixedSize(72, 26)
        btn_add.clicked.connect(self._add_model_dialog)
        left_header.addWidget(btn_add)

        left_layout.addLayout(left_header)

        self.model_list = QListWidget()
        self.model_list.currentRowChanged.connect(self._on_model_selected)
        left_layout.addWidget(self.model_list, 1)

        # 底部操作按钮
        btn_row = QHBoxLayout()
        self.btn_delete = QPushButton("删除")
        self.btn_delete.setObjectName("deleteBtn")
        self.btn_delete.setFixedSize(72, 26)
        self.btn_delete.clicked.connect(self._delete_model)
        btn_row.addWidget(self.btn_delete)
        btn_row.addStretch()
        left_layout.addLayout(btn_row)

        # 右侧：模型详情
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        right_title = QLabel("模型配置")
        right_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #cccccc;")
        right_layout.addWidget(right_title)

        # 类型切换
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("类型："))
        self.model_type_combo = QComboBox()
        self.model_type_combo.addItem("本地模型 (llama.cpp)", "local")
        self.model_type_combo.addItem("AI SDK (OpenAI 兼容)", "sdk")
        self.model_type_combo.addItem("🎙️ 本地语音 (CosyVoice)", "tts")
        self.model_type_combo.currentIndexChanged.connect(self._on_model_type_changed)
        type_row.addWidget(self.model_type_combo)
        type_row.addStretch()
        right_layout.addLayout(type_row)

        # 名称
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("模型名称："))
        self.model_name_edit = QLineEdit()
        self.model_name_edit.setPlaceholderText("给模型起个名字")
        name_row.addWidget(self.model_name_edit, 1)
        right_layout.addLayout(name_row)

        # 配置详情堆叠
        self.model_detail_stack = QStackedWidget()
        self.model_detail_stack.addWidget(self._create_local_model_form())
        self.model_detail_stack.addWidget(self._create_sdk_model_form())
        self.model_detail_stack.addWidget(self._create_tts_model_form())
        right_layout.addWidget(self.model_detail_stack, 1)

        # 分隔器
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([220, 460])
        layout.addWidget(splitter)

        # 保存按钮行
        save_row = QHBoxLayout()
        save_row.addStretch()
        self.btn_save_model = QPushButton("保存模型配置")
        self.btn_save_model.setFixedSize(120, 32)
        self.btn_save_model.clicked.connect(self._save_model_config)
        save_row.addWidget(self.btn_save_model)
        right_layout.addLayout(save_row)

        # 初始状态
        self._set_model_detail_enabled(False)

        return widget

    def _create_local_model_form(self) -> QWidget:
        """本地模型配置表单"""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)

        # 模型文件
        self.local_model_path = QLineEdit()
        self.local_model_path.setPlaceholderText(".gguf 模型文件路径")
        btn = QPushButton("浏览...")
        btn.setObjectName("secondaryBtn")
        btn.setFixedSize(72, 26)
        btn.clicked.connect(lambda: self._browse_file(self.local_model_path, "GGUF 模型文件 (*.gguf)"))
        row = QHBoxLayout()
        row.addWidget(self.local_model_path, 1)
        row.addWidget(btn)
        w = QWidget()
        w.setLayout(row)
        layout.addRow("模型文件：", w)

        # 多模态视觉模型 (mmproj)
        self.local_mmproj_path = QLineEdit()
        self.local_mmproj_path.setPlaceholderText("可选：多模态视觉模型 (mmproj) 文件")
        btn2 = QPushButton("浏览...")
        btn2.setObjectName("secondaryBtn")
        btn2.setFixedSize(72, 26)
        btn2.clicked.connect(lambda: self._browse_file(self.local_mmproj_path, "GGUF 文件 (*.gguf)"))
        row2 = QHBoxLayout()
        row2.addWidget(self.local_mmproj_path, 1)
        row2.addWidget(btn2)
        w2 = QWidget()
        w2.setLayout(row2)
        layout.addRow("多模态视觉模型：", w2)

        hint = QLabel("💡 多模态视觉模型用于支持图片理解，如 Qwen-VL 系列")
        hint.setStyleSheet("color: #808080; font-size: 11px;")
        layout.addRow("", hint)

        # GPU 层数
        self.local_ngl = QSpinBox()
        self.local_ngl.setRange(0, 9999)
        self.local_ngl.setValue(999)
        self.local_ngl.setSpecialValueText("全部")
        layout.addRow("GPU 层数：", self.local_ngl)

        # 上下文大小
        self.local_ctx = QSpinBox()
        self.local_ctx.setRange(512, 131072)
        self.local_ctx.setSingleStep(512)
        self.local_ctx.setValue(8192)
        layout.addRow("上下文大小：", self.local_ctx)

        # 最大生成长度
        self.local_npred = QSpinBox()
        self.local_npred.setRange(64, 131072)
        self.local_npred.setSingleStep(256)
        self.local_npred.setValue(4096)
        layout.addRow("最大生成长度：", self.local_npred)

        # Temperature
        self.local_temp = QDoubleSpinBox()
        self.local_temp.setRange(0.0, 2.0)
        self.local_temp.setSingleStep(0.1)
        self.local_temp.setValue(0.7)
        self.local_temp.setDecimals(2)
        layout.addRow("Temperature：", self.local_temp)

        # 模型下载地址
        download_hint = QLabel(
            '📥 <b>模型下载</b>：'
            '<a href="https://huggingface.co/TrevorJS/gemma-4-E4B-it-uncensored-GGUF" style="color:#58a6ff;">Gemma 4 E4B</a>'
            ' | '
            '<a href="https://blog.csdn.net/weixin_41961749/article/details/161501525" style="color:#58a6ff;">Qwen3.6-35B</a>'
            ''
        )
        download_hint.setOpenExternalLinks(True)
        download_hint.setStyleSheet("color: #888; font-size: 11px;")
        download_hint.setWordWrap(True)
        layout.addRow("", download_hint)

        return widget

    def _create_sdk_model_form(self) -> QWidget:
        """AI SDK 配置表单"""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)

        # Base URL
        self.sdk_base_url = QLineEdit()
        self.sdk_base_url.setPlaceholderText("https://api.openai.com/v1")
        layout.addRow("API 地址：", self.sdk_base_url)

        # API Key
        self.sdk_api_key = QLineEdit()
        self.sdk_api_key.setPlaceholderText("sk-...")
        self.sdk_api_key.setEchoMode(QLineEdit.Password)
        btn_show = QPushButton("显示")
        btn_show.setObjectName("secondaryBtn")
        btn_show.setFixedSize(60, 26)
        btn_show.setCheckable(True)
        btn_show.toggled.connect(
            lambda v: self.sdk_api_key.setEchoMode(QLineEdit.Normal if v else QLineEdit.Password)
        )
        row = QHBoxLayout()
        row.addWidget(self.sdk_api_key, 1)
        row.addWidget(btn_show)
        w = QWidget()
        w.setLayout(row)
        layout.addRow("API Key：", w)

        # 模型名
        self.sdk_model_name = QLineEdit()
        self.sdk_model_name.setPlaceholderText("gpt-4 / qwen-turbo / ...")
        layout.addRow("模型名称：", self.sdk_model_name)

        # Temperature
        self.sdk_temp = QDoubleSpinBox()
        self.sdk_temp.setRange(0.0, 2.0)
        self.sdk_temp.setSingleStep(0.1)
        self.sdk_temp.setValue(0.7)
        self.sdk_temp.setDecimals(2)
        layout.addRow("Temperature：", self.sdk_temp)

        hint = QLabel("💡 支持所有 OpenAI 兼容接口的服务（如 DeepSeek、Moonshot、通义千问等）")
        hint.setStyleSheet("color: #808080; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addRow("", hint)

        return widget

    def _create_tts_model_form(self) -> QWidget:
        """CosyVoice TTS 配置表单（含分步安装）"""
        from core.tts_client import TTSClient
        from widgets.tts_install_panel import CosyVoiceInstallPanel

        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)

        # 预训练模型选择
        self.tts_model_key = QComboBox()
        self.tts_model_key.addItem("CosyVoice2-0.5B（推荐，约 5GB）", "CosyVoice2-0.5B")
        self.tts_model_key.addItem("Fun-CosyVoice3-0.5B-2512（约 9.1GB，效果更好）",
                                   "Fun-CosyVoice3-0.5B-2512")
        layout.addRow("语音模型：", self.tts_model_key)

        # 音色
        self.tts_voice = QComboBox()
        self.tts_voice.setEditable(True)
        for v in ["中文女", "中文男", "英文女", "英文男", "日文女", "日文男", "粤语女", "韩语女"]:
            self.tts_voice.addItem(v)
        # 服务活着时用真实音色列表覆盖
        try:
            voices = TTSClient().get_voices()
            if voices:
                self.tts_voice.clear()
                self.tts_voice.addItems(voices)
        except Exception:
            pass
        layout.addRow("默认音色：", self.tts_voice)

        # 语速
        self.tts_speed = QDoubleSpinBox()
        self.tts_speed.setRange(0.5, 2.0)
        self.tts_speed.setSingleStep(0.1)
        self.tts_speed.setValue(1.0)
        self.tts_speed.setDecimals(2)
        layout.addRow("语速：", self.tts_speed)

        # 朗读字数上限（每次朗读的文本最大长度）
        self.tts_max_chars = QSpinBox()
        self.tts_max_chars.setRange(100, 10000)
        self.tts_max_chars.setSingleStep(100)
        self.tts_max_chars.setValue(int(self.config.get("tts.max_read_chars", 1000)))
        self.tts_max_chars.setToolTip("每次朗读的最大文本字数，超出部分截断。\n字数越多合成耗时越长")
        layout.addRow("朗读字数上限：", self.tts_max_chars)

        # 服务端口
        self.tts_port = QSpinBox()
        self.tts_port.setRange(1024, 65535)
        self.tts_port.setValue(8901)
        layout.addRow("服务端口：", self.tts_port)

        # 服务启停 + 状态
        svc_row = QHBoxLayout()
        self.tts_status_label = QLabel("⬜ 语音服务未运行")
        self.tts_status_label.setStyleSheet("color: #8a8a8a; font-size: 11px;")
        svc_row.addWidget(self.tts_status_label, 1)
        self.tts_start_btn = QPushButton("启动语音服务")
        self.tts_start_btn.setObjectName("secondaryBtn")
        self.tts_start_btn.setFixedSize(96, 26)
        self.tts_start_btn.clicked.connect(self._start_tts_service)
        svc_row.addWidget(self.tts_start_btn)
        self.tts_stop_btn = QPushButton("停止")
        self.tts_stop_btn.setObjectName("secondaryBtn")
        self.tts_stop_btn.setFixedSize(56, 26)
        self.tts_stop_btn.clicked.connect(self._stop_tts_service)
        svc_row.addWidget(self.tts_stop_btn)
        layout.addRow("", svc_row)

        svc_hint = QLabel(
            f"💡 服务地址 http://127.0.0.1:8901 可供外部程序调用"
            f"（GET /health、POST /tts）。首次启动需加载模型 10-60 秒。")
        svc_hint.setStyleSheet("color: #808080; font-size: 11px;")
        svc_hint.setWordWrap(True)
        layout.addRow("", svc_hint)

        # CosyVoice 下载地址
        cv_download_hint = QLabel(
            '📥 <b>CosyVoice 下载</b>：'
            '<a href="https://github.com/QwenAudio/CosyVoice" style="color:#58a6ff;">官方仓库</a>'
            ' | '
            '<a href="https://www.modelscope.cn/models/iic/Fun-CosyVoice3-0.5B-2512" style="color:#58a6ff;">ModelScope 模型</a>'
            ''
        )
        cv_download_hint.setOpenExternalLinks(True)
        cv_download_hint.setStyleSheet("color: #888; font-size: 11px;")
        cv_download_hint.setWordWrap(True)
        layout.addRow("", cv_download_hint)

        # 分步安装面板
        self.tts_install_panel = CosyVoiceInstallPanel()
        self.tts_install_panel.state_changed.connect(self._load_models)
        layout.addRow("", self.tts_install_panel)

        # 切换语音模型下拉框时立即写回 config：
        # ① 安装步骤2按此下载对应模型 ② 服务运行中切换会自动停止旧服务
        self.tts_model_key.currentIndexChanged.connect(self._save_tts_updates_to_config)

        return widget

    # ---------- TTS 服务启停 ----------

    def _start_tts_service(self):
        from core.tts_server_manager import get_tts_server_manager

        # 先保存表单里的端口/音色等，让服务读到最新配置
        self._save_tts_updates_to_config()

        mgr = get_tts_server_manager()
        mgr.log_received.connect(self._append_tts_log, Qt.UniqueConnection)
        mgr.status_changed.connect(self._on_tts_status_changed, Qt.UniqueConnection)
        if not mgr.start_service():
            QMessageBox.warning(self, "启动失败", "语音服务启动失败，请查看安装面板日志")

    def _stop_tts_service(self):
        from core.tts_server_manager import get_tts_server_manager
        get_tts_server_manager().stop_service()
        self._on_tts_status_changed("stopped")

    def _append_tts_log(self, line: str):
        if hasattr(self, "tts_install_panel"):
            self.tts_install_panel._append_log(line)

    def _on_tts_status_changed(self, status: str):
        mapping = {
            "stopped": ("⬜ 语音服务未运行", "#8a8a8a"),
            "starting": ("⏳ 语音服务启动中（加载模型约 10-60 秒）...", "#e0a000"),
            "running": ("✅ 语音服务运行中", "#33cc70"),
            "error": ("❌ 语音服务错误，请查看日志", "#ff5555"),
        }
        text, color = mapping.get(status, (status, "#8a8a8a"))
        if hasattr(self, "tts_status_label"):
            self.tts_status_label.setText(text)
            self.tts_status_label.setStyleSheet(f"color: {color}; font-size: 11px;")
        if hasattr(self, "tts_start_btn") and hasattr(self, "tts_stop_btn"):
            busy = status in ("starting", "running")
            self.tts_start_btn.setEnabled(not busy)
            self.tts_stop_btn.setEnabled(busy)

    def _save_tts_updates_to_config(self):
        """把 TTS 表单写回 config（供服务启动前读取）"""
        if self._editing_model_id:
            old_key = ""
            try:
                m = self.config.get_tts_models()[0]
                old_key = m.get("model_key", "") if m else ""
            except Exception:
                pass
            new_key = self.tts_model_key.currentData() or "CosyVoice2-0.5B"
            updates = {
                "model_key": new_key,
                "voice": self.tts_voice.currentText().strip() or "中文女",
                "speed": self.tts_speed.value(),
            }
            self.config.update_model(self._editing_model_id, updates)
            # 语音模型切换且服务正在运行 → 停止旧模型服务（下次启动自动加载新模型）
            if old_key and new_key != old_key:
                from core.tts_server_manager import get_tts_server_manager
                mgr = get_tts_server_manager()
                if mgr.status in ("running", "starting", "error"):
                    mgr.stop_service()
                    self._on_tts_status_changed("stopped")
                    self.tts_install_panel._append_log(
                        f"[切换] 语音模型已切换为 {new_key}，服务已停止，请重新启动语音服务")
        self.config.set("tts.port", self.tts_port.value())
        self.config.set("tts.max_read_chars", self.tts_max_chars.value())

    def _browse_file(self, line_edit: QLineEdit, filter_str: str):
        path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", filter_str)
        if path:
            line_edit.setText(path)
            # 如果名称为空，自动填文件名
            if not self.model_name_edit.text().strip():
                name = os.path.splitext(os.path.basename(path))[0]
                self.model_name_edit.setText(name[:40])

    def _set_model_detail_enabled(self, enabled: bool):
        """启用/禁用模型详情面板"""
        self.model_type_combo.setEnabled(enabled)
        self.model_name_edit.setEnabled(enabled)
        self.model_detail_stack.setEnabled(enabled)
        self.btn_save_model.setEnabled(enabled)
        self.btn_delete.setEnabled(enabled)

    def _load_models(self):
        """加载模型列表，标记 ⭕未就绪 / ✅就绪"""
        import os
        self.model_list.clear()
        models = self.config.get_models()
        current_id = self.config.get("current_model_id", "")

        icon_map = {"local": "💻", "sdk": "☁️", "tts": "🎙️"}
        for m in models:
            item = QListWidgetItem()
            icon_text = icon_map.get(m["type"], "❔")
            if m["type"] == "sdk":
                ready = bool(m.get("base_url"))
            elif m["type"] == "tts":
                env_py = self._tts_env_python()
                ready = (bool(m.get("repo_dir") and os.path.isdir(m.get("repo_dir", "")))
                         and bool(env_py)
                         and bool(m.get("model_dir") and os.path.isdir(m.get("model_dir", ""))))
            else:
                mp = m.get("model_path", "")
                ready = bool(mp and os.path.exists(mp))
            badge = "✅" if ready else "⭕"
            display = f"{badge} {icon_text} {m['name']}"
            if m["id"] == current_id:
                display += "  ✓"
            item.setText(display)
            item.setData(Qt.UserRole, m["id"])
            if not ready:
                fg = item.foreground()
                fg.setColor(QColor("#8a8a8a"))
                item.setForeground(fg)
            self.model_list.addItem(item)

        if models:
            # 选中当前模型
            for i in range(self.model_list.count()):
                item = self.model_list.item(i)
                if item.data(Qt.UserRole) == current_id:
                    self.model_list.setCurrentRow(i)
                    break
        else:
            self._set_model_detail_enabled(False)

    def _tts_env_python(self):
        try:
            from core.tts_installer import TTSInstaller
            return TTSInstaller().env_python()
        except Exception:
            return None

    def _on_model_selected(self, row: int):
        """选中模型时加载详情"""
        if row < 0:
            self._set_model_detail_enabled(False)
            return

        item = self.model_list.item(row)
        model_id = item.data(Qt.UserRole)
        models = self.config.get_models()

        for m in models:
            if m["id"] == model_id:
                self._editing_model_id = model_id
                self._fill_model_form(m)
                self._set_model_detail_enabled(True)
                break

    def _fill_model_form(self, model: dict):
        """填充模型配置表单"""
        self.model_name_edit.setText(model.get("name", ""))

        mtype = model.get("type", "local")
        idx_map = {"local": 0, "sdk": 1, "tts": 2}
        idx = idx_map.get(mtype, 0)
        self.model_type_combo.setCurrentIndex(idx)
        self.model_detail_stack.setCurrentIndex(idx)

        if mtype == "local":
            self.local_model_path.setText(model.get("model_path", ""))
            self.local_mmproj_path.setText(model.get("mmproj_path", ""))
            self.local_ngl.setValue(model.get("n_gpu_layers", 999))
            self.local_ctx.setValue(model.get("ctx_size", 8192))
            self.local_npred.setValue(model.get("n_predict", 4096))
            self.local_temp.setValue(model.get("temperature", 0.7))
        elif mtype == "tts":
            key_idx = self.tts_model_key.findData(model.get("model_key", "CosyVoice2-0.5B"))
            self.tts_model_key.setCurrentIndex(key_idx if key_idx >= 0 else 0)
            voice = model.get("voice", "中文女")
            v_idx = self.tts_voice.findText(voice)
            if v_idx >= 0:
                self.tts_voice.setCurrentIndex(v_idx)
            else:
                self.tts_voice.setEditText(voice)
            self.tts_speed.setValue(model.get("speed", 1.0))
            self.tts_port.setValue(self.config.get_tts_config().get("port", 8901))
            self.tts_max_chars.setValue(int(self.config.get("tts.max_read_chars", 1000)))
            self._on_tts_status_changed(
                "running" if self._tts_service_running() else "stopped")
        else:
            self.sdk_base_url.setText(model.get("base_url", ""))
            self.sdk_api_key.setText(model.get("api_key", ""))
            self.sdk_model_name.setText(model.get("model_name", ""))
            self.sdk_temp.setValue(model.get("temperature", 0.7))

    def _tts_service_running(self) -> bool:
        try:
            from core.tts_server_manager import get_tts_server_manager
            return get_tts_server_manager().is_running
        except Exception:
            return False

    def _on_model_type_changed(self, idx: int):
        """模型类型切换"""
        self.model_detail_stack.setCurrentIndex(idx)

    def _add_model_dialog(self):
        """添加新模型"""
        # 选择类型
        type_dialog = QDialog(self)
        type_dialog.setWindowTitle("添加模型")
        type_dialog.setFixedSize(360, 260)
        type_dialog.setModal(True)

        dlg_layout = QVBoxLayout(type_dialog)
        dlg_layout.setContentsMargins(20, 16, 20, 16)
        dlg_layout.setSpacing(12)

        title = QLabel("选择模型类型")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #00d4ff;")
        dlg_layout.addWidget(title)

        btn_local = QPushButton("💻  本地模型 (llama.cpp)")
        btn_local.setFixedHeight(48)
        btn_local.setObjectName("secondaryBtn")
        btn_local.clicked.connect(lambda: type_dialog.done(1))
        dlg_layout.addWidget(btn_local)

        btn_sdk = QPushButton("☁️  AI SDK (OpenAI 兼容)")
        btn_sdk.setFixedHeight(48)
        btn_sdk.setObjectName("secondaryBtn")
        btn_sdk.clicked.connect(lambda: type_dialog.done(2))
        dlg_layout.addWidget(btn_sdk)

        btn_tts = QPushButton("🎙️  本地语音 (CosyVoice)")
        btn_tts.setFixedHeight(48)
        btn_tts.setObjectName("secondaryBtn")
        btn_tts.clicked.connect(lambda: type_dialog.done(3))
        dlg_layout.addWidget(btn_tts)

        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedHeight(32)
        btn_cancel.clicked.connect(type_dialog.reject)
        dlg_layout.addWidget(btn_cancel)

        type_dialog.setStyleSheet("""
            QDialog { background: #0f0f14; }
            QLabel { color: #d4d4d4; font-family: "Microsoft YaHei"; }
            QPushButton {
                background: #1a1a24; color: #d4d4d4; border: 1px solid #3a3a44;
                border-radius: 10px; font-family: "Microsoft YaHei"; font-size: 13px;
                text-align: left; padding-left: 16px; font-weight: normal;
            }
            QPushButton:hover { background: #252530; border-color: #00d4ff; color: #00d4ff; }
            QPushButton:last-child {
                background: transparent; color: #888; border: 1px solid #3a3a44;
                text-align: center; padding-left: 0; font-size: 12px;
                border-radius: 8px;
            }
            QPushButton:last-child:hover { background: #252530; border-color: #00d4ff; color: #00d4ff; }
        """)

        result = type_dialog.exec_()
        if result == 0:
            return

        mtype_map = {1: "local", 2: "sdk", 3: "tts"}
        mtype = mtype_map.get(result, "local")
        default_names = {"local": "新本地模型", "sdk": "新 SDK 模型", "tts": "CosyVoice 本地语音"}
        default_name = default_names.get(mtype, "新模型")

        # 创建空模型并选中
        import time
        new_model = {
            "id": f"{mtype}-{int(time.time()*1000)}",
            "name": default_name,
            "type": mtype,
        }

        if mtype == "local":
            new_model.update({
                "model_path": "",
                "mmproj_path": "",
                "n_gpu_layers": 999,
                "ctx_size": 8192,
                "n_predict": 4096,
                "temperature": 0.7,
            })
        elif mtype == "tts":
            new_model.update({
                "engine": "cosyvoice",
                "model_key": "CosyVoice2-0.5B",
                "voice": "中文女",
                "speed": 1.0,
                "auto_start": False,
                "repo_dir": "",
                "model_dir": "",
            })
        else:
            new_model.update({
                "base_url": "https://api.openai.com/v1",
                "api_key": "",
                "model_name": "",
                "temperature": 0.7,
            })

        self.config.add_model(new_model)
        self._load_models()

        # 选中新模型
        for i in range(self.model_list.count()):
            item = self.model_list.item(i)
            if item.data(Qt.UserRole) == new_model["id"]:
                self.model_list.setCurrentRow(i)
                break

    def _save_model_config(self, silent: bool = False):
        """保存当前模型配置

        silent=True 时由底部「保存」按钮调用：
        校验失败（如占位模型没有文件路径）则跳过保存且不弹窗，不阻塞其他设置保存。
        """
        if not self._editing_model_id:
            return

        name = self.model_name_edit.text().strip()
        if not name:
            if not silent:
                QMessageBox.warning(self, "提示", "请输入模型名称")
            return

        mtype = self.model_type_combo.currentData() or "local"
        updates = {
            "name": name,
            "type": mtype,
        }

        if mtype == "local":
            model_path = self.local_model_path.text().strip()
            if not model_path:
                if not silent:
                    QMessageBox.warning(self, "提示", "请选择模型文件")
                return
            updates.update({
                "model_path": model_path,
                "mmproj_path": self.local_mmproj_path.text().strip(),
                "n_gpu_layers": self.local_ngl.value(),
                "ctx_size": self.local_ctx.value(),
                "n_predict": self.local_npred.value(),
                "temperature": self.local_temp.value(),
            })
        elif mtype == "tts":
            # 未安装完也允许保存占位（安装面板负责补齐 repo_dir/model_dir）
            updates.update({
                "model_key": self.tts_model_key.currentData() or "CosyVoice2-0.5B",
                "voice": self.tts_voice.currentText().strip() or "中文女",
                "speed": self.tts_speed.value(),
            })
            self.config.set("tts.max_read_chars", self.tts_max_chars.value())
            if self.tts_port.value() != self.config.get_tts_config().get("port", 8901):
                self.config.set("tts.port", self.tts_port.value())
        else:
            base_url = self.sdk_base_url.text().strip()
            if not base_url:
                if not silent:
                    QMessageBox.warning(self, "提示", "请输入 API 地址")
                return
            model_name = self.sdk_model_name.text().strip()
            if not model_name:
                if not silent:
                    QMessageBox.warning(self, "提示", "请输入模型名称")
                return
            updates.update({
                "base_url": base_url,
                "api_key": self.sdk_api_key.text().strip(),
                "model_name": model_name,
                "temperature": self.sdk_temp.value(),
            })

        self.config.update_model(self._editing_model_id, updates)
        self._load_models()

        # 重新选中
        for i in range(self.model_list.count()):
            item = self.model_list.item(i)
            if item.data(Qt.UserRole) == self._editing_model_id:
                self.model_list.setCurrentRow(i)
                break

        if not silent:
            QMessageBox.information(self, "已保存", "模型配置已保存")

    def _delete_model(self):
        """删除当前模型"""
        if not self._editing_model_id:
            return

        reply = QMessageBox.question(
            self, "删除模型",
            "确定要删除这个模型吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.config.delete_model(self._editing_model_id)
            self._editing_model_id = None
            self._load_models()

    # ========== 服务设置标签页 ==========

    def _create_server_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        conn_group = QGroupBox("🔌 连接设置")
        conn_layout = QFormLayout(conn_group)
        conn_layout.setSpacing(10)

        self.host_edit = QLineEdit()
        self.host_edit.setText("127.0.0.1")
        conn_layout.addRow("主机地址：", self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8080)
        conn_layout.addRow("端口：", self.port_spin)

        layout.addWidget(conn_group)

        server_group = QGroupBox("🖥️ 本地服务")
        server_layout = QVBoxLayout(server_group)

        self.auto_start_check = QCheckBox("启动 A Small Local AI Runner 时自动启动本地模型服务")
        server_layout.addWidget(self.auto_start_check)

        path_row = QHBoxLayout()
        self.server_path_edit = QLineEdit()
        self.server_path_edit.setPlaceholderText("llama-server.exe 路径（留空自动查找）")
        srv_btn = QPushButton("浏览...")
        srv_btn.setObjectName("secondaryBtn")
        srv_btn.setFixedSize(72, 26)
        srv_btn.clicked.connect(self._choose_server_file)
        path_row.addWidget(self.server_path_edit, 1)
        path_row.addWidget(srv_btn)
        pw = QWidget()
        pw.setLayout(path_row)
        server_layout.addWidget(QLabel("llama-server 路径："))
        server_layout.addWidget(pw)

        layout.addWidget(server_group)
        layout.addStretch()

        return widget

    def _choose_server_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 llama-server", "",
            "可执行文件 (*.exe);;所有文件 (*.*)"
        )
        if path:
            self.server_path_edit.setText(path)

    def _load_server_settings(self):
        cfg = self.config.load()
        self.host_edit.setText(cfg.get("llm", {}).get("host", "127.0.0.1"))
        self.port_spin.setValue(cfg.get("llm", {}).get("port", 8080))
        self.auto_start_check.setChecked(cfg.get("server", {}).get("auto_start", False))
        self.server_path_edit.setText(cfg.get("server", {}).get("llama_server_path", ""))

    # ========== 外观主题标签页 ==========

    def _create_appearance_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 背景图片（壁纸统一走「导入Wallpaper Engine壁纸文件夹」，作用于整个程序窗口）
        bg_group = QGroupBox("🖼️ 背景图片")
        bg_layout = QFormLayout(bg_group)
        bg_layout.setSpacing(10)

        # 文字透明度（所有文字：对话、按钮、菜单等；壁纸不透明不受影响）
        self.text_opacity_spin = QSpinBox()
        self.text_opacity_spin.setRange(0, 100)
        self.text_opacity_spin.setValue(100)
        self.text_opacity_spin.setSuffix(" %")
        self.text_opacity_spin.setToolTip("所有文字的最终透明度（已自动补偿界面前端透明度的衰减）；调低可让文字更隐入壁纸")
        bg_layout.addRow("文字透明度：", self.text_opacity_spin)

        # 界面前端透明度（100% = 前端完全隐藏，只剩壁纸）
        self.ui_transparency_spin = QSpinBox()
        self.ui_transparency_spin.setRange(0, 100)
        self.ui_transparency_spin.setValue(50)
        self.ui_transparency_spin.setSuffix(" %")
        self.ui_transparency_spin.setToolTip("调到 100% 时界面元素完全隐藏，只剩壁纸")
        bg_layout.addRow("界面前端透明度：", self.ui_transparency_spin)

        # 从本地壁纸文件夹选择（如 Wallpaper Engine 复制出来的壁纸文件夹）
        we_btn = QPushButton("📁 导入Wallpaper Engine壁纸文件夹...")
        we_btn.setObjectName("secondaryBtn")
        we_btn.setToolTip("扫描本地壁纸文件夹（每个子文件夹=一个壁纸，支持 Wallpaper Engine 复制出来的目录）")
        we_btn.clicked.connect(self._open_we_import)

        layout.addWidget(bg_group)
        layout.addWidget(we_btn)

        # 主题颜色
        color_group = QGroupBox("🎨 主题颜色")
        color_layout = QFormLayout(color_group)
        color_layout.setSpacing(10)

        # 编辑器背景色
        self.editor_color_edit = QLineEdit()
        self.editor_color_edit.setPlaceholderText("#1e1e1e")
        self.editor_color_edit.setMaxLength(9)
        btn_ec = QPushButton("选色")
        btn_ec.setObjectName("secondaryBtn")
        btn_ec.setFixedSize(56, 26)
        btn_ec.clicked.connect(lambda: self._pick_color(self.editor_color_edit))
        row_ec = QHBoxLayout()
        row_ec.addWidget(self.editor_color_edit, 1)
        row_ec.addWidget(btn_ec)
        w_ec = QWidget()
        w_ec.setLayout(row_ec)
        color_layout.addRow("编辑器底色：", w_ec)

        # 对话背景色
        self.chat_color_edit = QLineEdit()
        self.chat_color_edit.setPlaceholderText("#252526")
        self.chat_color_edit.setMaxLength(9)
        btn_cc = QPushButton("选色")
        btn_cc.setObjectName("secondaryBtn")
        btn_cc.setFixedSize(56, 26)
        btn_cc.clicked.connect(lambda: self._pick_color(self.chat_color_edit))
        row_cc = QHBoxLayout()
        row_cc.addWidget(self.chat_color_edit, 1)
        row_cc.addWidget(btn_cc)
        w_cc = QWidget()
        w_cc.setLayout(row_cc)
        color_layout.addRow("对话底色：", w_cc)

        # 对话字体颜色
        self.chat_text_color_edit = QLineEdit()
        self.chat_text_color_edit.setPlaceholderText("#cccccc")
        self.chat_text_color_edit.setMaxLength(9)
        btn_ct = QPushButton("选色")
        btn_ct.setObjectName("secondaryBtn")
        btn_ct.setFixedSize(56, 26)
        btn_ct.clicked.connect(lambda: self._pick_color(self.chat_text_color_edit))
        row_ct = QHBoxLayout()
        row_ct.addWidget(self.chat_text_color_edit, 1)
        row_ct.addWidget(btn_ct)
        w_ct = QWidget()
        w_ct.setLayout(row_ct)
        color_layout.addRow("对话字体颜色：", w_ct)

        # 强调色
        self.accent_color_edit = QLineEdit()
        self.accent_color_edit.setPlaceholderText("#007acc")
        self.accent_color_edit.setMaxLength(9)
        btn_ac = QPushButton("选色")
        btn_ac.setObjectName("secondaryBtn")
        btn_ac.setFixedSize(56, 26)
        btn_ac.clicked.connect(lambda: self._pick_color(self.accent_color_edit))
        row_ac = QHBoxLayout()
        row_ac.addWidget(self.accent_color_edit, 1)
        row_ac.addWidget(btn_ac)
        w_ac = QWidget()
        w_ac.setLayout(row_ac)
        color_layout.addRow("强调色：", w_ac)

        layout.addWidget(color_group)

        layout.addStretch()
        return widget

    def _open_we_import(self):
        """从本地壁纸文件夹（每个子文件夹=一个壁纸）选择壁纸，直接应用为整个程序窗口背景"""
        from widgets.wallpaper_import_dialog import WallpaperImportDialog, default_wallpaper_root

        def on_apply(path: str):
            # 壁纸作用于整个程序窗口：写入配置并立即生效（无需点保存）
            self.config.set("theme.chat_bg_image", path)
            w = self.parent()
            while w is not None and not hasattr(w, "apply_window_background"):
                w = w.parent()
            if w is not None:
                if hasattr(w.ai_panel, "apply_theme"):
                    w.ai_panel.apply_theme()
                if hasattr(w.video_panel, "reload_theme"):
                    w.video_panel.reload_theme()
                w.apply_window_background()
                w.apply_text_transparency()
                if hasattr(w, "status_label"):
                    w.status_label.setText("壁纸已应用")

        cfg = self.config.load()
        root = cfg.get("wallpaper", {}).get("root_dir") or default_wallpaper_root()

        def on_accepted():
            # 记住本次使用的壁纸根目录
            cur = self.config.get("wallpaper.root_dir", "")
            new_root = getattr(dlg_ref, "dir_edit", None)
            if new_root is not None:
                self.config.set("wallpaper.root_dir", new_root.text().strip() or cur)

        dlg_ref = WallpaperImportDialog(self, on_apply=on_apply, root_dir=root)
        dlg_ref.accepted.connect(on_accepted)
        dlg_ref.exec_()

    def _pick_color(self, line_edit: QLineEdit):
        from PyQt5.QtWidgets import QColorDialog
        from PyQt5.QtGui import QColor
        current = line_edit.text().strip()
        color = QColor(current) if current and current.startswith("#") else QColor("#007acc")
        result = QColorDialog.getColor(color, self, "选择颜色")
        if result.isValid():
            line_edit.setText(result.name())

    def _load_appearance_settings(self):
        cfg = self.config.load()
        theme_cfg = cfg.get("theme", {})
        self.text_opacity_spin.setValue(theme_cfg.get("text_opacity", 100))
        self.editor_color_edit.setText(theme_cfg.get("editor_bg_color", "#1e1e1e"))
        self.chat_color_edit.setText(theme_cfg.get("chat_bg_color", "#252526"))
        self.chat_text_color_edit.setText(theme_cfg.get("chat_text_color", "#cccccc"))
        self.ui_transparency_spin.setValue(theme_cfg.get("ui_transparency", 50))
        self.accent_color_edit.setText(theme_cfg.get("accent_color", "#007acc"))

    # ========== 通用设置标签页 ==========

    def _create_app_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        ui_group = QGroupBox("⚙️ 界面")
        ui_layout = QFormLayout(ui_group)
        ui_layout.setSpacing(10)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["深色主题", "浅色主题"])
        ui_layout.addRow("主题：", self.theme_combo)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(10, 20)
        self.font_size_spin.setValue(13)
        ui_layout.addRow("字体大小：", self.font_size_spin)

        self.show_welcome_check = QCheckBox("启动时显示欢迎页")
        self.show_welcome_check.setChecked(True)
        ui_layout.addRow("", self.show_welcome_check)

        layout.addWidget(ui_group)

        sys_group = QGroupBox("📊 系统监控")
        sys_layout = QVBoxLayout(sys_group)
        self.monitor_check = QCheckBox("显示系统资源占用（CPU、内存、GPU）")
        self.monitor_check.setChecked(True)
        sys_layout.addWidget(self.monitor_check)
        layout.addWidget(sys_group)

        chat_group = QGroupBox("💬 对话设置")
        chat_layout = QFormLayout(chat_group)
        chat_layout.setSpacing(10)

        self.memory_rounds_spin = QSpinBox()
        self.memory_rounds_spin.setRange(1, 100)
        self.memory_rounds_spin.setValue(10)
        self.memory_rounds_spin.setSuffix(" 轮")
        chat_layout.addRow("对话记忆轮数：", self.memory_rounds_spin)

        memory_tip = QLabel("数值越大，AI记得越久，但消耗的 token 也越多。\n建议 10-20 轮平衡效果和性能。")
        memory_tip.setStyleSheet("color: #666; font-size: 11px;")
        memory_tip.setWordWrap(True)
        chat_layout.addRow("", memory_tip)

        layout.addWidget(chat_group)

        layout.addStretch()

        return widget

    def _load_app_settings(self):
        cfg = self.config.load()
        theme = cfg.get("app", {}).get("theme", "dark")
        self.theme_combo.setCurrentIndex(0 if theme == "dark" else 1)
        self.font_size_spin.setValue(cfg.get("app", {}).get("font_size", 13))
        self.show_welcome_check.setChecked(cfg.get("app", {}).get("show_welcome", True))
        self.monitor_check.setChecked(cfg.get("system_monitor", {}).get("enabled", True))
        self.memory_rounds_spin.setValue(cfg.get("chat", {}).get("memory_rounds", 10))

    # ========== 保存 ==========

    def _on_save(self):
        # 同时保存正在编辑的模型配置（GPU层数/上下文大小等），
        # 避免用户点底部「保存」后模型参数被静默丢弃
        self._save_model_config(silent=True)

        cfg = self.config.load()

        # 外观主题设置
        if "theme" not in cfg:
            cfg["theme"] = {}
        # 背景壁纸(theme.chat_bg_image)由「导入Wallpaper Engine壁纸文件夹」直接写配置，此处不覆盖
        cfg["theme"]["text_opacity"] = self.text_opacity_spin.value()
        cfg["theme"]["ui_transparency"] = self.ui_transparency_spin.value()
        cfg["theme"]["editor_bg_color"] = self.editor_color_edit.text().strip()
        cfg["theme"]["chat_bg_color"] = self.chat_color_edit.text().strip()
        cfg["theme"]["chat_text_color"] = self.chat_text_color_edit.text().strip()
        cfg["theme"]["editor_bg_color"] = self.editor_color_edit.text().strip() or "#1e1e1e"
        cfg["theme"]["chat_bg_color"] = self.chat_color_edit.text().strip() or "#252526"
        cfg["theme"]["accent_color"] = self.accent_color_edit.text().strip() or "#007acc"

        # 服务设置
        cfg["llm"]["host"] = self.host_edit.text().strip() or "127.0.0.1"
        cfg["llm"]["port"] = self.port_spin.value()
        cfg["server"]["auto_start"] = self.auto_start_check.isChecked()
        cfg["server"]["llama_server_path"] = self.server_path_edit.text().strip()

        # 通用设置
        cfg["app"]["theme"] = "dark" if self.theme_combo.currentIndex() == 0 else "light"
        cfg["app"]["font_size"] = self.font_size_spin.value()
        cfg["app"]["show_welcome"] = self.show_welcome_check.isChecked()
        cfg["system_monitor"]["enabled"] = self.monitor_check.isChecked()

        # 对话设置
        if "chat" not in cfg:
            cfg["chat"] = {}
        cfg["chat"]["memory_rounds"] = self.memory_rounds_spin.value()

        if self.config.save(cfg):
            QMessageBox.information(self, "设置已保存", "设置已保存，部分设置需要重启后生效。")
            self.accept()
        else:
            QMessageBox.warning(self, "保存失败", "设置保存失败，请检查文件权限。")
