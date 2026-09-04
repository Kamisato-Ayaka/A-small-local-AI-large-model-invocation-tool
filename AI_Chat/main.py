"""
A Small Local AI Runner 主窗口 - 对话 + 视频生成
"""
import os
import sys
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QMenuBar, QAction, QFileDialog, QMessageBox, QLabel, QPushButton,
    QToolBar, QSizePolicy, QSystemTrayIcon, QMenu, QApplication, QComboBox
)
from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtGui import QFont, QKeySequence, QIcon, QPixmap

from widgets.ai_panel import AIPanel
from widgets.video_panel_v2 import VideoPanel
from widgets.tts_panel import TTSPanel
from widgets.wallpaper_panel import WallpaperPanel
from widgets.settings_dialog import SettingsDialog
from widgets.web_server_dialog import WebServerDialog
from core.llm_client import LLMClient
from core.config import get_config_manager
from core.server_manager import ServerManager
from core.system_monitor import SystemMonitor


class MainWindow(QMainWindow):
    """主窗口 - 对话 + 视频生成"""

    def __init__(self, workspace_path: str = None, llm_url: str = None):
        super().__init__()
        self.cfg = get_config_manager()
        self.workspace_path = workspace_path or os.path.join(os.path.dirname(__file__), "workspace")
        self.llm_url = llm_url
        self.server_manager = ServerManager()
        self.system_monitor = SystemMonitor()
        self._current_mode = ""  # 空值确保首次 _switch_mode 必定执行（非短路）

        # 角色文件夹（优先使用项目根目录的 charter 文件夹）
        project_root = os.path.dirname(os.path.abspath(__file__))
        charter_in_project = os.path.join(project_root, "charter")
        charter_in_parent = os.path.join(os.path.dirname(project_root), "charter")
        if os.path.exists(charter_in_parent):
            self.charter_dir = charter_in_parent
        elif os.path.exists(charter_in_project):
            self.charter_dir = charter_in_project
        else:
            # 默认创建在项目根目录
            self.charter_dir = charter_in_project
            os.makedirs(self.charter_dir, exist_ok=True)

        self._init_ui()
        self._init_menu()
        self._init_signals()
        self._update_title()

        # 启动系统监控
        self.system_monitor.start()

        # 初始化系统托盘
        self._init_tray()

        # Web 服务对话框（延迟创建）
        self.web_dialog = None

    def _init_ui(self):
        self.setWindowTitle("A Small Local AI Runner - AI 对话")
        self.resize(1100, 750)
        self.setMinimumSize(700, 500)

        # 中心部件
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # ===== 顶栏（两行） =====
        mode_bar = QWidget()
        self.mode_bar = mode_bar
        mode_bar.setFixedHeight(108)
        self._mode_bar_default_style = """
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1a1a2e, stop:1 #16213e);
                border-bottom: 1px solid rgba(0, 212, 255, 0.15);
            }
        """
        mode_bar.setStyleSheet(self._mode_bar_default_style)
        outer = QVBoxLayout(mode_bar)
        outer.setContentsMargins(12, 6, 12, 6)
        outer.setSpacing(2)

        # ---- 第一行：Logo + 模式按钮 + 右上角 ----
        row1 = QHBoxLayout()
        row1.setSpacing(4)

        # Logo
        title_label = QLabel("✨ A Small Local AI Runner")
        title_label.setStyleSheet("""
            color: #00d4ff; font-size: 14px; font-weight: 800;
            font-family: "Microsoft YaHei"; padding: 0 4px; letter-spacing: 1px;
        """)
        row1.addWidget(title_label)
        row1.addSpacing(12)

        # 模式按钮组（壁纸+对话+角色扮演+文生视频+图生视频+语音系统）
        btn_group = QWidget()
        btn_group.setStyleSheet("""
            QWidget { background: rgba(255,255,255,0.05); border-radius: 8px;
                       border: 1px solid rgba(0,212,255,0.1); }
        """)
        btn_group_layout = QHBoxLayout(btn_group)
        btn_group_layout.setContentsMargins(2, 2, 2, 2)
        btn_group_layout.setSpacing(0)

        self.btn_wp_mode = QPushButton("🖼 壁纸")
        self.btn_wp_mode.setFixedSize(72, 28)
        self.btn_wp_mode.setCheckable(True)
        self.btn_wp_mode.setCursor(Qt.PointingHandCursor)
        self.btn_wp_mode.setStyleSheet(self._mode_btn_style(False))
        self.btn_wp_mode.clicked.connect(lambda: self._switch_mode("wallpaper"))
        btn_group_layout.addWidget(self.btn_wp_mode)

        self.btn_chat_mode = QPushButton("💬 对话")
        self.btn_chat_mode.setFixedSize(72, 28)
        self.btn_chat_mode.setCheckable(True)
        self.btn_chat_mode.setChecked(True)
        self.btn_chat_mode.setCursor(Qt.PointingHandCursor)
        self.btn_chat_mode.setStyleSheet(self._mode_btn_style(True))
        self.btn_chat_mode.clicked.connect(lambda: self._switch_mode("chat"))
        btn_group_layout.addWidget(self.btn_chat_mode)

        self.btn_rp_mode = QPushButton("🎭 角色扮演")
        self.btn_rp_mode.setFixedSize(88, 28)
        self.btn_rp_mode.setCheckable(True)
        self.btn_rp_mode.setCursor(Qt.PointingHandCursor)
        self.btn_rp_mode.setStyleSheet(self._mode_btn_style(False))
        self.btn_rp_mode.clicked.connect(lambda: self._switch_mode("rp"))
        btn_group_layout.addWidget(self.btn_rp_mode)

        self.btn_video_mode = QPushButton("🎬 文生视频")
        self.btn_video_mode.setFixedSize(88, 28)
        self.btn_video_mode.setCheckable(True)
        self.btn_video_mode.setCursor(Qt.PointingHandCursor)
        self.btn_video_mode.setStyleSheet(self._mode_btn_style(False))
        self.btn_video_mode.clicked.connect(lambda: self._switch_mode("video"))
        btn_group_layout.addWidget(self.btn_video_mode)

        self.btn_i2v_mode = QPushButton("🖼 图生视频")
        self.btn_i2v_mode.setFixedSize(88, 28)
        self.btn_i2v_mode.setCheckable(True)
        self.btn_i2v_mode.setCursor(Qt.PointingHandCursor)
        self.btn_i2v_mode.setStyleSheet(self._mode_btn_style(False))
        self.btn_i2v_mode.clicked.connect(lambda: self._switch_mode("video_i2v"))
        btn_group_layout.addWidget(self.btn_i2v_mode)

        self.btn_tts_mode = QPushButton("🎤 语音系统")
        self.btn_tts_mode.setFixedSize(88, 28)
        self.btn_tts_mode.setCheckable(True)
        self.btn_tts_mode.setCursor(Qt.PointingHandCursor)
        self.btn_tts_mode.setStyleSheet(self._mode_btn_style(False))
        self.btn_tts_mode.clicked.connect(lambda: self._switch_mode("tts"))
        btn_group_layout.addWidget(self.btn_tts_mode)

        row1.addWidget(btn_group)
        row1.addStretch()

        # 右上角状态 + WiFi + 最小化
        self.model_mode_label = QLabel("● 未连接")
        self.model_mode_label.setStyleSheet("""
            color: #888; font-size: 12px; padding: 3px 10px; border-radius: 10px;
            background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06);
        """)
        row1.addWidget(self.model_mode_label)
        row1.addSpacing(6)

        self.btn_mobile = QPushButton("📱 WiFi")
        self.btn_mobile.setFixedSize(64, 28)
        self.btn_mobile.setCursor(Qt.PointingHandCursor)
        self.btn_mobile.setToolTip("移动端访问 (WiFi)")
        self.btn_mobile.setStyleSheet("""
            QPushButton { background: rgba(0,212,255,0.08); color: #00d4ff;
                border: 1px solid rgba(0,212,255,0.4); border-radius: 6px;
                font-size: 12px; font-weight: 600; padding: 3px 6px; }
            QPushButton:hover { background: rgba(0,212,255,0.18); color: #fff; }
        """)
        self.btn_mobile.clicked.connect(self._open_web_server)
        row1.addWidget(self.btn_mobile)
        row1.addSpacing(2)

        self.btn_minimize_tray = QPushButton("➖")
        self.btn_minimize_tray.setFixedSize(28, 28)
        self.btn_minimize_tray.setCursor(Qt.PointingHandCursor)
        self.btn_minimize_tray.setToolTip("最小化到系统托盘")
        self.btn_minimize_tray.setStyleSheet("""
            QPushButton { background: rgba(255,255,255,0.04); color: #aaa;
                border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; font-size: 12px; }
            QPushButton:hover { background: rgba(255,255,255,0.12); color: #fff; }
        """)
        self.btn_minimize_tray.clicked.connect(self._minimize_to_tray)
        row1.addWidget(self.btn_minimize_tray)

        outer.addLayout(row1)

        # ---- 第二行：5个固定模型选择框（始终显示，不随选项卡切换） ----
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        # 💬 对话模型
        row2.addWidget(self._make_model_label("💬 对话:"))
        self.combo_chat = self._make_model_combo(self._on_chat_model_changed, 180)
        row2.addWidget(self.combo_chat)

        # 🎭 角色扮演模型
        row2.addWidget(self._make_model_label("🎭 角色:"))
        self.combo_rp = self._make_model_combo(self._on_rp_model_changed, 180)
        row2.addWidget(self.combo_rp)

        # 🎬 文生视频模型
        row2.addWidget(self._make_model_label("🎬 文生:"))
        self.combo_t2v = self._make_model_combo(self._on_t2v_model_changed, 130)
        row2.addWidget(self.combo_t2v)

        # 🖼 图生视频模型
        row2.addWidget(self._make_model_label("🖼 图生:"))
        self.combo_i2v = self._make_model_combo(self._on_i2v_model_changed, 130)
        row2.addWidget(self.combo_i2v)

        # 🎤 语音系统模型
        row2.addWidget(self._make_model_label("🎤 语音:"))
        self.combo_tts = self._make_model_combo(self._on_tts_model_changed, 170)
        row2.addWidget(self.combo_tts)

        row2.addStretch()

        outer.addLayout(row2)

        central_layout.addWidget(mode_bar)

        # 堆叠窗口 - 壁纸 / 对话 / 角色扮演 / 文生视频 / 图生视频 / 语音系统
        self.stack = QStackedWidget()

        # 🖼 壁纸与外观页面
        self.wallpaper_panel = WallpaperPanel()
        self.wallpaper_panel.wallpaper_changed.connect(self.apply_window_background)
        self.stack.addWidget(self.wallpaper_panel)

        # AI 对话面板
        llm_client = LLMClient()
        if self.llm_url:
            llm_client.base_url = self.llm_url
        self.ai_panel = AIPanel(
            llm_client=llm_client,
            workspace_path=self.workspace_path,
            server_manager=self.server_manager,
            system_monitor=self.system_monitor,
            charter_dir=self.charter_dir
        )
        self.stack.addWidget(self.ai_panel)

        # 角色扮演对话面板（专用：带角色栏，界面与普通对话一致）
        self.rp_panel = AIPanel(
            llm_client=llm_client,
            workspace_path=self.workspace_path,
            server_manager=self.server_manager,
            system_monitor=self.system_monitor,
            charter_dir=self.charter_dir,
            roleplay_mode=True
        )
        self.stack.addWidget(self.rp_panel)

        # 视频生成面板（文生视频 t2v）
        self.video_panel = VideoPanel(mode="t2v")
        self.stack.addWidget(self.video_panel)

        # 视频生成面板（图生视频 i2v）
        self.video_panel_i2v = VideoPanel(mode="i2v")
        self.stack.addWidget(self.video_panel_i2v)

        # 语音系统配置面板（GPT-SoVITS + CosyVoice）
        self.tts_panel = TTSPanel()
        self.stack.addWidget(self.tts_panel)

        central_layout.addWidget(self.stack, 1)

        self.setCentralWidget(central)

        # 状态栏
        self.statusBar = self.statusBar()
        self._statusbar_default_style = """
            QStatusBar {
                background: #16213e;
                border-top: 1px solid rgba(0, 212, 255, 0.1);
                color: #a0b0c0;
                font-size: 12px;
            }
        """
        self.statusBar.setStyleSheet(self._statusbar_default_style)
        self.status_label = QLabel("就绪")
        self.statusBar.addWidget(self.status_label)

        # 系统监控状态
        self.monitor_label = QLabel("💻 CPU: --  🧠 内存: --  🎮 GPU: --")
        self.monitor_label.setStyleSheet("color: #8aa0b0; padding: 0 12px; font-size: 12px;")
        self.statusBar.addPermanentWidget(self.monitor_label)

        # 模型状态
        self.model_label = QLabel("● 未连接")
        self.model_label.setStyleSheet("""
            color: #888;
            padding: 2px 12px;
            border-radius: 10px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.06);
            font-size: 12px;
        """)
        self.statusBar.addPermanentWidget(self.model_label)

        # 窗口级壁纸背景层（铺满整个窗口：顶栏/菜单栏/内容区/状态栏后面）
        from widgets.animated_bg import AnimatedBackground
        self.window_bg = AnimatedBackground(self)
        # 壁纸宽高比 → 自动调整窗口大小比例，使壁纸完整显示（不裁切）
        self.window_bg.aspectRatioChanged.connect(self._adapt_window_to_aspect)
        self.window_bg.lower()
        self.window_bg.hide()
        self.resizeEvent = self._window_resize  # 同步壁纸尺寸

        # 启动即应用主题：先让各面板按配置变透明，再铺窗口级壁纸
        if hasattr(self, "wallpaper_panel") and hasattr(self.wallpaper_panel, "apply_theme"):
            self.wallpaper_panel.apply_theme()
        if hasattr(self, "ai_panel") and hasattr(self.ai_panel, "apply_theme"):
            self.ai_panel.apply_theme()
        if hasattr(self, "rp_panel") and hasattr(self.rp_panel, "apply_theme"):
            self.rp_panel.apply_theme()
        if hasattr(self, "video_panel") and hasattr(self.video_panel, "reload_theme"):
            self.video_panel.reload_theme()
        if hasattr(self, "video_panel_i2v") and hasattr(self.video_panel_i2v, "reload_theme"):
            self.video_panel_i2v.reload_theme()
        if hasattr(self, "tts_panel") and hasattr(self.tts_panel, "apply_theme"):
            self.tts_panel.apply_theme()
        self.apply_window_background()
        self.apply_text_transparency()

        # 默认显示对话面板（壁纸面板是第一个 stack widget，但用户默认要对话）
        self._init_model_combos()  # 先填充5个固定下拉
        self._switch_mode("chat")
        # 互动壁纸透视圈由 AnimatedBackground 内部轮询 QCursor 驱动（Qt 不给
        # 未开 mouseTracking 的控件发 MouseMove，事件过滤器方案不可靠，已废弃）

    def _adapt_window_to_aspect(self, ratio: float):
        """按壁纸宽高比调整窗口尺寸（在屏幕可用区内取最大适配值）并居中"""
        try:
            if ratio <= 0:
                return
            screen = QApplication.primaryScreen().availableGeometry()
            margin = 40  # 留出任务栏/边框余量
            avail_w = screen.width() - margin
            avail_h = screen.height() - margin
            w = min(avail_w, int(avail_h * ratio))
            h = int(w / ratio)
            if w > 0 and h > 0:
                self.showNormal()  # 若处于最大化则先还原，避免 resize 失效
                self.resize(w, h)
                self.move(screen.x() + (screen.width() - w) // 2,
                          screen.y() + (screen.height() - h) // 2)
        except Exception:
            pass

    def _window_resize(self, event):
        QMainWindow.resizeEvent(self, event)
        if hasattr(self, "window_bg"):
            self.window_bg.setGeometry(self.rect())

    def apply_window_background(self):
        """把对话壁纸渲染到整个窗口（含顶栏/菜单栏/状态栏），并应用界面前端透明度"""
        import os
        from PyQt5.QtWidgets import QGraphicsOpacityEffect
        theme = self.cfg.get("theme", {})
        img = theme.get("chat_bg_image", "")
        bg_color = theme.get("chat_bg_color", "#16213e")
        opacity = 1.0  # 壁纸始终不透明；透明度概念只作用于文字与前端
        ui_t = max(0, min(100, theme.get("ui_transparency", 50)))
        ui_opacity = 1.0 - ui_t / 100.0

        if img and os.path.exists(img):
            self.window_bg.set_background(img, bg_color, opacity)
            self.window_bg.setGeometry(self.rect())
            self.window_bg.show()
            self.window_bg.lower()
            # 前端面板：顶栏用半透明黑底（和下方内容一致的观感），其余透明让壁纸透出
            self.mode_bar.setStyleSheet(
                "QWidget { background: rgba(18, 18, 28, 0.72);"
                " border-bottom: 1px solid rgba(0, 212, 255, 0.15); }")
            self.statusBar.setStyleSheet(
                "QStatusBar { background: transparent; color: #a0b0c0; font-size: 12px; }")
            self.menuBar().setStyleSheet(
                "QMenuBar { background: transparent; }"
                "QMenuBar::item { background: transparent; }"
                "QMenu { background: #2d2d3a; color: #d4d4d4; border: 1px solid #3a3a44; }")
            self.centralWidget().setStyleSheet("background: transparent;")
        else:
            self.window_bg.clear()
            self.window_bg.hide()
            self.mode_bar.setStyleSheet(self._mode_bar_default_style)
            self.statusBar.setStyleSheet(self._statusbar_default_style)
            self.menuBar().setStyleSheet("")
            self.centralWidget().setStyleSheet("")

        # 界面前端透明度（顶栏/菜单栏/状态栏/对话内容层统一淡出，100% 只剩壁纸）
        for w in (self.mode_bar, self.statusBar, self.menuBar()):
            if not hasattr(w, "_ui_opacity_effect"):
                w._ui_opacity_effect = QGraphicsOpacityEffect(w)
                w.setGraphicsEffect(w._ui_opacity_effect)
            w._ui_opacity_effect.setOpacity(ui_opacity)
        for panel_attr in ("ai_panel", "rp_panel", "video_panel", "video_panel_i2v", "tts_panel", "wallpaper_panel"):
            p = getattr(self, panel_attr, None)
            if p and hasattr(p, "set_ui_opacity"):
                p.set_ui_opacity(ui_opacity)

        # 互动壁纸激活自证：状态栏提示透视层已就绪
        if img and os.path.exists(img) and getattr(self.window_bg, "_video_source2", ""):
            if hasattr(self, "status_label"):
                self.status_label.setText(
                    f"互动壁纸已激活：移动鼠标查看透视层（{os.path.basename(self.window_bg._video_source2)}）")

    def _mode_btn_style(self, active: bool) -> str:
        if active:
            return """
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #007acc, stop:1 #00d4ff);
                    color: #ffffff; border: none; border-radius: 6px; font-size: 12px;
                    font-weight: 700; font-family: "Microsoft YaHei"; padding: 5px 10px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0a8bde, stop:1 #1fe0ff);
                }
            """
        else:
            return """
                QPushButton {
                    background: transparent; color: #8aa0b0; border: none; border-radius: 6px;
                    font-size: 12px; font-family: "Microsoft YaHei"; padding: 5px 10px;
                }
                QPushButton:hover {
                    color: #c0d8e8; background: rgba(255, 255, 255, 0.08);
                }
            """

    def _row_combo_style(self) -> str:
        """第二行模型下拉框样式（深色模式下必须醒目可见）"""
        return ("QComboBox { background: rgba(30,30,46,0.95); color: #e0f0ff;"
                " border: 1px solid rgba(0,212,255,0.6); border-radius: 4px;"
                " padding: 2px 6px; min-height: 20px; font-size: 11px;"
                " selection-background-color: rgba(0,122,204,0.4); }"
                "QComboBox:hover { border-color: #00d4ff; background: rgba(0,212,255,0.15); }"
                "QComboBox::drop-down { border: none; width: 18px;"
                " background: rgba(0,212,255,0.2); border-left: 1px solid rgba(0,212,255,0.6); }"
                "QComboBox QAbstractItemView { background: #1a1a2e; color: #e0f0ff;"
                " border: 1px solid rgba(0,212,255,0.5);"
                " selection-background-color: rgba(0,212,255,0.3); outline: 0;"
                " font-size: 11px; padding: 2px; }")

    def _make_model_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #8aa0b0; font-size: 11px;")
        return lbl

    def _make_model_combo(self, signal_cb, width: int) -> QComboBox:
        combo = QComboBox()
        combo.setFixedWidth(width)
        combo.setStyleSheet(self._row_combo_style())
        combo.currentIndexChanged.connect(signal_cb)
        return combo

    # ============================================================
    # 5个固定模型下拉：填充 + 回调（始终存在，不随选项卡切换）
    # ============================================================

    def _init_model_combos(self):
        """程序启动时一次性填充5个下拉框"""
        self._fill_llm_combo(self.combo_chat)
        self._fill_llm_combo(self.combo_rp)
        self._fill_video_combo(self.combo_t2v, "t2v")
        self._fill_video_combo(self.combo_i2v, "i2v")
        self._fill_tts_combo(self.combo_tts)

    def _fill_llm_combo(self, combo: QComboBox):
        """填充 LLM 对话模型下拉（只显示 path 存在的 local + sdk）"""
        combo.blockSignals(True)
        combo.clear()
        models = self.cfg.get("models", [])
        local_models = []
        sdk_models = []
        for m in models:
            mtype = m.get("type", "")
            path = m.get("path", "")
            if mtype == "local":
                # 必须有 path 且文件存在
                if path and os.path.exists(path):
                    local_models.append(m)
            elif mtype == "sdk":
                sdk_models.append(m)

        for m in local_models:
            size = m.get("size_mb", 0)
            size_str = f" ({size//1024}GB)" if size >= 1024 else f" ({size}MB)" if size else ""
            combo.addItem(f"💻 {m.get('name', '未命名')}{size_str}", m.get("id"))
        for m in sdk_models:
            combo.addItem(f"☁️ {m.get('name', '未命名')}", m.get("id"))

        if combo.count() == 0:
            combo.addItem("（未找到本地模型，请检查 models/ 目录）", "")
        # 选中当前模型
        try:
            cur = self.cfg.get_current_model()
            if cur:
                idx = combo.findData(cur.get("id"))
                if idx >= 0:
                    combo.setCurrentIndex(idx)
        except Exception:
            pass
        combo.blockSignals(False)

    def _fill_video_combo(self, combo: QComboBox, mode: str):
        """填充视频模型下拉"""
        combo.blockSignals(True)
        combo.clear()
        workflows = self.cfg.get("comfyui.workflows", [])
        for w in workflows:
            combo.addItem(w.get("name", "未命名"), w.get("id", w.get("name", "")))
        if combo.count() == 0:
            combo.addItem("Sulphur 2", "ltx23_sulphur2")
        # 选中当前
        cur = self.cfg.get("comfyui.model_source", "")
        if cur:
            idx = combo.findText(cur)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _fill_tts_combo(self, combo: QComboBox):
        """填充 TTS 引擎下拉"""
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("🎤 CosyVoice", "cosyvoice")
        combo.addItem("🎤 GPT-SoVITS-v2pro", "gpt_sovits")
        cur = self.cfg.get("tts_engine", "gpt_sovits")
        idx = combo.findData(cur)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    # ---- 回调 ----

    def _on_chat_model_changed(self, idx: int):
        data = self.combo_chat.currentData()
        if not data:
            return
        try:
            models = self.cfg.get("models", [])
            for m in models:
                if m.get("id") == data:
                    self.cfg.set("current_model_id", data)
                    self.cfg.save()
                    self._on_server_status_changed("starting")
                    if hasattr(self.ai_panel, '_restart_server_if_running'):
                        self.ai_panel._restart_server_if_running()
                    self.status_label.setText(f"💬 对话模型已切换: {m.get('name')}")
                    break
        except Exception as e:
            self.status_label.setText(f"切换对话模型失败: {e}")

    def _on_rp_model_changed(self, idx: int):
        data = self.combo_rp.currentData()
        if not data:
            return
        # 角色扮演共用对话模型池
        self._on_chat_model_changed(idx)

    def _on_t2v_model_changed(self, idx: int):
        data = self.combo_t2v.currentData()
        if not data:
            return
        self.cfg.set("comfyui.model_source", data)
        self.cfg.save()
        if hasattr(self.video_panel, 'reload_theme'):
            self.video_panel.reload_theme()
        self.status_label.setText(f"🎬 文生视频模型已切换: {data}")

    def _on_i2v_model_changed(self, idx: int):
        data = self.combo_i2v.currentData()
        if not data:
            return
        self.cfg.set("comfyui.model_source", data)
        self.cfg.save()
        if hasattr(self.video_panel_i2v, 'reload_theme'):
            self.video_panel_i2v.reload_theme()
        self.status_label.setText(f"🖼 图生视频模型已切换: {data}")

    def _on_tts_model_changed(self, idx: int):
        data = self.combo_tts.currentData()
        if not data:
            return
        self.cfg.set("tts_engine", data)
        self.cfg.save()
        if hasattr(self.tts_panel, '_on_engine_changed'):
            self.tts_panel._on_engine_changed(0 if data == "cosyvoice" else 1)
        # 通知两个 AIPanel 刷新按钮行
        for panel in (self.ai_panel, self.rp_panel):
            if panel is not None and hasattr(panel, '_refresh_tts_btn_row'):
                panel._refresh_tts_btn_row()
        self.status_label.setText(f"🎤 语音引擎已切换: {data}")

    # ============================================================
    # 模式切换（重写）
    # ============================================================

    def _switch_mode(self, mode: str):
        """切换模式"""
        if mode == self._current_mode:
            return

        self._current_mode = mode

        # 重置所有按钮样式
        self.btn_wp_mode.setChecked(False); self.btn_wp_mode.setStyleSheet(self._mode_btn_style(False))
        self.btn_chat_mode.setChecked(False); self.btn_chat_mode.setStyleSheet(self._mode_btn_style(False))
        self.btn_rp_mode.setChecked(False); self.btn_rp_mode.setStyleSheet(self._mode_btn_style(False))
        self.btn_video_mode.setChecked(False); self.btn_video_mode.setStyleSheet(self._mode_btn_style(False))
        self.btn_i2v_mode.setChecked(False); self.btn_i2v_mode.setStyleSheet(self._mode_btn_style(False))
        self.btn_tts_mode.setChecked(False); self.btn_tts_mode.setStyleSheet(self._mode_btn_style(False))

        if mode == "wallpaper":
            self.stack.setCurrentWidget(self.wallpaper_panel)
            self.btn_wp_mode.setChecked(True); self.btn_wp_mode.setStyleSheet(self._mode_btn_style(True))
            self.setWindowTitle("A Small Local AI Runner - 壁纸与外观")
            self.status_label.setText("壁纸与外观模式")
        elif mode == "chat":
            self.stack.setCurrentWidget(self.ai_panel)
            self.btn_chat_mode.setChecked(True); self.btn_chat_mode.setStyleSheet(self._mode_btn_style(True))
            self.setWindowTitle("A Small Local AI Runner - 对话")
            self.status_label.setText("对话模式")
        elif mode == "rp":
            self.stack.setCurrentWidget(self.rp_panel)
            self.btn_rp_mode.setChecked(True); self.btn_rp_mode.setStyleSheet(self._mode_btn_style(True))
            self.setWindowTitle("A Small Local AI Runner - 角色扮演对话模式")
            self.status_label.setText("角色扮演对话模式")
        elif mode == "video_i2v":
            self.stack.setCurrentWidget(self.video_panel_i2v)
            self.btn_i2v_mode.setChecked(True); self.btn_i2v_mode.setStyleSheet(self._mode_btn_style(True))
            self.setWindowTitle("A Small Local AI Runner - 图生视频")
            self.status_label.setText("图生视频模式")
        elif mode == "tts":
            self.stack.setCurrentWidget(self.tts_panel)
            self.btn_tts_mode.setChecked(True); self.btn_tts_mode.setStyleSheet(self._mode_btn_style(True))
            self.setWindowTitle("A Small Local AI Runner - 语音系统")
            self.status_label.setText("语音系统模式")
        else:  # video
            self.stack.setCurrentWidget(self.video_panel)
            self.btn_video_mode.setChecked(True); self.btn_video_mode.setStyleSheet(self._mode_btn_style(True))
            self.setWindowTitle("A Small Local AI Runner - 文生视频")
            self.status_label.setText("文生视频模式")

        # 联动第二行动态模型下拉（5个固定下拉不随选项卡切换，无需刷新）
        pass

    def _init_menu(self):
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")

        open_folder_action = QAction("打开文件夹...", self)
        open_folder_action.setShortcut(QKeySequence("Ctrl+K, Ctrl+O"))
        open_folder_action.triggered.connect(self.open_folder_dialog)
        file_menu.addAction(open_folder_action)

        file_menu.addSeparator()

        settings_action = QAction("设置...", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self.open_settings)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 视图菜单
        view_menu = menubar.addMenu("视图(&V)")

        wp_mode_action = QAction("壁纸与外观", self)
        wp_mode_action.setShortcut(QKeySequence("Ctrl+0"))
        wp_mode_action.triggered.connect(lambda: self._switch_mode("wallpaper"))
        view_menu.addAction(wp_mode_action)

        chat_mode_action = QAction("对话模式", self)
        chat_mode_action.setShortcut(QKeySequence("Ctrl+1"))
        chat_mode_action.triggered.connect(lambda: self._switch_mode("chat"))
        view_menu.addAction(chat_mode_action)

        rp_mode_action = QAction("角色扮演对话模式", self)
        rp_mode_action.setShortcut(QKeySequence("Ctrl+2"))
        rp_mode_action.triggered.connect(lambda: self._switch_mode("rp"))
        view_menu.addAction(rp_mode_action)

        video_mode_action = QAction("文生视频模式", self)
        video_mode_action.setShortcut(QKeySequence("Ctrl+3"))
        video_mode_action.triggered.connect(lambda: self._switch_mode("video"))
        view_menu.addAction(video_mode_action)

        i2v_mode_action = QAction("图生视频模式", self)
        i2v_mode_action.setShortcut(QKeySequence("Ctrl+4"))
        i2v_mode_action.triggered.connect(lambda: self._switch_mode("video_i2v"))
        view_menu.addAction(i2v_mode_action)

        tts_mode_action = QAction("语音系统模式", self)
        tts_mode_action.setShortcut(QKeySequence("Ctrl+5"))
        tts_mode_action.triggered.connect(lambda: self._switch_mode("tts"))
        view_menu.addAction(tts_mode_action)

        view_menu.addSeparator()

        toggle_fullscreen = QAction("全屏", self)
        toggle_fullscreen.setShortcut(QKeySequence("F11"))
        toggle_fullscreen.triggered.connect(self._toggle_fullscreen)
        view_menu.addAction(toggle_fullscreen)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于 A Small Local AI Runner", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _init_signals(self):
        # 系统监控信号
        self.system_monitor.stats_updated.connect(self._on_stats_updated)

        # 服务状态变化信号
        self.server_manager.status_changed.connect(self._on_server_status_changed)

        # TTS 服务状态 → 刷新两个 AIPanel 的启停按钮文字
        def _refresh_tts_btns(status):
            for panel in (self.ai_panel, self.rp_panel):
                if panel is not None and hasattr(panel, '_update_tts_svc_btn_text'):
                    panel._update_tts_svc_btn_text()

        try:
            from core.gpt_sovits_server_manager import get_gpt_sovits_server_manager
            get_gpt_sovits_server_manager().status_changed.connect(_refresh_tts_btns)
        except Exception:
            pass
        try:
            from core.tts_server_manager import get_tts_server_manager
            get_tts_server_manager().status_changed.connect(_refresh_tts_btns)
        except Exception:
            pass

        # AI 面板的工作区请求
        if hasattr(self.ai_panel, 'workspace_requested'):
            self.ai_panel.workspace_requested.connect(self.open_folder_dialog)

        # 对话面板「➕ 新建角色」→ 跳转角色扮演选项卡并打开创建向导
        if hasattr(self.ai_panel, 'roleplay_requested'):
            self.ai_panel.roleplay_requested.connect(self._open_roleplay_new_character)
            # 配置 GPT-SoVITS 按钮 → 跳转到语音系统页面
            for panel in (self.ai_panel, self.rp_panel):
                if hasattr(panel, 'gs_config_requested'):
                    panel.gs_config_requested.connect(lambda: self._switch_mode("tts"))

    def _update_title(self):
        folder_name = os.path.basename(self.workspace_path.rstrip(os.sep)) or "未选择"
        mode_name = {"wallpaper": "壁纸与外观", "chat": "对话", "rp": "角色扮演对话模式",
                     "video": "文生视频", "video_i2v": "图生视频", "tts": "语音系统"}.get(self._current_mode, "对话")
        self.setWindowTitle(f"A Small Local AI Runner - {mode_name} - {folder_name}")

    def _on_stats_updated(self, stats: dict):
        cpu = stats.get("cpu", 0)
        mem = stats.get("memory", 0)
        gpu = stats.get("gpu", 0)
        self.monitor_label.setText(
            f"💻 CPU: {cpu:.0f}%  🧠 内存: {mem:.0f}%  🎮 GPU: {gpu:.0f}%"
        )

    def _on_server_status_changed(self, status: str):
        """服务状态变化回调 - 更新状态栏和顶部模型状态"""
        if status == "running":
            self.model_label.setText("● 已连接")
            self.model_label.setStyleSheet("""
                color: #4caf50;
                padding: 2px 12px;
                border-radius: 10px;
                background: rgba(76, 175, 80, 0.1);
                border: 1px solid rgba(76, 175, 80, 0.3);
                font-size: 12px;
            """)
            self.model_mode_label.setText("● 已连接")
            self.model_mode_label.setStyleSheet("""
                color: #4caf50;
                font-size: 12px;
                padding: 4px 10px;
                border-radius: 10px;
                background: rgba(76, 175, 80, 0.1);
                border: 1px solid rgba(76, 175, 80, 0.3);
            """)
        elif status == "starting":
            self.model_label.setText("● 启动中...")
            self.model_label.setStyleSheet("""
                color: #ff9800;
                padding: 2px 12px;
                border-radius: 10px;
                background: rgba(255, 152, 0, 0.1);
                border: 1px solid rgba(255, 152, 0, 0.3);
                font-size: 12px;
            """)
            self.model_mode_label.setText("● 启动中...")
            self.model_mode_label.setStyleSheet("""
                color: #ff9800;
                font-size: 12px;
                padding: 4px 10px;
                border-radius: 10px;
                background: rgba(255, 152, 0, 0.1);
                border: 1px solid rgba(255, 152, 0, 0.3);
            """)
        elif status == "stopping":
            self.model_label.setText("● 停止中...")
            self.model_label.setStyleSheet("""
                color: #ff9800;
                padding: 2px 12px;
                border-radius: 10px;
                background: rgba(255, 152, 0, 0.1);
                border: 1px solid rgba(255, 152, 0, 0.3);
                font-size: 12px;
            """)
            self.model_mode_label.setText("● 停止中...")
            self.model_mode_label.setStyleSheet("""
                color: #ff9800;
                font-size: 12px;
                padding: 4px 10px;
                border-radius: 10px;
                background: rgba(255, 152, 0, 0.1);
                border: 1px solid rgba(255, 152, 0, 0.3);
            """)
        else:
            self.model_label.setText("● 未连接")
            self.model_label.setStyleSheet("""
                color: #888;
                padding: 2px 12px;
                border-radius: 10px;
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.06);
                font-size: 12px;
            """)
            self.model_mode_label.setText("● 未连接")
            self.model_mode_label.setStyleSheet("""
                color: #888;
                font-size: 12px;
                padding: 4px 10px;
                border-radius: 10px;
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.06);
            """)

    def _on_model_status_changed(self, status: str, model_name: str = ""):
        if status == "connected":
            self.model_label.setText(f"● {model_name}")
            self.model_label.setStyleSheet("""
                color: #4caf50;
                padding: 2px 12px;
                border-radius: 10px;
                background: rgba(76, 175, 80, 0.1);
                border: 1px solid rgba(76, 175, 80, 0.3);
                font-size: 12px;
            """)
        elif status == "connecting":
            self.model_label.setText("● 连接中...")
            self.model_label.setStyleSheet("""
                color: #ff9800;
                padding: 2px 12px;
                border-radius: 10px;
                background: rgba(255, 152, 0, 0.1);
                border: 1px solid rgba(255, 152, 0, 0.3);
                font-size: 12px;
            """)
        else:
            self.model_label.setText("● 未连接")
            self.model_label.setStyleSheet("""
                color: #888;
                padding: 2px 12px;
                border-radius: 10px;
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.06);
                font-size: 12px;
            """)

    def open_folder_dialog(self):
        """打开文件夹作为项目目录"""
        folder = QFileDialog.getExistingDirectory(self, "选择项目文件夹", self.workspace_path)
        if folder:
            self._switch_workspace(folder)

    def _switch_workspace(self, new_path: str):
        """切换工作区"""
        self.workspace_path = new_path
        self.cfg.set("workspace_path", new_path)
        self.cfg.save()
        self._update_title()

        # 通知 AI 面板
        if hasattr(self.ai_panel, 'set_workspace_path'):
            self.ai_panel.set_workspace_path(new_path)

        self.status_label.setText(f"已打开: {new_path}")

    def apply_text_transparency(self):
        """文字透明度（theme.text_opacity 0-100）：作用于所有文字，不影响壁纸/面板底色。
        滑条代表最终效果，自动补偿界面前端透明度（QGraphicsOpacityEffect）的衰减。"""
        try:
            from core.text_opacity import apply_text_opacity, effective_text_alpha
            apply_text_opacity(effective_text_alpha())
        except Exception:
            pass
        # 消息文字统一走 ai_panel（带补偿后的 alpha）
        if hasattr(self.ai_panel, "apply_text_colors"):
            self.ai_panel.apply_text_colors()
        if hasattr(self, "rp_panel") and hasattr(self.rp_panel, "apply_text_colors"):
            self.rp_panel.apply_text_colors()

    def open_settings(self):
        # 记录打开前的当前模型，保存后若换了模型且服务在跑，自动重启加载新模型
        prev_model_id = None
        try:
            prev = self.cfg.get_current_model()
            prev_model_id = prev.get("id") if prev else None
        except Exception:
            pass

        dialog = SettingsDialog(self)
        if dialog.exec_():
            self.status_label.setText("设置已保存")
            # 通知各面板重新加载主题
            for panel_attr in ("wallpaper_panel", "ai_panel", "rp_panel"):
                p = getattr(self, panel_attr, None)
                if p and hasattr(p, 'apply_theme'):
                    p.apply_theme()
            for panel_attr in ("video_panel", "video_panel_i2v"):
                p = getattr(self, panel_attr, None)
                if p and hasattr(p, 'reload_theme'):
                    p.reload_theme()
            if hasattr(self, 'tts_panel') and hasattr(self.tts_panel, 'apply_theme'):
                self.tts_panel.apply_theme()
            # 刷新窗口级壁纸与前端透明度
            self.apply_window_background()
            self.apply_text_transparency()
            # 模型发生变化且服务正在运行：自动重启加载新模型
            try:
                cur = self.cfg.get_current_model()
                cur_id = cur.get("id") if cur else None
                if cur_id and cur_id != prev_model_id:
                    if hasattr(self.ai_panel, '_restart_server_if_running'):
                        self.ai_panel._restart_server_if_running()
            except Exception:
                pass

    def _open_roleplay_new_character(self):
        """对话面板点「➕ 新建角色」：切换到角色扮演选项卡并打开创建向导"""
        self._switch_mode("rp")
        if hasattr(self, "rp_panel") and self.rp_panel.character_manager:
            self.rp_panel._add_character()

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _show_about(self):
        QMessageBox.about(
            self, "关于 A Small Local AI Runner",
            "<h3>A Small Local AI Runner</h3>"
            "<p>本地 AI 编程助手</p>"
            "<p>💬 AI 对话 &nbsp; 🎬 视频生成 &nbsp; 📱 移动端访问</p>"
            "<p>基于 llama.cpp + PyQt5 + ComfyUI</p>"
        )

    def _open_web_server(self):
        """打开 Web 服务对话框"""
        if self.web_dialog is None:
            # 获取 LLM 基础 URL
            llm_url = "http://127.0.0.1:8080"
            if self.server_manager and self.server_manager.status == "running":
                llm_url = f"http://127.0.0.1:{self.server_manager.port}"
            elif hasattr(self.cfg, 'get'):
                model = self.cfg.get_current_model() if hasattr(self.cfg, 'get_current_model') else None
                if model and model.get("type") == "sdk":
                    llm_url = model.get("base_url", "http://127.0.0.1:8080")

            self.web_dialog = WebServerDialog(
                charter_dir=self.charter_dir,
                llm_base_url=llm_url,
                server_manager=self.server_manager,
                system_monitor=self.system_monitor,
                parent=self
            )
        self.web_dialog.show()
        self.web_dialog.raise_()
        self.web_dialog.activateWindow()

    # ========== 系统托盘 ==========
    def _init_tray(self):
        """初始化系统托盘"""
        icon_path = os.path.join(os.path.dirname(__file__), "assets", "tray_icon.png")
        
        # 创建托盘图标（透明图标用于隐藏）
        self.tray_icon = QSystemTrayIcon(self)
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            # 备用：创建一个极小的透明图标
            pixmap = QPixmap(16, 16)
            pixmap.fill(Qt.transparent)
            self.tray_icon.setIcon(QIcon(pixmap))

        # 托盘菜单
        tray_menu = QMenu()
        
        show_action = tray_menu.addAction("显示主窗口")
        show_action.triggered.connect(self._restore_from_tray)
        
        tray_menu.addSeparator()
        
        quit_action = tray_menu.addAction("退出")
        quit_action.triggered.connect(self._quit_app)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.setToolTip("A Small Local AI Runner")
        
        # 双击托盘图标显示/隐藏
        self.tray_icon.activated.connect(self._on_tray_activated)
        
        self.tray_icon.show()

    def _minimize_to_tray(self):
        """最小化到系统托盘"""
        self.hide()
        self.tray_icon.showMessage(
            "A Small Local AI Runner",
            "已最小化到系统托盘",
            QSystemTrayIcon.Information,
            2000
        )

    def _restore_from_tray(self):
        """从托盘恢复窗口"""
        self.show()
        self.activateWindow()
        self.raise_()

    def _on_tray_activated(self, reason):
        """托盘图标激活事件"""
        if reason == QSystemTrayIcon.DoubleClick:
            if self.isVisible():
                self._minimize_to_tray()
            else:
                self._restore_from_tray()

    def _quit_app(self):
        """完全退出应用"""
        # 停止 CosyVoice TTS 服务（防孤儿进程，atexit 另有兜底）
        try:
            from core.tts_server_manager import get_tts_server_manager
            get_tts_server_manager().stop_service()
        except Exception:
            pass
        # 停止 GPT-SoVITS 服务
        try:
            from core.gpt_sovits_server_manager import get_gpt_sovits_server_manager
            get_gpt_sovits_server_manager().stop_service()
        except Exception:
            pass
        self.tray_icon.hide()
        QApplication.instance().quit()

    def closeEvent(self, event):
        """关闭事件 - 改为最小化到托盘"""
        event.ignore()
        self._minimize_to_tray()
