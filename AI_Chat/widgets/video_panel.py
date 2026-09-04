"""
视频生成面板 - 基于 ComfyUI API
"""
import os
import json
import tempfile
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QComboBox, QProgressBar, QFileDialog, QMessageBox,
    QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox, QLineEdit,
    QScrollArea, QFrame, QSizePolicy, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QSlider, QListWidget, QListWidgetItem,
    QSplitter, QTabWidget, QPlainTextEdit
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl, QSize
from PyQt5.QtGui import QPixmap, QFont, QIcon, QMovie
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget

from core.config import get_config_manager
from core.comfyui_client import ComfyUIClient, load_workflow_json, convert_ui_to_api, find_text_nodes
from widgets.animated_bg import AnimatedBackground


class GenerateThread(QThread):
    """视频生成线程"""
    progress = pyqtSignal(float, str)  # 进度 0-1, 状态文本
    finished_ok = pyqtSignal(dict)     # 生成完成，返回结果
    error = pyqtSignal(str)            # 出错

    def __init__(self, server_address: str, workflow: dict):
        super().__init__()
        self.server_address = server_address
        self.workflow = workflow
        self._interrupted = False

    def run(self):
        try:
            client = ComfyUIClient(self.server_address)
            
            def on_progress(pct, text):
                if self._interrupted:
                    client.interrupt()
                self.progress.emit(pct, text)
            
            result = client.generate_and_wait(
                self.workflow,
                progress_cb=on_progress,
                poll_interval=1.5,
            )
            self.finished_ok.emit(result)
        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        self._interrupted = True


class VideoPanel(QWidget):
    """视频生成面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = get_config_manager()
        self.gen_thread = None
        self.client = None
        self._last_output_dir = ""
        self._init_ui()
        self._load_settings()
        self._refresh_connection_status()

    def _init_ui(self):
        # 背景层
        self.bg_layer = AnimatedBackground(self)
        self.bg_layer.lower()

        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 内容容器（半透明，透出背景）
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 12)
        content_layout.setSpacing(10)

        # 顶部工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        title = QLabel("🎬 视频生成")
        title.setStyleSheet("""
            color: #e6edf3;
            font-size: 16px;
            font-weight: 600;
            font-family: "Microsoft YaHei";
        """)
        toolbar.addWidget(title)

        toolbar.addStretch()

        # 连接状态
        self.conn_label = QLabel("● 未连接")
        self.conn_label.setStyleSheet("color: #f85149; font-size: 12px;")
        toolbar.addWidget(self.conn_label)

        # 刷新连接
        btn_refresh = QPushButton("🔄")
        btn_refresh.setFixedSize(28, 28)
        btn_refresh.setToolTip("刷新连接状态")
        btn_refresh.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.1);
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 4px;
                color: #ccc;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.2);
            }
        """)
        btn_refresh.clicked.connect(self._refresh_connection_status)
        toolbar.addWidget(btn_refresh)

        # 设置按钮
        btn_settings = QPushButton("⚙")
        btn_settings.setFixedSize(28, 28)
        btn_settings.setToolTip("ComfyUI 设置")
        btn_settings.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.1);
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 4px;
                color: #ccc;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.2);
            }
        """)
        btn_settings.clicked.connect(self._open_settings)
        toolbar.addWidget(btn_settings)

        content_layout.addLayout(toolbar)

        # 分割器：左侧参数 + 右侧预览
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)

        # === 左侧：参数 + 指南 Tab ===
        left_tabs = QTabWidget()
        left_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background: transparent;
            }
            QTabBar::tab {
                background: rgba(255,255,255,0.05);
                color: #888;
                padding: 6px 16px;
                border: 1px solid rgba(255,255,255,0.1);
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
                font-size: 12px;
            }
            QTabBar::tab:selected {
                background: rgba(88, 166, 255, 0.15);
                color: #58a6ff;
                border: 1px solid rgba(88, 166, 255, 0.3);
                border-bottom: none;
            }
            QTabBar::tab:hover:!selected {
                color: #ccc;
                background: rgba(255,255,255,0.1);
            }
        """)

        # --- Tab 1: 参数 ---
        param_tab = QWidget()
        left_layout = QVBoxLayout(param_tab)
        left_layout.setContentsMargins(0, 8, 0, 0)
        left_layout.setSpacing(10)

        # 工作流选择
        wf_group = QGroupBox("工作流")
        wf_group.setStyleSheet("""
            QGroupBox {
                color: #e6edf3;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 12px;
                background: rgba(255,255,255,0.03);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                font-size: 12px;
            }
        """)
        wf_layout = QVBoxLayout(wf_group)
        wf_layout.setSpacing(6)

        wf_row = QHBoxLayout()
        self.workflow_combo = QComboBox()
        self.workflow_combo.setStyleSheet(self._combo_style())
        self.workflow_combo.currentIndexChanged.connect(self._on_workflow_changed)
        wf_row.addWidget(self.workflow_combo, 1)

        btn_load_wf = QPushButton("加载...")
        btn_load_wf.setFixedWidth(64)
        btn_load_wf.setStyleSheet(self._btn_secondary_style())
        btn_load_wf.clicked.connect(self._load_workflow_file)
        wf_row.addWidget(btn_load_wf)

        wf_layout.addLayout(wf_row)

        self.workflow_info = QLabel("请选择或加载工作流")
        self.workflow_info.setStyleSheet("color: #888; font-size: 11px;")
        self.workflow_info.setWordWrap(True)
        wf_layout.addWidget(self.workflow_info)

        left_layout.addWidget(wf_group)

        # 模型文件状态
        model_group = QGroupBox("模型文件")
        model_group.setStyleSheet("""
            QGroupBox {
                color: #e6edf3;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 12px;
                background: rgba(255,255,255,0.03);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                font-size: 12px;
            }
        """)
        model_layout = QVBoxLayout(model_group)
        model_layout.setSpacing(4)

        self.model_status_label = QLabel("检测中...")
        self.model_status_label.setStyleSheet("color: #888; font-size: 11px;")
        self.model_status_label.setWordWrap(True)
        model_layout.addWidget(self.model_status_label)

        # 4个模型的小状态行
        self.model_rows_widget = QWidget()
        self.model_rows_layout = QVBoxLayout(self.model_rows_widget)
        self.model_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.model_rows_layout.setSpacing(3)
        model_layout.addWidget(self.model_rows_widget)

        # 管理按钮
        model_btn_row = QHBoxLayout()
        model_btn_row.addStretch()
        self.manage_models_btn = QPushButton("管理模型 →")
        self.manage_models_btn.setStyleSheet(self._btn_secondary_style())
        self.manage_models_btn.setFixedHeight(26)
        self.manage_models_btn.clicked.connect(self._open_model_manager)
        model_btn_row.addWidget(self.manage_models_btn)
        model_layout.addLayout(model_btn_row)

        left_layout.addWidget(model_group)

        # 提示词输入
        prompt_group = QGroupBox("提示词 (Prompt)")
        prompt_group.setStyleSheet("""
            QGroupBox {
                color: #e6edf3;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 12px;
                background: rgba(255,255,255,0.03);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                font-size: 12px;
            }
        """)
        prompt_layout = QVBoxLayout(prompt_group)
        prompt_layout.setSpacing(6)

        # 提示词节点选择
        prompt_node_row = QHBoxLayout()
        prompt_node_row.addWidget(QLabel("目标节点:"))
        self.prompt_node_combo = QComboBox()
        self.prompt_node_combo.setStyleSheet(self._combo_style())
        prompt_node_row.addWidget(self.prompt_node_combo, 1)
        prompt_layout.addLayout(prompt_node_row)

        # 正向提示词
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText("输入提示词（建议使用英文）...\n例如：A beautiful sunset over the ocean, cinematic lighting, 4k")
        self.prompt_edit.setStyleSheet("""
            QTextEdit {
                background: rgba(0,0,0,0.3);
                color: #e6edf3;
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 4px;
                padding: 8px;
                font-size: 13px;
                font-family: "Microsoft YaHei";
            }
            QTextEdit:focus {
                border: 1px solid #58a6ff;
            }
        """)
        self.prompt_edit.setMinimumHeight(100)
        prompt_layout.addWidget(self.prompt_edit)

        left_layout.addWidget(prompt_group, 1)

        # 生成参数
        param_group = QGroupBox("生成参数")
        param_group.setStyleSheet("""
            QGroupBox {
                color: #e6edf3;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 12px;
                background: rgba(255,255,255,0.03);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                font-size: 12px;
            }
        """)
        param_form = QFormLayout(param_group)
        param_form.setSpacing(8)

        # 分辨率（宽高一行）
        res_row = QHBoxLayout()
        res_row.setSpacing(6)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(256, 2048)
        self.width_spin.setValue(768)
        self.width_spin.setSingleStep(64)
        self.width_spin.setStyleSheet(self._spin_style())
        self.height_spin = QSpinBox()
        self.height_spin.setRange(256, 2048)
        self.height_spin.setValue(432)
        self.height_spin.setSingleStep(64)
        self.height_spin.setStyleSheet(self._spin_style())
        res_row.addWidget(self.width_spin, 1)
        res_row.addWidget(QLabel("×"))
        res_row.addWidget(self.height_spin, 1)
        res_widget = QWidget()
        res_widget.setLayout(res_row)
        param_form.addRow("分辨率:", res_widget)

        # 时长
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 100000)
        self.duration_spin.setValue(5)
        self.duration_spin.setSuffix(" 秒")
        self.duration_spin.setStyleSheet(self._spin_style())
        param_form.addRow("时长:", self.duration_spin)

        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(1, 200)
        self.steps_spin.setValue(20)
        self.steps_spin.setStyleSheet(self._spin_style())
        param_form.addRow("步数:", self.steps_spin)

        self.cfg_spin = QDoubleSpinBox()
        self.cfg_spin.setRange(1.0, 20.0)
        self.cfg_spin.setValue(7.0)
        self.cfg_spin.setSingleStep(0.5)
        self.cfg_spin.setStyleSheet(self._spin_style())
        param_form.addRow("CFG:", self.cfg_spin)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(8, 60)
        self.fps_spin.setValue(24)
        self.fps_spin.setStyleSheet(self._spin_style())
        param_form.addRow("帧率:", self.fps_spin)

        left_layout.addWidget(param_group)
        left_layout.addStretch()

        left_tabs.addTab(param_tab, "⚙️ 参数")

        # --- Tab 2: 使用指南 ---
        guide_tab = QWidget()
        guide_layout = QVBoxLayout(guide_tab)
        guide_layout.setContentsMargins(0, 8, 0, 0)
        guide_layout.setSpacing(8)

        guide_scroll = QScrollArea()
        guide_scroll.setWidgetResizable(True)
        guide_scroll.setFrameShape(QFrame.NoFrame)
        guide_scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.2);
                border-radius: 4px;
                min-height: 30px;
            }
        """)

        guide_content = QWidget()
        guide_content_layout = QVBoxLayout(guide_content)
        guide_content_layout.setContentsMargins(4, 4, 4, 4)
        guide_content_layout.setSpacing(12)

        # 指南内容
        guide_html = self._get_guide_html()
        guide_label = QLabel(guide_html)
        guide_label.setTextFormat(Qt.RichText)
        guide_label.setWordWrap(True)
        guide_label.setStyleSheet("""
            QLabel {
                color: #ccc;
                font-size: 12px;
                font-family: "Microsoft YaHei";
                line-height: 1.6;
            }
        """)
        guide_label.setOpenExternalLinks(True)
        guide_content_layout.addWidget(guide_label)
        guide_content_layout.addStretch()

        guide_scroll.setWidget(guide_content)
        guide_layout.addWidget(guide_scroll)

        left_tabs.addTab(guide_tab, "📖 使用指南")

        splitter.addWidget(left_tabs)

        # === 右侧：预览区 ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        # 视频预览
        preview_group = QGroupBox("预览")
        preview_group.setStyleSheet("""
            QGroupBox {
                color: #e6edf3;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 12px;
                background: rgba(255,255,255,0.03);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                font-size: 12px;
            }
        """)
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setSpacing(6)

        # 视频显示区域
        self.video_container = QFrame()
        self.video_container.setMinimumHeight(280)
        self.video_container.setStyleSheet("""
            QFrame {
                background: rgba(0,0,0,0.5);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 4px;
            }
        """)
        video_layout = QVBoxLayout(self.video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)

        # 视频播放器
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background: black; border-radius: 4px;")
        self.media_player = QMediaPlayer()
        self.media_player.setVideoOutput(self.video_widget)
        video_layout.addWidget(self.video_widget)

        # 占位文字
        self.preview_placeholder = QLabel("🎬\n\n视频预览区\n生成完成后显示结果")
        self.preview_placeholder.setAlignment(Qt.AlignCenter)
        self.preview_placeholder.setStyleSheet("color: #666; font-size: 14px;")
        video_layout.addWidget(self.preview_placeholder)

        preview_layout.addWidget(self.video_container, 1)

        # 播放控制
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(6)

        self.btn_play = QPushButton("▶ 播放")
        self.btn_play.setStyleSheet(self._btn_secondary_style())
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_play.setEnabled(False)
        ctrl_row.addWidget(self.btn_play)

        self.btn_save = QPushButton("💾 保存")
        self.btn_save.setStyleSheet(self._btn_secondary_style())
        self.btn_save.clicked.connect(self._save_video)
        self.btn_save.setEnabled(False)
        ctrl_row.addWidget(self.btn_save)

        ctrl_row.addStretch()

        self.file_label = QLabel("")
        self.file_label.setStyleSheet("color: #888; font-size: 11px;")
        ctrl_row.addWidget(self.file_label)

        preview_layout.addLayout(ctrl_row)

        right_layout.addWidget(preview_group, 1)

        # 历史记录
        hist_group = QGroupBox("生成历史")
        hist_group.setStyleSheet("""
            QGroupBox {
                color: #e6edf3;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 12px;
                background: rgba(255,255,255,0.03);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                font-size: 12px;
            }
        """)
        hist_layout = QVBoxLayout(hist_group)
        hist_layout.setSpacing(4)

        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(100)
        self.history_list.setStyleSheet("""
            QListWidget {
                background: rgba(0,0,0,0.2);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 4px;
                color: #ccc;
                font-size: 11px;
            }
            QListWidget::item {
                padding: 4px 8px;
            }
            QListWidget::item:selected {
                background: rgba(88, 166, 255, 0.3);
            }
        """)
        self.history_list.itemDoubleClicked.connect(self._load_history_item)
        hist_layout.addWidget(self.history_list)

        right_layout.addWidget(hist_group)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([320, 500])

        content_layout.addWidget(splitter, 1)

        # 底部：进度 + 生成按钮
        bottom = QWidget()
        bottom.setStyleSheet("""
            background: rgba(0, 0, 0, 0.4);
            border-top: 1px solid rgba(255,255,255,0.08);
        """)
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 10, 16, 12)
        bottom_layout.setSpacing(8)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("就绪")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 4px;
                background: rgba(0,0,0,0.3);
                text-align: center;
                color: #ccc;
                height: 20px;
                font-size: 11px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #58a6ff, stop:1 #f0883e);
                border-radius: 3px;
            }
        """)
        bottom_layout.addWidget(self.progress_bar)

        # 生成按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_generate = QPushButton("🎬 生成视频")
        self.btn_generate.setMinimumHeight(36)
        self.btn_generate.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #58a6ff, stop:1 #f0883e);
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: 600;
                padding: 0 24px;
            }
            QPushButton:hover {
                opacity: 0.9;
            }
            QPushButton:disabled {
                background: #444;
                color: #888;
            }
        """)
        self.btn_generate.clicked.connect(self._start_generate)
        btn_row.addWidget(self.btn_generate)

        self.btn_stop = QPushButton("⏹ 停止")
        self.btn_stop.setMinimumHeight(36)
        self.btn_stop.setFixedWidth(80)
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background: rgba(248, 81, 73, 0.2);
                color: #f85149;
                border: 1px solid rgba(248, 81, 73, 0.4);
                border-radius: 6px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(248, 81, 73, 0.3);
            }
            QPushButton:disabled {
                color: #666;
                border-color: #444;
                background: transparent;
            }
        """)
        self.btn_stop.clicked.connect(self._stop_generate)
        self.btn_stop.setEnabled(False)
        btn_row.addWidget(self.btn_stop)

        btn_row.addStretch()

        bottom_layout.addLayout(btn_row)

        content_layout.addWidget(bottom)

        main_layout.addWidget(content)

        # 存储当前工作流
        self._current_workflow_api = None  # API 格式工作流
        self._current_workflow_path = ""
        self._current_video_path = ""

    def _combo_style(self):
        return """
            QComboBox {
                background: rgba(0,0,0,0.3);
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 4px;
                padding: 4px 8px;
                color: #e6edf3;
                font-size: 12px;
                min-height: 20px;
            }
            QComboBox:hover {
                border: 1px solid rgba(88, 166, 255, 0.5);
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #888;
            }
            QComboBox QAbstractItemView {
                background: #1e1e1e;
                border: 1px solid #333;
                color: #e6edf3;
                selection-background-color: #007acc;
            }
        """

    def _btn_secondary_style(self):
        return """
            QPushButton {
                background: rgba(255,255,255,0.08);
                color: #ccc;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.15);
                border: 1px solid rgba(88, 166, 255, 0.4);
            }
            QPushButton:disabled {
                color: #666;
                border-color: #333;
            }
        """

    def _spin_style(self):
        return """
            QSpinBox, QDoubleSpinBox {
                background: rgba(0,0,0,0.3);
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 4px;
                padding: 4px 8px;
                color: #e6edf3;
                font-size: 12px;
            }
            QSpinBox:hover, QDoubleSpinBox:hover {
                border: 1px solid rgba(88, 166, 255, 0.5);
            }
        """

    def _load_settings(self):
        """加载设置"""
        theme_cfg = self.cfg.get("theme", {})
        comfy_cfg = self.cfg.get("comfyui", {})

        # 背景
        bg_image = theme_cfg.get("chat_bg_image", "")
        bg_color = theme_cfg.get("chat_bg_color", "#252526")
        self.bg_layer.set_background(bg_image, bg_color, 1.0)  # 壁纸始终不透明

        # ComfyUI 地址
        server_addr = comfy_cfg.get("server_address", "127.0.0.1:8188")
        self._server_address = server_addr
        self.client = ComfyUIClient(server_addr)

        # 已保存的工作流
        workflows = comfy_cfg.get("workflows", [])
        self.workflow_combo.clear()
        for wf in workflows:
            self.workflow_combo.addItem(wf.get("name", "未命名"), wf.get("id", ""))

        # 默认工作流
        default_wf = comfy_cfg.get("last_workflow", "")
        if default_wf:
            for i in range(self.workflow_combo.count()):
                if self.workflow_combo.itemData(i) == default_wf:
                    self.workflow_combo.setCurrentIndex(i)
                    break

        # 默认视频参数
        self.width_spin.setValue(comfy_cfg.get("default_width", 768))
        self.height_spin.setValue(comfy_cfg.get("default_height", 432))
        self.duration_spin.setValue(comfy_cfg.get("default_duration", 5))
        self.fps_spin.setValue(comfy_cfg.get("default_fps", 24))
        self.steps_spin.setValue(comfy_cfg.get("default_steps", 20))
        self.cfg_spin.setValue(comfy_cfg.get("default_cfg", 7.0))

        # 自动加载当前工作流数据
        if self.workflow_combo.count() > 0:
            idx = self.workflow_combo.currentIndex()
            wf_id = self.workflow_combo.itemData(idx)
            api_wf, name = self._get_workflow_data(wf_id)
            if api_wf:
                self._current_workflow_api = api_wf
                self._current_workflow_path = name
                self._populate_prompt_nodes()

        # 刷新模型状态
        self._refresh_model_status()

    def _refresh_connection_status(self):
        """刷新连接状态"""
        if not self.client:
            return
        ok = self.client.check_connection()
        if ok:
            self.conn_label.setText("● 已连接")
            self.conn_label.setStyleSheet("color: #3fb950; font-size: 12px;")
            self.btn_generate.setEnabled(True)
        else:
            self.conn_label.setText("● 未连接")
            self.conn_label.setStyleSheet("color: #f85149; font-size: 12px;")
            # 未连接也允许生成（可能用户还没启动 ComfyUI）
            self.btn_generate.setEnabled(True)

    def _refresh_model_status(self):
        """刷新模型文件状态显示"""
        comfy_cfg = self.cfg.get("comfyui", {})
        download_folder = comfy_cfg.get("download_folder", "")
        model_source = comfy_cfg.get("model_source", "Sulphur 2")

        # 清空现有行
        while self.model_rows_layout.count() > 0:
            item = self.model_rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not download_folder or not os.path.isdir(download_folder):
            self.model_status_label.setText("⚠️ 未设置下载文件夹")
            self.model_status_label.setStyleSheet("color: #dcdcaa; font-size: 11px;")
            return

        from core.model_manager import check_models
        models = check_models(download_folder, model_source)
        total = len(models)
        ready = sum(1 for m in models if m["exists"])

        if ready == total:
            self.model_status_label.setText(f"✅ 全部就绪 ({ready}/{total})")
            self.model_status_label.setStyleSheet("color: #3fb950; font-size: 11px;")
        else:
            self.model_status_label.setText(f"⚠️ {ready}/{total} 个就绪")
            self.model_status_label.setStyleSheet("color: #dcdcaa; font-size: 11px;")

        # 显示每个模型的小状态行
        for m in models:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)

            icon = QLabel("✅" if m["exists"] else "❌")
            icon.setFixedWidth(20)
            icon.setStyleSheet("font-size: 10px;")

            name = QLabel(m["name"])
            name.setStyleSheet("color: #aaa; font-size: 10px;")
            name.setWordWrap(True)

            row.addWidget(icon)
            row.addWidget(name, 1)

            w = QWidget()
            w.setLayout(row)
            self.model_rows_layout.addWidget(w)

    def _open_model_manager(self):
        """打开设置向导并直接跳到模型管理（第2步）"""
        from widgets.setup_wizard import SetupWizard
        wizard = SetupWizard(self)
        # 直接跳到第 2 步（模型文件）
        wizard.current_step = 1
        wizard._update_step_ui()
        if wizard.exec_() == QDialog.Accepted:
            self._load_settings()
            self._refresh_connection_status()
            self._refresh_model_status()
            self._populate_prompt_nodes()

    def _open_settings(self):
        """打开设置向导"""
        from widgets.setup_wizard import SetupWizard
        wizard = SetupWizard(self)
        if wizard.exec_() == QDialog.Accepted:
            # 重新加载设置
            self._load_settings()
            self._refresh_connection_status()
            self._refresh_model_status()
            self._populate_prompt_nodes()

    def _load_workflow_file(self):
        """加载工作流 JSON 文件"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "选择工作流文件", "",
            "ComfyUI 工作流 (*.json);;所有文件 (*.*)"
        )
        if not filepath:
            return

        try:
            ui_wf = load_workflow_json(filepath)
            
            # 检查格式
            if "prompt" in ui_wf and isinstance(ui_wf["prompt"], dict):
                # 已经是 API 格式
                api_wf = ui_wf["prompt"]
                is_api_format = True
            elif "nodes" in ui_wf:
                # UI 格式，尝试转换
                api_wf = convert_ui_to_api(ui_wf)
                is_api_format = False
            else:
                # 可能直接是 API 格式（字典结构）
                api_wf = ui_wf
                is_api_format = True

            self._current_workflow_api = api_wf
            self._current_workflow_path = filepath

            # 添加到下拉列表（兼容旧格式，保存路径）
            wf_name = os.path.basename(filepath)
            self.workflow_combo.addItem(wf_name, filepath)
            self.workflow_combo.setCurrentIndex(self.workflow_combo.count() - 1)

            # 保存到配置
            comfy_cfg = self.cfg.get("comfyui", {})
            workflows = comfy_cfg.get("workflows", [])
            if not any(w.get("path") == filepath for w in workflows):
                workflows.append({"name": wf_name, "path": filepath})
            comfy_cfg["workflows"] = workflows
            comfy_cfg["last_workflow"] = filepath
            self.cfg.set("comfyui", comfy_cfg)
            self.cfg.save()

            # 查找文本节点
            text_nodes = find_text_nodes(api_wf)
            self.prompt_node_combo.clear()
            for nid in text_nodes:
                node = api_wf.get(nid, {})
                ctype = node.get("class_type", nid)
                self.prompt_node_combo.addItem(f"{nid}: {ctype}", nid)

            # 更新信息
            node_count = len(api_wf)
            fmt = "API 格式" if is_api_format else "UI 格式（已转换）"
            self.workflow_info.setText(f"{node_count} 个节点 · {fmt}\n{os.path.basename(filepath)}")

            if not text_nodes:
                self.workflow_info.setText(
                    self.workflow_info.text() + 
                    "\n⚠️ 未找到文本输入节点，请手动配置"
                )

        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"加载工作流失败：\n{str(e)}")

    def _get_workflow_data(self, wf_id_or_path: str):
        """
        根据工作流 ID 或路径获取 API 格式数据
        返回 (api_wf_dict, display_name) 或 (None, "")
        """
        comfy_cfg = self.cfg.get("comfyui", {})
        workflows = comfy_cfg.get("workflows", [])

        # 先按 id 查找（新格式，内嵌数据）
        for wf in workflows:
            if wf.get("id") == wf_id_or_path and wf.get("data"):
                return wf["data"], wf.get("name", "未命名")

        # 再按 path 查找（旧格式，从文件加载）
        for wf in workflows:
            if wf.get("path") == wf_id_or_path and os.path.exists(wf["path"]):
                try:
                    ui_wf = load_workflow_json(wf["path"])
                    if "prompt" in ui_wf and isinstance(ui_wf["prompt"], dict):
                        return ui_wf["prompt"], wf.get("name", os.path.basename(wf["path"]))
                    elif "nodes" in ui_wf:
                        return convert_ui_to_api(ui_wf), wf.get("name", os.path.basename(wf["path"]))
                    else:
                        return ui_wf, wf.get("name", os.path.basename(wf["path"]))
                except Exception:
                    pass

        # 如果直接是文件路径
        if os.path.exists(wf_id_or_path):
            try:
                ui_wf = load_workflow_json(wf_id_or_path)
                if "prompt" in ui_wf and isinstance(ui_wf["prompt"], dict):
                    return ui_wf["prompt"], os.path.basename(wf_id_or_path)
                elif "nodes" in ui_wf:
                    return convert_ui_to_api(ui_wf), os.path.basename(wf_id_or_path)
                else:
                    return ui_wf, os.path.basename(wf_id_or_path)
            except Exception:
                pass

        return None, ""

    def _populate_prompt_nodes(self):
        """填充提示词节点下拉框"""
        if not self._current_workflow_api:
            return
        text_nodes = find_text_nodes(self._current_workflow_api)
        self.prompt_node_combo.clear()
        for nid in text_nodes:
            node = self._current_workflow_api.get(nid, {})
            ctype = node.get("class_type", nid)
            self.prompt_node_combo.addItem(f"{nid}: {ctype}", nid)

    def _on_workflow_changed(self, index):
        """工作流切换"""
        if index < 0:
            return
        wf_id = self.workflow_combo.itemData(index)
        if not wf_id:
            return

        api_wf, name = self._get_workflow_data(wf_id)
        if api_wf:
            self._current_workflow_api = api_wf
            self._current_workflow_path = name

            # 更新文本节点列表
            self._populate_prompt_nodes()

            # 更新信息
            node_count = len(api_wf)
            self.workflow_info.setText(f"{node_count} 个节点\n{name}")

            if self.prompt_node_combo.count() == 0:
                self.workflow_info.setText(
                    self.workflow_info.text() + 
                    "\n⚠️ 未找到文本输入节点"
                )

            # 保存最近使用
            comfy_cfg = self.cfg.get("comfyui", {})
            comfy_cfg["last_workflow"] = wf_id
            self.cfg.set("comfyui", comfy_cfg)
            self.cfg.save()

    def _start_generate(self):
        """开始生成视频"""
        if not self._current_workflow_api:
            QMessageBox.warning(self, "提示", "请先加载工作流文件")
            return

        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "提示", "请输入提示词")
            return

        # 检查连接
        if not self.client.check_connection():
            ret = QMessageBox.question(
                self, "连接失败",
                "无法连接到 ComfyUI 服务器，是否仍然提交？\n\n"
                "请确保 ComfyUI 已启动并运行在正确的地址。",
                QMessageBox.Yes | QMessageBox.No
            )
            if ret != QMessageBox.Yes:
                return

        # 构建工作流副本并修改提示词
        import copy
        workflow = copy.deepcopy(self._current_workflow_api)

        # 修改目标节点的提示词
        target_node_id = self.prompt_node_combo.currentData()
        if target_node_id and target_node_id in workflow:
            node = workflow[target_node_id]
            # 尝试设置文本 - 不同节点类型有不同的输入名
            if "text" in node.get("inputs", {}):
                node["inputs"]["text"] = prompt
            elif "prompt" in node.get("inputs", {}):
                node["inputs"]["prompt"] = prompt
            else:
                # 尝试用 widget 值
                wv = node.get("_widgets_values", [])
                if wv and isinstance(wv[0], str):
                    wv[0] = prompt
                    node["_widgets_values"] = wv

        # 开始生成
        self._set_generating(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("准备中...")

        self.gen_thread = GenerateThread(self._server_address, workflow)
        self.gen_thread.progress.connect(self._on_progress)
        self.gen_thread.finished_ok.connect(self._on_generate_finished)
        self.gen_thread.error.connect(self._on_generate_error)
        self.gen_thread.start()

    def _stop_generate(self):
        """停止生成"""
        if self.gen_thread and self.gen_thread.isRunning():
            self.gen_thread.stop()
            self.progress_bar.setFormat("正在停止...")

    def _set_generating(self, generating: bool):
        self.btn_generate.setEnabled(not generating)
        self.btn_stop.setEnabled(generating)
        self.prompt_edit.setEnabled(not generating)
        self.workflow_combo.setEnabled(not generating)

    def _on_progress(self, pct: float, text: str):
        """进度更新"""
        self.progress_bar.setValue(int(pct * 100))
        self.progress_bar.setFormat(text)

    def _on_generate_finished(self, result: dict):
        """生成完成"""
        self._set_generating(False)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("生成完成！")

        videos = result.get("videos", [])
        images = result.get("images", [])

        if not videos and not images:
            QMessageBox.information(self, "完成", "生成完成，但未找到输出文件。\n请检查 ComfyUI 输出目录。")
            return

        # 下载第一个视频/图片
        first = videos[0] if videos else images[0]
        filename = first["filename"]
        subfolder = first.get("subfolder", "")
        ftype = first.get("type", "output")

        data = self.client.get_image(filename, subfolder, ftype)
        if not data:
            QMessageBox.warning(self, "下载失败", "无法下载生成的文件")
            return

        # 保存到临时文件
        tmp_dir = tempfile.gettempdir()
        out_path = os.path.join(tmp_dir, f"codemate_{filename}")
        with open(out_path, 'wb') as f:
            f.write(data)

        self._current_video_path = out_path
        self.file_label.setText(filename)

        # 播放视频
        if videos:
            self.preview_placeholder.setVisible(False)
            self.video_widget.setVisible(True)
            self.media_player.setMedia(QMediaContent(QUrl.fromLocalFile(out_path)))
            self.media_player.play()
            self.btn_play.setText("⏸ 暂停")
            self.btn_play.setEnabled(True)
        else:
            # 图片
            self.preview_placeholder.setVisible(False)
            pixmap = QPixmap(out_path)
            self.preview_placeholder.setPixmap(pixmap.scaled(
                self.video_container.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

        self.btn_save.setEnabled(True)

        # 添加到历史
        item = QListWidgetItem(filename)
        item.setData(Qt.UserRole, out_path)
        self.history_list.insertItem(0, item)

    def _on_generate_error(self, error_msg: str):
        """生成出错"""
        self._set_generating(False)
        self.progress_bar.setFormat("出错")
        QMessageBox.critical(self, "生成失败", f"生成过程中出错：\n{error_msg}")

    def _toggle_play(self):
        """播放/暂停切换"""
        if self.media_player.state() == QMediaPlayer.PlayingState:
            self.media_player.pause()
            self.btn_play.setText("▶ 播放")
        else:
            self.media_player.play()
            self.btn_play.setText("⏸ 暂停")

    def _save_video(self):
        """保存视频"""
        if not self._current_video_path:
            return

        default_name = os.path.basename(self._current_video_path)
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存视频", default_name,
            "视频文件 (*.mp4 *.webm *.avi);;图片文件 (*.png *.jpg *.gif);;所有文件 (*.*)"
        )
        if save_path:
            import shutil
            shutil.copy2(self._current_video_path, save_path)
            QMessageBox.information(self, "保存成功", f"已保存到：\n{save_path}")

    def _load_history_item(self, item):
        """加载历史记录项"""
        path = item.data(Qt.UserRole)
        if path and os.path.exists(path):
            self._current_video_path = path
            self.media_player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
            self.media_player.play()
            self.btn_play.setText("⏸ 暂停")
            self.btn_play.setEnabled(True)
            self.btn_save.setEnabled(True)
            self.file_label.setText(os.path.basename(path))

    def update_theme(self):
        """更新主题"""
        theme_cfg = self.cfg.get("theme", {})
        bg_image = theme_cfg.get("chat_bg_image", "")
        bg_color = theme_cfg.get("chat_bg_color", "#252526")
        self.bg_layer.set_background(bg_image, bg_color, 1.0)  # 壁纸始终不透明

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.bg_layer.resize(self.size())

    def _get_guide_html(self) -> str:
        """获取使用指南 HTML"""
        return """
<style>
body { color: #ccc; font-size: 12px; line-height: 1.7; }
h2 { color: #58a6ff; font-size: 14px; margin: 16px 0 8px; padding-bottom: 4px; border-bottom: 1px solid rgba(88,166,255,0.3); }
h3 { color: #f0883e; font-size: 13px; margin: 12px 0 6px; }
.step-num { display: inline-block; width: 20px; height: 20px; background: linear-gradient(135deg, #58a6ff, #f0883e); color: white; border-radius: 50%; text-align: center; font-weight: bold; font-size: 11px; margin-right: 6px; line-height: 20px; }
.warn { background: rgba(210,153,34,0.1); border-left: 3px solid #d29922; padding: 8px 10px; margin: 8px 0; border-radius: 0 4px 4px 0; }
.tip { background: rgba(63,185,80,0.1); border-left: 3px solid #3fb950; padding: 8px 10px; margin: 8px 0; border-radius: 0 4px 4px 0; }
.info { background: rgba(88,166,255,0.1); border-left: 3px solid #58a6ff; padding: 8px 10px; margin: 8px 0; border-radius: 0 4px 4px 0; }
code { background: rgba(0,0,0,0.3); padding: 2px 5px; border-radius: 3px; font-family: Consolas, monospace; font-size: 11px; color: #f0883e; }
pre { background: rgba(0,0,0,0.3); padding: 8px 10px; border-radius: 4px; font-family: Consolas, monospace; font-size: 11px; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 11px; }
th { background: rgba(88,166,255,0.15); color: #58a6ff; text-align: left; padding: 6px 8px; border: 1px solid rgba(255,255,255,0.1); }
td { padding: 5px 8px; border: 1px solid rgba(255,255,255,0.1); }
a { color: #58a6ff; text-decoration: none; }
a:hover { text-decoration: underline; }
ul, ol { padding-left: 20px; margin: 6px 0; }
li { margin: 3px 0; }
</style>

<h2>🎬 视频生成使用指南</h2>

<p>本功能通过 <b>ComfyUI</b> API 驱动视频生成模型。<br>
支持 LTX、Sulphur 2 等基于 DiT 的视频生成模型。<br>
请先完成下面的准备工作。</p>

<h2>📋 前置准备（共 4 步）</h2>

<h3><span class="step-num">1</span>安装 ComfyUI</h3>
<p>ComfyUI 是视频生成的后端引擎，必须先安装并启动。</p>

<div class="info">
<b>推荐下载 ComfyUI 便携版：</b><br>
• 官方下载：<a href="https://comfy.org/">comfy.org</a><br>
• 选择 Windows 便携版（Portable）
</div>

<p>下载后解压到任意目录，例如：<br><code>D:\\ComfyUI</code></p>

<h3><span class="step-num">2</span>安装 ComfyUI-GGUF 插件</h3>
<p>GGUF 格式模型需要此插件才能加载。</p>

<p><b>方式 A：管理器安装（推荐）</b></p>
<ol>
<li>启动 ComfyUI</li>
<li>点击右侧「Manager」按钮</li>
<li>搜索 <code>ComfyUI-GGUF</code></li>
<li>点击 Install 安装</li>
<li>重启 ComfyUI</li>
</ol>

<p><b>方式 B：手动安装</b></p>
<pre>cd ComfyUI/custom_nodes
git clone https://github.com/city96/ComfyUI-GGUF.git</pre>

<h3><span class="step-num">3</span>放置模型文件</h3>
<p>将 <b>视频模型文件夹</b>（如 <code>Sulphur 2</code> 或 <code>LTX 2.3</code>）中的模型文件复制到 ComfyUI 对应目录：</p>

<table>
<tr><th>源文件</th><th>目标目录</th></tr>
<tr>
<td><code>10Eros_v1.5-Q4_K_S.gguf</code></td>
<td><code>ComfyUI/models/diffusion_models/</code></td>
</tr>
<tr>
<td><code>INT8 diffusion_models/*.safetensors</code></td>
<td><code>ComfyUI/models/diffusion_models/</code></td>
</tr>
<tr>
<td><code>text_encoders/*.safetensors</code></td>
<td><code>ComfyUI/models/text_encoders/</code></td>
</tr>
</table>

<div class="warn">
<b>⚠️ 注意：</b>不同工作流可能需要的模型路径不同。<br>
如果加载工作流后提示找不到模型，请检查节点中的模型文件名是否与实际文件一致。
</div>

<h3><span class="step-num">4</span>启动 ComfyUI</h3>
<p>运行 ComfyUI 目录下的：<br><code>run_nvidia_gpu.bat</code>（N 卡用户）</p>

<p>启动后浏览器会自动打开 <code>http://127.0.0.1:8188</code>，<br>
保持 ComfyUI 运行，然后回到 A Small Local AI Runner。</p>

<h2>🚀 A Small Local AI Runner 操作步骤</h2>

<h3><span class="step-num">1</span>确认连接</h3>
<p>点击右上角 🔄 按钮刷新连接状态。<br>
显示 <span style="color:#3fb950"><b>● 已连接</b></span> 说明 ComfyUI 运行正常。</p>

<div class="warn">
如果显示未连接：<br>
• 确认 ComfyUI 已启动<br>
• 确认端口是 8188（可点击 ⚙ 修改地址）<br>
• 确认没有防火墙阻止
</div>

<h3><span class="step-num">2</span>加载工作流</h3>
<p>点击「加载...」按钮，选择 ComfyUI 工作流 JSON 文件。</p>

<div class="tip">
<b>💡 推荐工作流：</b><br>
你可以在 ComfyUI 中搭建好工作流，然后用「Save」导出 JSON 文件给 A Small Local AI Runner 使用。
</div>

<p>工作流会自动保存到下拉列表中，下次直接选择即可。</p>

<h3><span class="step-num">3</span>选择提示词节点</h3>
<p>在「目标节点」下拉中选择要修改提示词的节点。</p>

<div class="info">
<b>找不到文本节点？</b><br>
某些模板化工作流（如 LTX 官方模板）的节点被封装了，A Small Local AI Runner 可能无法识别提示词节点。<br><br>
<b>解决方法：</b>在 ComfyUI 中把模板节点展开（Convert to regular nodes），导出标准工作流后再加载。
</div>

<h3><span class="step-num">4</span>输入提示词并生成</h3>
<p>在提示词输入框中输入描述，点击「🎬 生成视频」。</p>

<div class="tip">
<b>💡 提示词建议：</b><br>
• 使用<b>英文</b>提示词效果更好<br>
• 包含：主体 + 动作 + 环境 + 风格 + 镜头<br>
• 例如：<code>A beautiful sunset over the ocean, cinematic lighting, slow motion, 4k</code>
</div>

<h3><span class="step-num">5</span>查看和保存结果</h3>
<p>生成完成后会自动播放视频。<br>
点击「💾 保存」可以导出到指定位置。</p>

<h2>📊 显存需求参考</h2>
<table>
<tr><th>显存</th><th>可行度</th><th>建议设置</th></tr>
<tr><td>8 GB</td><td style="color:#f85149">勉强</td><td>低分辨率 + GGUF Q4</td></tr>
<tr><td>12 GB</td><td style="color:#f0883e">可行</td><td>768×512, 5-7秒</td></tr>
<tr><td>16 GB</td><td style="color:#58a6ff">良好</td><td>768×512, 10-15秒</td></tr>
<tr><td>24 GB+</td><td style="color:#3fb950">流畅</td><td>1024×768, 15-20秒</td></tr>
</table>

<h2>❓ 常见问题</h2>

<h3>Q: 为什么不直接用 llama.cpp 跑视频模型？</h3>
<p>这个 GGUF 文件是<b>视频扩散模型</b>，不是文本对话模型（LLM）。它的张量结构与 LLM 不同，llama.cpp 的 LLM 引擎加载不了（会报 "tensor name is too long" 错误）。</p>

<h3>Q: 生成速度慢怎么办？</h3>
<ul>
<li>降低分辨率和帧数</li>
<li>使用 GGUF 量化版本</li>
<li>减少步数（Steps）</li>
<li>确认使用了 GPU 加速</li>
</ul>

<h3>Q: 可以生成多长的视频？</h3>
<p>LTX / Sulphur 2 系列模型支持最长约 10-20 秒视频（24fps）。实际长度取决于显存大小和模型版本，8GB 显存可能只能生成 3-5 秒。</p>

<h3>Q: 支持中文提示词吗？</h3>
<p>文本编码器支持多语言，但视频生成模型在英文数据上训练更多，<b>建议使用英文提示词</b>以获得更好效果。</p>

<h2>🔗 相关链接</h2>
<ul>
<li><a href="https://comfy.org/">ComfyUI 官网</a></li>
<li><a href="https://huggingface.co/vantagewithai/LTX2.3-10Eros-1.5-GGUF">模型 HuggingFace 页面</a></li>
<li><a href="https://docs.ltx.video/">LTX-Video 官方文档</a></li>
</ul>
"""


def _quick_input(parent, title: str, label: str, default: str = "") -> tuple:
    """简单的输入对话框"""
    from PyQt5.QtWidgets import QInputDialog
    text, ok = QInputDialog.getText(parent, title, label, text=default)
    return text, ok
