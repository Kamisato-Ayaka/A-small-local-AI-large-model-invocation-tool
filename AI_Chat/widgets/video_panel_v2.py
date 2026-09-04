"""
视频生成面板 v2 - 重新设计布局
左侧：系统监控 + 视频参数
中间：视频预览 + 历史记录
底部：模型选择 + 提示词 + 生成按钮
"""
import os
import json
import tempfile
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QComboBox, QProgressBar, QFileDialog, QMessageBox,
    QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox, QLineEdit,
    QScrollArea, QFrame, QSizePolicy, QListWidget, QListWidgetItem,
    QSplitter, QInputDialog, QDialog, QApplication
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl, QEvent
from PyQt5.QtGui import QPixmap, QFont, QIcon, QMovie
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget

from core.config import get_config_manager
from core.comfyui_client import ComfyUIClient, load_workflow_json, convert_ui_to_api, find_text_nodes
from widgets.animated_bg import AnimatedBackground
from widgets.video_setup_wizard import VideoSetupWizard


class GenerateThread(QThread):
    """视频生成线程"""
    progress = pyqtSignal(float, str)
    finished_ok = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, server_address: str, workflow: dict, image_path: str = "", image_node_id=None):
        super().__init__()
        self.server_address = server_address
        self.workflow = workflow
        self.image_path = image_path  # 图生视频：待上传的首帧图片
        self.image_node_id = image_node_id  # 图生视频：指定注入的 LoadImage 节点（None=全部）
        self._interrupted = False

    def run(self):
        try:
            client = ComfyUIClient(self.server_address)

            # 图生视频：先上传图片并注入指定的 LoadImage 节点
            if self.image_path:
                self.progress.emit(0.0, "上传输入图片...")
                image_ref = client.upload_image(self.image_path)
                n = client.inject_load_image(self.workflow, image_ref, self.image_node_id)
                if n == 0:
                    raise RuntimeError("工作流中没有找到加载图像(LoadImage)节点，"
                                       "请确认导入的是 LTX-2.3 图生视频工作流 API 文件")

            def on_progress(pct, text):
                if self._interrupted:
                    client.interrupt()
                self.progress.emit(pct, text)

            result = client.generate_and_wait(
                self.workflow,
                progress_cb=on_progress,
                poll_interval=1.5,
            )
            if self._interrupted:
                self.error.emit("已停止")
                return
            self.finished_ok.emit(result)
        except Exception as e:
            if not self._interrupted:
                self.error.emit(str(e))

    def stop(self):
        self._interrupted = True


# ========== 预设模型定义 ==========
PRESET_MODELS = [
    {
        "id": "ltx23_sulphur2",
        "name": "LTX-2.3 + Sulphur 2",
        "description": "LTX 2.3 架构 + Sulphur 2 微调版",
        "workflow_file": "video_ltx2_3_t2v.json",
        "prompt_node": "267:327: TextGenerateLTX2Prompt",
        "model_folder": "Sulphur 2",
        "default_width": 768,
        "default_height": 432,
        "default_fps": 24,
    },
]


class VideoPanel(QWidget):
    """视频生成面板（新版布局）"""

    def __init__(self, parent=None, mode: str = "t2v"):
        super().__init__(parent)
        self.cfg = get_config_manager()
        self.mode = mode  # t2v=文生视频 / i2v=图生视频
        self.client = None
        self._server_address = "127.0.0.1:8188"
        self._generate_thread = None
        self._current_workflow_api = None
        self._current_workflow_name = ""
        self._model_file_summary = ""  # 模型文件检测摘要（供设置三步卡显示）
        self._video_outputs = []  # 生成历史
        self._temp_dir = os.path.join(tempfile.gettempdir(), "codemate_video")
        os.makedirs(self._temp_dir, exist_ok=True)

        self._init_ui()
        self._load_settings()
        self._refresh_connection_status()
        self._start_status_timer()

    # ========== UI 初始化 ==========

    def _init_ui(self):
        # 自身布局
        self.setObjectName("videoPanelRoot")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 背景层（放在最底层）
        self.bg_layer = AnimatedBackground(self)
        self.bg_layer.lower()

        # 主内容容器（透明背景）
        content = QWidget(self)
        content.setObjectName("contentOverlay")
        content.setStyleSheet("background: transparent;")
        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # ===== 顶部：系统监控 + 连接状态 =====
        top_bar = self._create_top_bar()
        main_layout.addWidget(top_bar)

        # ===== 主体：左（参数） + 右（预览+历史） =====
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)

        # 左侧面板
        left_panel = self._create_left_panel()
        splitter.addWidget(left_panel)

        # 右侧：预览区域
        right_panel = self._create_preview_panel()
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([300, 700])
        main_layout.addWidget(splitter, 1)

        # ===== 底部：模型选择 + 提示词 + 生成 =====
        bottom_bar = self._create_bottom_bar()
        main_layout.addWidget(bottom_bar)

        layout.addWidget(content)

    def _create_top_bar(self) -> QWidget:
        """顶部状态栏：系统监控 + 连接状态"""
        bar = QFrame()
        bar.setStyleSheet("""
            QFrame {
                background: rgba(30, 30, 30, 200);
                border-radius: 8px;
            }
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(20)

        # 标题
        title_text = "🖼 图生视频" if self.mode == "i2v" else "🎬 文生视频"
        title = QLabel(title_text)
        title.setStyleSheet("color: #fff; font-size: 15px; font-weight: bold; font-family: 'Microsoft YaHei';")
        layout.addWidget(title)

        layout.addSpacing(20)

        # 系统监控
        self.cpu_label = QLabel("CPU: --")
        self.cpu_label.setStyleSheet("color: #aaa; font-size: 12px;")
        self.mem_label = QLabel("内存: --")
        self.mem_label.setStyleSheet("color: #aaa; font-size: 12px;")
        self.gpu_label = QLabel("GPU: --")
        self.gpu_label.setStyleSheet("color: #aaa; font-size: 12px;")

        layout.addWidget(self.cpu_label)
        layout.addWidget(self.mem_label)
        layout.addWidget(self.gpu_label)

        layout.addStretch()

        # 连接状态
        self.conn_label = QLabel("● 检测中...")
        self.conn_label.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self.conn_label)

        # 设置按钮
        settings_btn = QPushButton("⚙️")
        settings_btn.setFixedSize(32, 28)
        settings_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none;
                font-size: 16px; border-radius: 4px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.1); }
        """)
        settings_btn.setToolTip("模型设置")
        settings_btn.clicked.connect(self._open_model_settings)
        layout.addWidget(settings_btn)

        return bar

    def _create_left_panel(self) -> QWidget:
        """左侧面板：模型设置三步 + 当前模型 + 视频参数 + 模型文件（带滚动）"""
        panel = QFrame()
        panel.setObjectName("videoLeftPanel")
        panel.setStyleSheet("""
            #videoLeftPanel {
                background: rgba(30, 30, 30, 200);
                border-radius: 8px;
            }
        """)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(6, 6, 6, 6)

        # 滚动区：内容过长时可上下滚动
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; }
            QScrollArea > QWidget > QWidget { background: transparent; }
            QScrollBar:vertical {
                background: rgba(255,255,255,0.06); width: 8px; border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.25); border-radius: 4px; min-height: 30px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        outer.addWidget(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(10)
        scroll.setWidget(content)

        group_style = """
            QGroupBox {
                color: #e6edf3; border: 1px solid rgba(255,255,255,0.15);
                border-radius: 6px; margin-top: 8px; padding-top: 12px;
                background: rgba(255,255,255,0.03);
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px; padding: 0 4px; font-size: 12px;
            }
        """

        # ===== 模型设置（三步，原封不动嵌入向导页面，竖排） =====
        setup_group = QGroupBox("模型设置")
        setup_group.setStyleSheet(group_style)
        sg = QVBoxLayout(setup_group)
        sg.setSpacing(12)

        # 创建向导实例（不弹出对话框），复用其三个步骤页面的完整控件：
        # 说明文字、截图（点击可放大）、路径输入框、浏览按钮、状态与检测列表等
        self._setup_wizard = VideoSetupWizard(self, mode=self.mode)
        wiz = self._setup_wizard
        # 向导里选中工作流后立即保存配置 → 面板马上重载，底部节点下拉框随之刷新
        wiz.workflow_saved.connect(self._load_current_model_workflow)
        step_titles = ["步骤 1 · 下载目录", "步骤 2 · 工作流", "步骤 3 · 模型文件"]
        for i, (title, step_w) in enumerate(zip(
                step_titles, (wiz.step1_widget, wiz.step2_widget, wiz.step3_widget))):
            step_w.setVisible(True)  # 向导默认隐藏 2/3 步，嵌入后全部显示
            cap = QLabel(title)
            cap.setStyleSheet(
                "color: #007acc; font-size: 11px; font-weight: bold; background: transparent;")
            sg.addWidget(cap)
            sg.addWidget(step_w)
            # 给步骤内的截图（有 pixmap 的 QLabel）安装点击放大
            for lbl in step_w.findChildren(QLabel):
                pix = lbl.pixmap()
                if pix is not None and not pix.isNull() and pix.width() > 100:
                    lbl.setProperty("zoomable", True)
                    lbl.installEventFilter(self)
                    lbl.setToolTip("点击放大查看")

        layout.addWidget(setup_group)

        # ===== 模型信息 =====
        model_group = QGroupBox("当前模型")
        model_group.setStyleSheet(group_style)
        mg = QVBoxLayout(model_group)
        mg.setSpacing(4)

        self.model_name_label = QLabel("未选择模型")
        self.model_name_label.setStyleSheet("color: #fff; font-size: 13px; font-weight: bold;")
        mg.addWidget(self.model_name_label)

        self.model_desc_label = QLabel("请在下方选择模型")
        self.model_desc_label.setStyleSheet("color: #888; font-size: 11px;")
        self.model_desc_label.setWordWrap(True)
        mg.addWidget(self.model_desc_label)

        layout.addWidget(model_group)

        # 视频参数
        param_group = QGroupBox("视频参数")
        param_group.setStyleSheet("""
            QGroupBox {
                color: #e6edf3; border: 1px solid rgba(255,255,255,0.15);
                border-radius: 6px; margin-top: 8px; padding-top: 12px;
                background: rgba(255,255,255,0.03);
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px; padding: 0 4px; font-size: 12px;
            }
        """)
        pf = QFormLayout(param_group)
        pf.setSpacing(10)

        # 分辨率
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
        w = QWidget()
        w.setLayout(res_row)
        pf.addRow("分辨率:", w)

        # 时长
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 100000)
        self.duration_spin.setValue(5)
        self.duration_spin.setSuffix(" 秒")
        self.duration_spin.setStyleSheet(self._spin_style())
        pf.addRow("时长:", self.duration_spin)

        # 帧率
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(8, 60)
        self.fps_spin.setValue(24)
        self.fps_spin.setSuffix(" fps")
        self.fps_spin.setStyleSheet(self._spin_style())
        pf.addRow("帧率:", self.fps_spin)

        # 步数
        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(1, 200)
        self.steps_spin.setValue(20)
        self.steps_spin.setStyleSheet(self._spin_style())
        steps_row = QHBoxLayout()
        steps_row.setContentsMargins(0, 0, 0, 0)
        steps_row.setSpacing(4)
        steps_row.addWidget(self.steps_spin, 1)
        steps_help = QPushButton("?")
        steps_help.setFixedSize(22, 22)
        steps_help.setToolTip("什么是步数？")
        steps_help.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.1); color: #aaa;
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 11px; font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background: rgba(0,122,204,0.5); color: #fff; }
        """)
        steps_help.clicked.connect(self._show_steps_help)
        steps_row.addWidget(steps_help)
        steps_widget = QWidget()
        steps_widget.setLayout(steps_row)
        pf.addRow("步数:", steps_widget)

        # CFG
        self.cfg_spin = QDoubleSpinBox()
        self.cfg_spin.setRange(1.0, 20.0)
        self.cfg_spin.setValue(6.0)
        self.cfg_spin.setSingleStep(0.5)
        self.cfg_spin.setStyleSheet(self._spin_style())
        cfg_row = QHBoxLayout()
        cfg_row.setContentsMargins(0, 0, 0, 0)
        cfg_row.setSpacing(4)
        cfg_row.addWidget(self.cfg_spin, 1)
        cfg_help = QPushButton("?")
        cfg_help.setFixedSize(22, 22)
        cfg_help.setToolTip("什么是 CFG？")
        cfg_help.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.1); color: #aaa;
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 11px; font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background: rgba(0,122,204,0.5); color: #fff; }
        """)
        cfg_help.clicked.connect(self._show_cfg_help)
        cfg_row.addWidget(cfg_help)
        cfg_widget = QWidget()
        cfg_widget.setLayout(cfg_row)
        pf.addRow("CFG:", cfg_widget)

        layout.addWidget(param_group)

        # 模型文件状态
        model_file_group = QGroupBox("模型文件")
        model_file_group.setStyleSheet("""
            QGroupBox {
                color: #e6edf3; border: 1px solid rgba(255,255,255,0.15);
                border-radius: 6px; margin-top: 8px; padding-top: 12px;
                background: rgba(255,255,255,0.03);
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px; padding: 0 4px; font-size: 12px;
            }
        """)
        mfg = QVBoxLayout(model_file_group)
        mfg.setSpacing(4)

        self.model_file_status = QLabel("检测中...")
        self.model_file_status.setStyleSheet("color: #888; font-size: 11px;")
        mfg.addWidget(self.model_file_status)

        self.model_file_rows = QWidget()
        self.model_file_rows_layout = QVBoxLayout(self.model_file_rows)
        self.model_file_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.model_file_rows_layout.setSpacing(3)
        mfg.addWidget(self.model_file_rows)

        layout.addWidget(model_file_group)

        layout.addStretch()
        return panel

    def eventFilter(self, obj, event):
        """嵌入步骤页截图点击放大"""
        if event.type() == QEvent.MouseButtonRelease and obj.property("zoomable"):
            pix = obj.pixmap()
            if pix is not None and not pix.isNull():
                self._zoom_pixmap(pix)
                return True
        return super().eventFilter(obj, event)

    def _zoom_pixmap(self, pix: QPixmap):
        """弹窗放大查看图片"""
        dlg = QDialog(self)
        dlg.setWindowTitle("步骤示意图（点击图片关闭）")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(8, 8, 8, 8)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setCursor(Qt.PointingHandCursor)
        screen = QApplication.primaryScreen().availableGeometry()
        lbl.setPixmap(pix.scaled(int(screen.width() * 0.8), int(screen.height() * 0.8),
                                 Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lbl.mousePressEvent = lambda e: dlg.accept()
        lay.addWidget(lbl)
        dlg.exec_()

    def _refresh_setup_steps(self):
        """同步嵌入的三步向导实例（从配置重新加载并刷新检测状态）"""
        wiz = getattr(self, "_setup_wizard", None)
        if wiz is None:
            return
        try:
            wiz._load_settings()
        except Exception:
            pass

    def _create_preview_panel(self) -> QWidget:
        """右侧预览面板"""
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background: rgba(30, 30, 30, 200);
                border-radius: 8px;
            }
        """)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # 视频预览区域
        preview_container = QFrame()
        preview_container.setStyleSheet("""
            QFrame {
                background: #000;
                border-radius: 6px;
            }
        """)
        preview_container.setMinimumHeight(300)
        pv = QVBoxLayout(preview_container)
        pv.setContentsMargins(0, 0, 0, 0)

        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background: #000;")
        self.video_widget.setMinimumSize(400, 300)
        pv.addWidget(self.video_widget)

        self.media_player = QMediaPlayer()
        self.media_player.setVideoOutput(self.video_widget)
        self.media_player.error.connect(self._on_media_error)

        layout.addWidget(preview_container, 1)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #3c3c3c; border-radius: 4px;
                background: #252526; text-align: center; color: #fff;
                height: 22px;
            }
            QProgressBar::chunk { background: #007acc; border-radius: 3px; }
        """)
        layout.addWidget(self.progress_bar)

        # 状态文本
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.status_label)

        # 播放控制
        ctrl_row = QHBoxLayout()
        self.play_btn = QPushButton("▶ 播放")
        self.play_btn.setFixedSize(80, 28)
        self.play_btn.setStyleSheet(self._btn_secondary_style())
        self.play_btn.clicked.connect(self._toggle_play)
        self.play_btn.setEnabled(False)

        self.save_btn = QPushButton("💾 保存视频")
        self.save_btn.setFixedSize(90, 28)
        self.save_btn.setStyleSheet(self._btn_secondary_style())
        self.save_btn.clicked.connect(self._save_video)
        self.save_btn.setEnabled(False)

        self.stop_btn = QPushButton("⏹ 停止生成")
        self.stop_btn.setFixedSize(100, 28)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background: #a12d2d; color: white; border: none;
                padding: 4px 12px; border-radius: 4px; font-size: 12px;
            }
            QPushButton:hover { background: #c93a3a; }
            QPushButton:disabled { background: #3a3a3a; color: #666; }
        """)
        self.stop_btn.clicked.connect(self._stop_generation)
        self.stop_btn.setEnabled(False)

        ctrl_row.addWidget(self.play_btn)
        ctrl_row.addWidget(self.save_btn)
        ctrl_row.addStretch()
        ctrl_row.addWidget(self.stop_btn)
        layout.addLayout(ctrl_row)

        # 历史记录
        history_label = QLabel("生成历史")
        history_label.setStyleSheet("color: #aaa; font-size: 12px; font-weight: bold;")
        layout.addWidget(history_label)

        self.history_list = QListWidget()
        self.history_list.setFixedHeight(100)
        self.history_list.setStyleSheet("""
            QListWidget {
                background: rgba(255,255,255,0.03);
                color: #ccc; border: 1px solid rgba(255,255,255,0.1);
                border-radius: 6px; padding: 4px;
            }
            QListWidget::item { padding: 6px 8px; border-radius: 4px; }
            QListWidget::item:selected { background: #094771; }
        """)
        self.history_list.itemDoubleClicked.connect(self._on_history_selected)
        layout.addWidget(self.history_list)

        return panel

    def _create_bottom_bar(self) -> QWidget:
        """底部栏：模型选择 + 提示词 + 生成按钮"""
        bar = QFrame()
        bar.setStyleSheet("""
            QFrame {
                background: rgba(30, 30, 30, 200);
                border-radius: 8px;
            }
        """)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        # 图生视频：输入图片选择行
        if self.mode == "i2v":
            img_row = QHBoxLayout()
            img_row.setSpacing(8)

            img_label = QLabel("输入图片:")
            img_label.setStyleSheet("color: #aaa; font-size: 12px;")
            img_row.addWidget(img_label)

            self.image_edit = QLineEdit()
            self.image_edit.setPlaceholderText("必填：选择作为视频首帧的图片（点击右侧浏览）")
            self.image_edit.setReadOnly(True)
            self.image_edit.setStyleSheet("""
                QLineEdit {
                    background: rgba(255,255,255,0.05);
                    color: #e6edf3; border: 1px solid rgba(255,255,255,0.15);
                    border-radius: 4px; padding: 4px 8px; font-size: 12px;
                }
            """)
            img_row.addWidget(self.image_edit, 1)

            self.btn_browse_image = QPushButton("浏览...")
            self.btn_browse_image.setStyleSheet(self._btn_secondary_style())
            self.btn_browse_image.setCursor(Qt.PointingHandCursor)
            self.btn_browse_image.clicked.connect(self._browse_image)
            img_row.addWidget(self.btn_browse_image)

            layout.addLayout(img_row)

        # 提示词输入
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText("输入视频生成提示词（英文）...\n例如：A beautiful sunset over the ocean, cinematic lighting, 4k")
        self.prompt_edit.setFixedHeight(80)
        self.prompt_edit.setStyleSheet("""
            QTextEdit {
                background: rgba(255,255,255,0.05);
                color: #e6edf3; border: 1px solid rgba(255,255,255,0.15);
                border-radius: 6px; padding: 10px 12px; font-size: 13px;
                font-family: "Consolas", "Microsoft YaHei";
            }
            QTextEdit:focus { border-color: #007acc; }
        """)
        layout.addWidget(self.prompt_edit)

        # 底部一行：模型选择 + 提示词节点 + 生成按钮
        row = QHBoxLayout()
        row.setSpacing(10)

        # 模型选择
        model_label = QLabel("模型:")
        model_label.setStyleSheet("color: #aaa; font-size: 12px;")
        row.addWidget(model_label)

        self.model_combo = QComboBox()
        self.model_combo.setFixedWidth(200)
        self.model_combo.setStyleSheet(self._combo_style())
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        row.addWidget(self.model_combo)

        # 图生视频：图片节点选择
        if self.mode == "i2v":
            img_node_label = QLabel("图片节点:")
            img_node_label.setStyleSheet("color: #aaa; font-size: 12px;")
            row.addWidget(img_node_label)

            self.image_node_combo = QComboBox()
            self.image_node_combo.setFixedWidth(220)
            self.image_node_combo.setStyleSheet(self._combo_style())
            row.addWidget(self.image_node_combo)

        # 提示词节点
        node_label = QLabel("提示词节点:")
        node_label.setStyleSheet("color: #aaa; font-size: 12px;")
        row.addWidget(node_label)

        self.prompt_node_combo = QComboBox()
        self.prompt_node_combo.setFixedWidth(220)
        self.prompt_node_combo.setStyleSheet(self._combo_style())
        row.addWidget(self.prompt_node_combo)

        row.addStretch()

        # 生成按钮
        self.btn_generate = QPushButton("🎬 生成视频")
        self.btn_generate.setFixedSize(120, 36)
        self.btn_generate.setStyleSheet("""
            QPushButton {
                background: #007acc; color: white; border: none;
                border-radius: 6px; font-size: 14px; font-weight: bold;
            }
            QPushButton:hover { background: #0e639c; }
            QPushButton:disabled { background: #3a3a3a; color: #666; }
        """)
        self.btn_generate.clicked.connect(self._generate_video)
        self.btn_generate.setEnabled(False)
        row.addWidget(self.btn_generate)

        layout.addLayout(row)

        return bar

    # ========== 样式辅助 ==========

    def _spin_style(self) -> str:
        return """
            QSpinBox, QDoubleSpinBox {
                background: rgba(255,255,255,0.05);
                color: #ccc; border: 1px solid rgba(255,255,255,0.15);
                border-radius: 4px; padding: 4px 8px; font-size: 12px;
            }
            QSpinBox:focus, QDoubleSpinBox:focus { border-color: #007acc; }
        """

    def _combo_style(self) -> str:
        return """
            QComboBox {
                background: rgba(255,255,255,0.05);
                color: #ccc; border: 1px solid rgba(255,255,255,0.15);
                border-radius: 4px; padding: 4px 8px; font-size: 12px;
                min-height: 22px;
            }
            QComboBox:hover { border-color: #007acc; }
            QComboBox QAbstractItemView {
                background: #252526; color: #ccc; border: 1px solid #3c3c3c;
                selection-background-color: #094771;
            }
        """

    def _btn_secondary_style(self) -> str:
        return """
            QPushButton {
                background: rgba(255,255,255,0.08);
                color: #e6edf3; border: 1px solid rgba(255,255,255,0.15);
                border-radius: 4px; padding: 4px 12px; font-size: 12px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.15); }
            QPushButton:disabled { color: #555; }
        """

    # ========== 设置加载/保存 ==========

    def reload_theme(self):
        """有壁纸时透明让主窗口壁纸层透出；无壁纸回退纯色底"""
        import os
        theme_cfg = self.cfg.get("theme", {})
        bg_image = theme_cfg.get("chat_bg_image", "")
        if bg_image and os.path.exists(bg_image):
            self.bg_layer.clear_to_transparent()
        else:
            self.bg_layer.set_background(
                "", theme_cfg.get("chat_bg_color", "#252526"),
                theme_cfg.get("bg_opacity", 100) / 100.0)

    def resizeEvent(self, event):
        """调整大小时同步背景层大小"""
        super().resizeEvent(event)
        if hasattr(self, 'bg_layer') and self.bg_layer:
            self.bg_layer.setGeometry(self.rect())

    def _load_settings(self):
        """加载设置"""
        theme_cfg = self.cfg.get("theme", {})
        comfy_cfg = self.cfg.get("comfyui", {})

        # 背景（有壁纸时透明，交给主窗口壁纸层；无壁纸回退纯色底）
        import os
        bg_image = theme_cfg.get("chat_bg_image", "")
        if bg_image and os.path.exists(bg_image):
            self.bg_layer.clear_to_transparent()
        else:
            self.bg_layer.set_background(
                "", theme_cfg.get("chat_bg_color", "#252526"),
                theme_cfg.get("bg_opacity", 100) / 100.0)

        # ComfyUI 地址
        server_addr = comfy_cfg.get("server_address", "127.0.0.1:8188")
        self._server_address = server_addr
        self.client = ComfyUIClient(server_addr)

        # 加载模型列表（预设 + 自定义）
        self.model_combo.clear()
        for m in PRESET_MODELS:
            self.model_combo.addItem(m["name"], m["id"])

        # 加载上次选中的模型
        last_model = comfy_cfg.get("last_model", "ltx23_sulphur2")
        for i in range(self.model_combo.count()):
            if self.model_combo.itemData(i) == last_model:
                self.model_combo.setCurrentIndex(i)
                break

        # 加载视频参数
        self.width_spin.setValue(comfy_cfg.get("default_width", 768))
        self.height_spin.setValue(comfy_cfg.get("default_height", 432))
        self.duration_spin.setValue(comfy_cfg.get("default_duration", 5))
        self.fps_spin.setValue(comfy_cfg.get("default_fps", 24))
        self.steps_spin.setValue(comfy_cfg.get("default_steps", 20))
        self.cfg_spin.setValue(comfy_cfg.get("default_cfg", 6.0))

        # 加载工作流
        self._load_current_model_workflow()
        # 刷新左侧模型设置三步状态
        self._refresh_setup_steps()

    def _save_param_settings(self):
        """保存视频参数"""
        comfy_cfg = self.cfg.get("comfyui", {})
        comfy_cfg["default_width"] = self.width_spin.value()
        comfy_cfg["default_height"] = self.height_spin.value()
        comfy_cfg["default_duration"] = self.duration_spin.value()
        comfy_cfg["default_fps"] = self.fps_spin.value()
        comfy_cfg["default_steps"] = self.steps_spin.value()
        comfy_cfg["default_cfg"] = self.cfg_spin.value()
        self.cfg.set("comfyui", comfy_cfg)
        self.cfg.save()

    # ========== 模型管理 ==========

    def _on_model_changed(self, index: int):
        """模型切换"""
        if index < 0:
            return
        model_id = self.model_combo.itemData(index)
        model_info = self._get_model_info(model_id)
        if not model_info:
            return

        self.model_name_label.setText(model_info["name"])
        self.model_desc_label.setText(model_info.get("description", ""))

        # 保存选择
        comfy_cfg = self.cfg.get("comfyui", {})
        comfy_cfg["last_model"] = model_id
        self.cfg.set("comfyui", comfy_cfg)
        self.cfg.save()

        # 加载该模型的工作流
        self._load_current_model_workflow()

        # 刷新模型文件状态
        self._refresh_model_file_status()

    def _get_model_info(self, model_id: str) -> dict:
        """获取模型信息"""
        for m in PRESET_MODELS:
            if m["id"] == model_id:
                return m
        return {}

    def _get_app_root(self) -> str:
        """获取程序根目录"""
        import os
        desktop_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.dirname(desktop_dir)

    def _load_current_model_workflow(self):
        """加载当前模型的默认工作流"""
        model_id = self.model_combo.itemData(self.model_combo.currentIndex())
        model_info = self._get_model_info(model_id)
        if not model_info:
            self.btn_generate.setEnabled(False)
            return

        # 先检查配置中有没有保存的工作流（按模式分键，文生/图生互不覆盖）
        comfy_cfg = self.cfg.get("comfyui", {})
        workflows = comfy_cfg.get("workflows", [])
        last_wf = comfy_cfg.get(f"last_workflow_{self.mode}", "")

        if last_wf:
            for wf in workflows:
                if wf.get("id") == last_wf and wf.get("data"):
                    self._current_workflow_api = wf["data"]
                    self._current_workflow_name = wf.get("name", "")
                    self._populate_prompt_nodes()
                    # 自动选择指定节点
                    self._auto_select_prompt_node(model_info.get("prompt_node", ""))
                    self.btn_generate.setEnabled(True)
                    self._refresh_setup_steps()
                    return

        # 配置中没有，尝试从模型文件夹加载默认工作流（按模式区分文件名）
        wf_filename = model_info.get("workflow_file", "")
        if self.mode == "i2v":
            wf_filename = "video_ltx2_3_i2v.json"
        if wf_filename:
            model_folder = model_info.get("model_folder", "")
            wf_path = os.path.join(self._get_app_root(), "models", model_folder, wf_filename)
            if os.path.exists(wf_path):
                try:
                    wf_data = load_workflow_json(wf_path)
                    if "prompt" in wf_data and isinstance(wf_data["prompt"], dict):
                        api_wf = wf_data["prompt"]
                    elif "nodes" in wf_data:
                        api_wf = convert_ui_to_api(wf_data)
                    else:
                        api_wf = wf_data

                    self._current_workflow_api = api_wf
                    self._current_workflow_name = wf_filename
                    self._populate_prompt_nodes()
                    self._auto_select_prompt_node(model_info.get("prompt_node", ""))
                    self.btn_generate.setEnabled(True)
                    self._refresh_setup_steps()
                    return
                except Exception:
                    pass

        self.btn_generate.setEnabled(False)
        self._refresh_setup_steps()

    def _auto_select_prompt_node(self, target_node: str):
        """自动选择指定的提示词节点"""
        if not target_node:
            return
        for i in range(self.prompt_node_combo.count()):
            text = self.prompt_node_combo.itemText(i)
            if target_node in text:
                self.prompt_node_combo.setCurrentIndex(i)
                return

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

        # 图生视频：同时填充图片节点（LoadImage）下拉框
        if self.mode == "i2v":
            self.image_node_combo.clear()
            for nid, node in self._current_workflow_api.items():
                ctype = str(node.get("class_type", "")).lower()
                if ctype in ("loadimage", "load_image"):
                    label = node.get("class_type", nid)
                    self.image_node_combo.addItem(f"{nid}: {label}", nid)

    def _refresh_model_file_status(self):
        """刷新模型文件状态"""
        # 清空
        while self.model_file_rows_layout.count() > 0:
            item = self.model_file_rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        comfy_cfg = self.cfg.get("comfyui", {})
        download_folder = comfy_cfg.get("download_folder", "")

        if not download_folder or not os.path.isdir(download_folder):
            self.model_file_status.setText("⚠️ 未设置实例目录")
            self.model_file_status.setStyleSheet("color: #dcdcaa; font-size: 11px;")
            self._model_file_summary = "⚠️ 未设置实例目录"
            self._refresh_setup_steps()
            return

        model_id = self.model_combo.itemData(self.model_combo.currentIndex())
        model_info = self._get_model_info(model_id)
        model_source = model_info.get("model_folder", "Sulphur 2")

        try:
            from core.model_manager import check_models
            models = check_models(download_folder, model_source)
        except Exception:
            self.model_file_status.setText("检测失败")
            self._model_file_summary = "检测失败"
            self._refresh_setup_steps()
            return

        total = len(models)
        ready = sum(1 for m in models if m["exists"])

        if ready == total:
            self.model_file_status.setText(f"✅ 全部就绪 ({ready}/{total})")
            self.model_file_status.setStyleSheet("color: #3fb950; font-size: 11px;")
            self._model_file_summary = f"✅ 全部就绪 ({ready}/{total})"
        else:
            self.model_file_status.setText(f"⚠️ {ready}/{total} 个就绪")
            self.model_file_status.setStyleSheet("color: #dcdcaa; font-size: 11px;")
            self._model_file_summary = f"⚠️ {ready}/{total} 个就绪"

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
            self.model_file_rows_layout.addWidget(w)

        self._refresh_setup_steps()

    # ========== 系统监控 ==========

    def _start_status_timer(self):
        """启动系统状态刷新定时器"""
        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._refresh_system_status)
        self._status_timer.start(2000)
        self._refresh_system_status()

    def _refresh_system_status(self):
        """刷新系统资源状态"""
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory().percent
            self.cpu_label.setText(f"CPU: {cpu:.0f}%")
            self.mem_label.setText(f"内存: {mem:.0f}%")

            # GPU 检测（简单版，通过 nvidia-smi）
            gpu_val = self._get_gpu_usage()
            self.gpu_label.setText(f"GPU: {gpu_val}")
        except Exception:
            pass

        # 也刷新连接状态
        self._refresh_connection_status()

    def _get_gpu_usage(self) -> str:
        """获取 GPU 使用率"""
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if lines and lines[0].strip():
                    return f"{lines[0].strip()}%"
        except Exception:
            pass
        return "--"

    def _refresh_connection_status(self):
        """刷新 ComfyUI 连接状态"""
        if not self.client:
            return
        try:
            ok = self.client.check_connection()
            if ok:
                self.conn_label.setText("● ComfyUI 已连接")
                self.conn_label.setStyleSheet("color: #3fb950; font-size: 12px;")
                if self._current_workflow_api:
                    self.btn_generate.setEnabled(True)
            else:
                self.conn_label.setText("● ComfyUI 未连接")
                self.conn_label.setStyleSheet("color: #f85149; font-size: 12px;")
        except Exception:
            self.conn_label.setText("● 连接检测失败")
            self.conn_label.setStyleSheet("color: #f85149; font-size: 12px;")

    # ========== 视频生成 ==========

    def _browse_image(self):
        """图生视频：选择输入图片"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择输入图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)"
        )
        if path:
            self.image_edit.setText(path)

    def _generate_video(self):
        """生成视频"""
        if not self._current_workflow_api:
            QMessageBox.warning(self, "提示", "请先加载工作流")
            return

        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "提示", "请输入提示词")
            return

        # 图生视频：校验并携带输入图片
        image_path = ""
        if self.mode == "i2v":
            image_path = self.image_edit.text().strip()
            if not image_path or not os.path.isfile(image_path):
                QMessageBox.warning(self, "提示", "请先选择用于生成视频的输入图片")
                return

        if not self.client or not self.client.check_connection():
            ret = QMessageBox.question(
                self, "未连接",
                "ComfyUI 未连接，是否继续尝试？\n\n请确保 ComfyUI 已启动。",
                QMessageBox.Yes | QMessageBox.No
            )
            if ret != QMessageBox.Yes:
                return

        # 构建工作流副本
        import copy
        workflow = copy.deepcopy(self._current_workflow_api)

        # 注入提示词（兼容 API 格式：节点字符串输入 / 顺着链接找源头字符串节点）
        prompt_node_id = self.prompt_node_combo.currentData()
        if prompt_node_id:
            from core.comfyui_client import inject_prompt_text
            if inject_prompt_text(workflow, prompt_node_id, prompt) == 0:
                QMessageBox.warning(
                    self, "提示词注入失败",
                    f"无法在提示词节点 {prompt_node_id} 上找到可注入的文本输入。\n"
                    "请重新在 ComfyUI 中导出(API)工作流文件。")
                return
        else:
            QMessageBox.warning(self, "未选择提示词节点", "请先在底栏选择提示词节点。")
            return

        # 注入视频参数（时长/帧率/分辨率，LTX 模板的 PrimitiveInt 参数节点）
        from core.comfyui_client import inject_video_params
        inject_video_params(
            workflow,
            width=self.width_spin.value(),
            height=self.height_spin.value(),
            duration=self.duration_spin.value(),
            fps=self.fps_spin.value(),
        )

        # 保存参数
        self._save_param_settings()

        # UI 状态
        self.btn_generate.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("开始生成...")

        # 启动生成线程（图生视频时携带图片路径与选中的图片节点，由线程内上传注入）
        image_node_id = None
        if self.mode == "i2v":
            image_node_id = self.image_node_combo.currentData()
        self._generate_thread = GenerateThread(self._server_address, workflow, image_path, image_node_id)
        self._generate_thread.progress.connect(self._on_generate_progress)
        self._generate_thread.finished_ok.connect(self._on_generate_finished)
        self._generate_thread.error.connect(self._on_generate_error)
        self._generate_thread.start()

    def _on_generate_progress(self, pct: float, text: str):
        self.progress_bar.setValue(int(pct * 100))
        self.status_label.setText(text)

    def _on_generate_finished(self, result: dict):
        self.btn_generate.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setValue(100)
        self.status_label.setText("✅ 生成完成")

        # 收集所有输出文件信息：
        # - videos/images/files 是 _extract_outputs 已分类的列表
        # - 兜底扫描 outputs 里各节点的其他输出键（如新版保存视频节点的 "video"/"gifs"）
        infos = list(result.get("videos", [])) + list(result.get("images", [])) + list(result.get("files", []))
        for node_output in (result.get("outputs") or {}).values():
            if not isinstance(node_output, dict):
                continue
            for key in ("video", "videos", "gifs", "images", "files"):
                val = node_output.get(key)
                if isinstance(val, list):
                    infos.extend(val)

        # 找视频文件下载预览
        for img_info in infos:
            if not isinstance(img_info, dict):
                continue
            filename = img_info.get("filename", "")
            if not filename.lower().endswith(('.mp4', '.webm', '.mov', '.avi', '.mkv', '.gif')):
                continue
            try:
                video_data = self.client.get_image(filename, img_info.get("subfolder", ""), img_info.get("type", "output"))
                if not video_data:
                    self.status_label.setText(f"❌ 下载视频失败：{filename}")
                    return
                # 文件名可能带子目录前缀（如 video/xxx.mp4），本地只保留文件名部分
                output_path = os.path.join(self._temp_dir, os.path.basename(filename))
                with open(output_path, 'wb') as f:
                    f.write(video_data)
                self._video_outputs.append(output_path)
                self._add_to_history(output_path)
                self._play_video(output_path)
                self.save_btn.setEnabled(True)
                self.play_btn.setEnabled(True)
            except Exception as e:
                self.status_label.setText(f"下载失败：{str(e)}")
            return

        self.status_label.setText("生成完成（未找到视频文件）")

    def _on_generate_error(self, error_msg: str):
        self.btn_generate.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText(f"❌ {error_msg}")
        self.status_label.setStyleSheet("color: #f85149; font-size: 12px;")
        QTimer.singleShot(3000, lambda: self.status_label.setStyleSheet("color: #888; font-size: 11px;"))

    def _stop_generation(self):
        if self._generate_thread and self._generate_thread.isRunning():
            self._generate_thread.stop()
            self.status_label.setText("正在停止...")

    # ========== 视频播放 ==========

    def _play_video(self, path: str):
        if not os.path.exists(path):
            self.status_label.setText("❌ 视频文件不存在")
            return
        self.media_player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
        self.media_player.play()
        self.play_btn.setText("⏸ 暂停")
        self.play_btn.setEnabled(True)

    def _on_media_error(self, error):
        """播放器错误处理"""
        error_map = {
            QMediaPlayer.NoError: "无错误",
            QMediaPlayer.ResourceError: "资源错误：无法播放该视频格式",
            QMediaPlayer.FormatError: "格式错误：不支持的视频格式",
            QMediaPlayer.NetworkError: "网络错误",
            QMediaPlayer.AccessDeniedError: "访问被拒绝",
            QMediaPlayer.ServiceMissingError: "缺少服务：系统缺少媒体播放器组件",
        }
        err_msg = error_map.get(error, f"未知错误: {error}")
        self.status_label.setText(f"⚠️ 视频播放失败：{err_msg}")
        self.status_label.setStyleSheet("color: #dcdcaa; font-size: 11px;")

    def _toggle_play(self):
        if self.media_player.state() == QMediaPlayer.PlayingState:
            self.media_player.pause()
            self.play_btn.setText("▶ 播放")
        else:
            self.media_player.play()
            self.play_btn.setText("⏸ 暂停")

    def _save_video(self):
        if not self._video_outputs:
            return
        latest = self._video_outputs[-1]
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存视频",
            os.path.basename(latest),
            "视频文件 (*.mp4 *.webm *.mov)"
        )
        if save_path:
            import shutil
            shutil.copy2(latest, save_path)
            QMessageBox.information(self, "成功", f"视频已保存到：\n{save_path}")

    # ========== 历史记录 ==========

    def _add_to_history(self, path: str):
        import time
        timestamp = time.strftime("%H:%M:%S")
        item = QListWidgetItem(f"🎥 {timestamp}  {os.path.basename(path)}")
        item.setData(Qt.UserRole, path)
        self.history_list.insertItem(0, item)

    def _on_history_selected(self, item):
        path = item.data(Qt.UserRole)
        if path and os.path.exists(path):
            self._play_video(path)

    # ========== 参数帮助 ==========

    def _show_steps_help(self):
        """显示步数参数说明"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("步数（Steps）是什么？")
        msg.setText(
            "<h3>步数（Steps）</h3>"
            "<p>扩散模型生成视频的过程是从<b>纯噪点</b>一步步「去噪」变成清晰画面。"
            "步数就是去噪的迭代次数。</p>"
            "<h4>效果对比</h4>"
            "<table border='0' cellpadding='4' cellspacing='0'>"
            "<tr><td><b>少（1-10步）</b></td><td>快，但画面模糊、细节少</td></tr>"
            "<tr><td><b>适中（20-30步）</b></td><td>✅ 质量和速度的平衡点（推荐）</td></tr>"
            "<tr><td><b>多（50步以上）</b></td><td>细节更丰富，但越往后提升越小</td></tr>"
            "</table>"
            "<h4>简单说</h4>"
            "<p>步数越高 → 画质越好，但生成越慢。<br>"
            "一般 20-30 步就够用了。</p>"
        )
        msg.setStyleSheet("""
            QMessageBox { background: #252526; color: #ccc; }
            QLabel { color: #ccc; font-size: 13px; }
            QPushButton { background: #0e639c; color: #fff; border: none;
                          border-radius: 4px; padding: 6px 16px; min-width: 80px; }
        """)
        msg.exec_()

    def _show_cfg_help(self):
        """显示 CFG 参数说明"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("CFG 是什么？")
        msg.setText(
            "<h3>CFG（Classifier-Free Guidance）</h3>"
            "<p>CFG 控制模型有多「听话」——也就是多严格地按照你的提示词来生成。</p>"
            "<h4>效果对比</h4>"
            "<table border='0' cellpadding='4' cellspacing='0'>"
            "<tr><td><b>1 - 3</b></td><td>很自由，经常跑题</td><td>想要创意、随机</td></tr>"
            "<tr><td><b>4 - 7</b></td><td>✅ 平衡（推荐）</td><td>日常使用</td></tr>"
            "<tr><td><b>8 - 12</b></td><td>非常严格遵循提示词</td><td>需要精确控制画面</td></tr>"
            "<tr><td><b>15+</b></td><td>太严了，画面可能过饱和/怪异</td><td>不推荐</td></tr>"
            "</table>"
            "<h4>简单说</h4>"
            "<p>CFG 越高 → AI 越听你的话，但太高会让画面变得不自然。<br>"
            "默认 6.0 是比较均衡的值。</p>"
        )
        msg.setStyleSheet("""
            QMessageBox { background: #252526; color: #ccc; }
            QLabel { color: #ccc; font-size: 13px; }
            QPushButton { background: #0e639c; color: #fff; border: none;
                          border-radius: 4px; padding: 6px 16px; min-width: 80px; }
        """)
        msg.exec_()

    # ========== 设置向导 ==========

    def _open_model_settings(self):
        """打开模型设置向导"""
        from widgets.video_setup_wizard import VideoSetupWizard
        wizard = VideoSetupWizard(self, mode=self.mode)
        if wizard.exec_():
            self._load_settings()
            self._refresh_connection_status()
            self._refresh_model_file_status()
