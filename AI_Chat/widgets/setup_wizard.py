"""
ComfyUI 设置向导 - 四步引导式配置
"""
import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QProgressBar, QListWidget, QListWidgetItem,
    QStackedWidget, QWidget, QMessageBox, QSpinBox, QGroupBox, QFormLayout,
    QScrollArea, QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap, QFont, QIcon

from core.config import get_config_manager
from core.model_manager import check_models, copy_models, verify_comfyui_exe, verify_download_folder, get_source_folder


def get_asset_path(filename: str) -> str:
    """获取资源文件路径"""
    assets_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    return os.path.join(assets_dir, filename)


def _find_best_screenshot(base_name: str) -> str:
    """
    找到最佳质量的截图（优先 _full 版本，然后 png，然后 webp）
    返回完整路径，如果都不存在返回空字符串
    """
    assets_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    candidates = [
        f"{base_name}_full.png",
        f"{base_name}.png",
        f"{base_name}_full.webp",
        f"{base_name}.webp",
    ]
    for name in candidates:
        path = os.path.join(assets_dir, name)
        if os.path.exists(path):
            return path
    return ""


def _load_screenshot(label: QLabel, base_name: str, max_width: int = 640):
    """加载截图到 QLabel，自动选择最佳版本"""
    path = _find_best_screenshot(base_name)
    if path:
        pix = QPixmap(path)
        label.setPixmap(pix.scaledToWidth(max_width, Qt.SmoothTransformation))
    else:
        label.setText("（截图未找到）")


class CopyWorker(QThread):
    """后台复制文件线程"""
    progress = pyqtSignal(str, int, int)  # 名称, 当前, 总数
    finished_ok = pyqtSignal(bool, str, list)  # 成功, 消息, 结果列表

    def __init__(self, download_folder: str, model_source: str):
        super().__init__()
        self.download_folder = download_folder
        self.model_source = model_source

    def run(self):
        def on_progress(name, idx, total):
            self.progress.emit(name, idx, total)

        ok, msg, results = copy_models(
            self.download_folder,
            self.model_source,
            progress_callback=on_progress
        )
        self.finished_ok.emit(ok, msg, results)


class SetupWizard(QDialog):
    """ComfyUI 视频生成设置向导（四步）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = get_config_manager()
        self.current_step = 0
        self._copy_worker = None
        self._init_ui()
        self._load_config()

    def _init_ui(self):
        self.setWindowTitle("🎬 视频生成设置向导")
        self.setMinimumSize(720, 640)
        self.setStyleSheet("""
            QDialog { background: #1e1e1e; }
            QLabel { color: #cccccc; font-family: "Microsoft YaHei"; }
            QLabel#stepTitle { color: #ffffff; font-size: 18px; font-weight: bold; }
            QLabel#stepDesc { color: #888; font-size: 12px; }
            QPushButton {
                background: #0e639c; color: white; border: none;
                padding: 8px 20px; border-radius: 4px; font-size: 12px;
                font-family: "Microsoft YaHei";
            }
            QPushButton:hover { background: #1177bb; }
            QPushButton:disabled { background: #3a3a3a; color: #666; }
            QPushButton#secondary {
                background: #3a3a3a;
            }
            QPushButton#secondary:hover { background: #4a4a4a; }
            QLineEdit {
                background: #252526; color: #ccc; border: 1px solid #3c3c3c;
                padding: 6px 10px; border-radius: 4px; font-size: 12px;
            }
            QLineEdit:focus { border-color: #007acc; }
            QGroupBox {
                color: #ccc; border: 1px solid #3c3c3c; border-radius: 6px;
                margin-top: 12px; padding-top: 16px; font-weight: bold;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
            QSpinBox {
                background: #252526; color: #ccc; border: 1px solid #3c3c3c;
                padding: 4px 8px; border-radius: 4px;
            }
            QListWidget {
                background: #252526; color: #ccc; border: 1px solid #3c3c3c;
                border-radius: 6px; padding: 4px;
            }
            QListWidget::item { padding: 8px; border-radius: 4px; }
            QListWidget::item:selected { background: #094771; }
            QProgressBar {
                border: 1px solid #3c3c3c; border-radius: 4px;
                background: #252526; text-align: center; color: #fff;
                height: 20px;
            }
            QProgressBar::chunk { background: #007acc; border-radius: 3px; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)

        # 顶部：步骤指示器
        self.step_indicator = QLabel()
        self.step_indicator.setAlignment(Qt.AlignCenter)
        self.step_indicator.setStyleSheet("""
            QLabel { color: #007acc; font-size: 13px; font-weight: bold;
                     padding: 8px; background: #252526; border-radius: 6px; }
        """)
        layout.addWidget(self.step_indicator)

        # 步骤内容区域
        self.stacked = QStackedWidget()
        layout.addWidget(self.stacked, 1)

        # 创建4个步骤页面
        self.stacked.addWidget(self._create_step1())
        self.stacked.addWidget(self._create_step2())
        self.stacked.addWidget(self._create_step3())
        self.stacked.addWidget(self._create_step4())

        # 底部按钮
        btn_layout = QHBoxLayout()
        self.prev_btn = QPushButton("◀ 上一步")
        self.prev_btn.setObjectName("secondary")
        self.prev_btn.clicked.connect(self._prev_step)
        self.next_btn = QPushButton("下一步 ▶")
        self.next_btn.clicked.connect(self._next_step)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("secondary")
        self.cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.prev_btn)
        btn_layout.addWidget(self.next_btn)
        layout.addLayout(btn_layout)

        self._update_step_ui()

    # ========== 步骤 1：ComfyUI 可执行文件 ==========

    def _create_step1(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("第 1 步：指定 ComfyUI 可执行文件")
        title.setObjectName("stepTitle")
        layout.addWidget(title)

        desc = QLabel("找到你的 ComfyUI 桌面版启动程序（.exe 或 .bat）")
        desc.setObjectName("stepDesc")
        layout.addWidget(desc)

        # 截图说明
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(200)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #3c3c3c; border-radius: 6px; background: #252526; }")
        img_label = QLabel()
        _load_screenshot(img_label, "step1_comfyui_exe", 640)
        img_label.setAlignment(Qt.AlignCenter)
        scroll.setWidget(img_label)
        layout.addWidget(scroll)

        # 文件选择
        file_group = QGroupBox("ComfyUI 启动文件")
        fl = QFormLayout(file_group)
        fl.setSpacing(10)

        row = QHBoxLayout()
        self.exe_edit = QLineEdit()
        self.exe_edit.setPlaceholderText("例如：C:\\ComfyUI\\ComfyUI.exe")
        browse_btn = QPushButton("浏览...")
        browse_btn.setFixedWidth(72)
        browse_btn.clicked.connect(self._browse_exe)
        row.addWidget(self.exe_edit, 1)
        row.addWidget(browse_btn)
        w = QWidget()
        w.setLayout(row)
        fl.addRow("文件路径：", w)

        self.exe_status = QLabel("尚未选择")
        self.exe_status.setStyleSheet("color: #888; font-size: 11px;")
        fl.addRow("状态：", self.exe_status)

        layout.addWidget(file_group)

        # 服务器地址
        addr_group = QGroupBox("服务器设置")
        al = QFormLayout(addr_group)
        al.setSpacing(10)
        self.addr_edit = QLineEdit()
        self.addr_edit.setPlaceholderText("127.0.0.1:8188")
        al.addRow("服务地址：", self.addr_edit)
        layout.addWidget(addr_group)

        layout.addStretch()
        return page

    def _browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 ComfyUI 可执行文件", "",
            "可执行文件 (*.exe *.bat *.cmd);;所有文件 (*.*)"
        )
        if path:
            self.exe_edit.setText(path)
            self._check_exe()

    def _check_exe(self):
        path = self.exe_edit.text().strip()
        ok, msg = verify_comfyui_exe(path)
        if ok:
            self.exe_status.setText(f"✅ {msg}")
            self.exe_status.setStyleSheet("color: #4ec9b0; font-size: 11px;")
            self._save_partial()  # 立即保存
        else:
            self.exe_status.setText(f"⚠️ {msg}")
            self.exe_status.setStyleSheet("color: #dcdcaa; font-size: 11px;")

    # ========== 步骤 2：下载文件夹 + 模型检测 ==========

    def _create_step2(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("第 2 步：指定下载文件夹并复制模型")
        title.setObjectName("stepTitle")
        layout.addWidget(title)

        desc = QLabel("在 ComfyUI 桌面版中，右键点击模型 → 选择「在文件夹中显示」，复制带「下载」字样的路径")
        desc.setObjectName("stepDesc")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 截图
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(180)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #3c3c3c; border-radius: 6px; background: #252526; }")
        img_label = QLabel()
        _load_screenshot(img_label, "step2_download_folder", 640)
        img_label.setAlignment(Qt.AlignCenter)
        scroll.setWidget(img_label)
        layout.addWidget(scroll)

        # 文件夹选择
        folder_group = QGroupBox("下载文件夹（实例目录）")
        fl = QFormLayout(folder_group)
        fl.setSpacing(10)

        row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("粘贴带「下载」字样的文件夹路径")
        browse_btn = QPushButton("浏览...")
        browse_btn.setFixedWidth(72)
        browse_btn.clicked.connect(self._browse_folder)
        row.addWidget(self.folder_edit, 1)
        row.addWidget(browse_btn)
        w = QWidget()
        w.setLayout(row)
        fl.addRow("文件夹路径：", w)

        self.folder_status = QLabel("尚未指定")
        self.folder_status.setStyleSheet("color: #888; font-size: 11px;")
        fl.addRow("状态：", self.folder_status)

        layout.addWidget(folder_group)

        # 模型文件列表（每个文件一行，带状态和复制按钮）
        model_group = QGroupBox("模型文件检测")
        ml = QVBoxLayout(model_group)
        ml.setSpacing(6)

        # 用滚动区域放所有模型行
        self.model_scroll = QScrollArea()
        self.model_scroll.setWidgetResizable(True)
        self.model_scroll.setFixedHeight(220)
        self.model_scroll.setStyleSheet("""
            QScrollArea { border: 1px solid #3c3c3c; border-radius: 6px; background: #1e1e1e; }
        """)
        self.model_list_widget = QWidget()
        self.model_list_layout = QVBoxLayout(self.model_list_widget)
        self.model_list_layout.setContentsMargins(8, 8, 8, 8)
        self.model_list_layout.setSpacing(6)
        self.model_list_layout.addStretch()
        self.model_scroll.setWidget(self.model_list_widget)
        ml.addWidget(self.model_scroll)

        # 按钮行
        btn_row = QHBoxLayout()
        self.check_btn = QPushButton("🔍 重新检测")
        self.check_btn.setObjectName("secondary")
        self.check_btn.clicked.connect(self._check_models)
        self.copy_all_btn = QPushButton("📋 一键复制全部缺失")
        self.copy_all_btn.clicked.connect(self._copy_all_models)
        self.copy_all_btn.setEnabled(False)
        btn_row.addWidget(self.check_btn)
        btn_row.addWidget(self.copy_all_btn)
        btn_row.addStretch()
        ml.addLayout(btn_row)

        self.copy_progress = QProgressBar()
        self.copy_progress.setVisible(False)
        ml.addWidget(self.copy_progress)

        self.copy_status = QLabel("请先指定下载文件夹，然后点击「重新检测」")
        self.copy_status.setStyleSheet("color: #888; font-size: 11px;")
        ml.addWidget(self.copy_status)

        layout.addWidget(model_group)

        # 源文件夹信息
        src_info = QLabel()
        src_info.setStyleSheet("color: #666; font-size: 11px;")
        src_folder = get_source_folder()
        src_info.setText(f"模型源：{src_folder}")
        layout.addWidget(src_info)

        return page

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择下载文件夹")
        if path:
            self.folder_edit.setText(path)
            self._check_folder()

    def _check_folder(self):
        path = self.folder_edit.text().strip()
        ok, msg = verify_download_folder(path)
        if ok:
            self.folder_status.setText(f"✅ {msg}")
            self.folder_status.setStyleSheet("color: #4ec9b0; font-size: 11px;")
            self._refresh_model_list()
            self.copy_all_btn.setEnabled(True)
            self._save_partial()  # 立即保存
        else:
            self.folder_status.setText(f"⚠️ {msg}")
            self.folder_status.setStyleSheet("color: #dcdcaa; font-size: 11px;")
            self.copy_all_btn.setEnabled(False)

    def _check_models(self):
        """手动触发检测"""
        self._check_folder()

    def _refresh_model_list(self):
        folder = self.folder_edit.text().strip()
        if not folder:
            return

        source = self.cfg.get("comfyui.model_source", "Sulphur 2")
        models = check_models(folder, source)

        # 清空现有行
        while self.model_list_layout.count() > 0:
            item = self.model_list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        missing = 0
        for m in models:
            row = self._create_model_row(m)
            self.model_list_layout.addWidget(row)
            if not m["exists"]:
                missing += 1

        self.model_list_layout.addStretch()

        if missing == 0:
            self.copy_status.setText("✅ 所有模型文件已就绪")
            self.copy_status.setStyleSheet("color: #4ec9b0; font-size: 12px;")
            self.copy_all_btn.setEnabled(False)
        else:
            self.copy_status.setText(f"⚠️ 缺失 {missing} 个文件，可逐个复制或一键复制全部")
            self.copy_status.setStyleSheet("color: #dcdcaa; font-size: 12px;")
            self.copy_all_btn.setEnabled(True)

    def _create_model_row(self, model_info: dict) -> QWidget:
        """创建单个模型文件的行控件"""
        row = QFrame()
        row.setStyleSheet("""
            QFrame {
                background: #252526;
                border-radius: 6px;
                padding: 2px;
            }
        """)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        # 状态图标
        icon_label = QLabel()
        icon_label.setFixedSize(20, 20)
        icon_label.setAlignment(Qt.AlignCenter)
        if model_info["exists"]:
            icon_label.setText("✅")
        elif model_info["source_exists"]:
            icon_label.setText("⚠️")
        else:
            icon_label.setText("❌")
        layout.addWidget(icon_label)

        # 名称和路径
        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        name_label = QLabel(model_info["name"])
        name_label.setStyleSheet("color: #e0e0e0; font-size: 12px; font-weight: bold;")
        text_layout.addWidget(name_label)

        file_label = QLabel(f"{model_info['target_folder']}/{model_info['filename']}")
        file_label.setStyleSheet("color: #888; font-size: 10px;")
        text_layout.addWidget(file_label)

        layout.addWidget(text_widget, 1)

        # 状态文字 + 复制按钮
        if model_info["exists"]:
            status_label = QLabel("已存在")
            status_label.setStyleSheet("color: #4ec9b0; font-size: 11px;")
            layout.addWidget(status_label)
        elif model_info["source_exists"]:
            copy_btn = QPushButton("复制")
            copy_btn.setFixedSize(60, 26)
            copy_btn.setStyleSheet("""
                QPushButton {
                    background: #0e639c; color: white; border: none;
                    border-radius: 4px; font-size: 11px;
                }
                QPushButton:hover { background: #1177bb; }
            """)
            # 绑定单个文件复制
            copy_btn.clicked.connect(
                lambda checked, m=model_info: self._copy_single_model(m)
            )
            layout.addWidget(copy_btn)
        else:
            miss_label = QLabel("源文件缺失")
            miss_label.setStyleSheet("color: #f48771; font-size: 11px;")
            layout.addWidget(miss_label)

        return row

    def _copy_single_model(self, model_info: dict):
        """复制单个模型文件"""
        folder = self.folder_edit.text().strip()
        if not folder:
            return

        # 确保目标目录存在
        target_dir = os.path.join(folder, model_info["target_folder"])
        os.makedirs(target_dir, exist_ok=True)

        self.copy_progress.setVisible(True)
        self.copy_progress.setRange(0, 1)
        self.copy_progress.setValue(0)
        self.copy_status.setText(f"正在复制：{model_info['name']}...")

        try:
            import shutil
            shutil.copy2(model_info["source_path"], model_info["target_path"])
            self.copy_progress.setValue(1)
            self.copy_status.setText(f"✅ {model_info['name']} 复制完成")
            self.copy_status.setStyleSheet("color: #4ec9b0; font-size: 12px;")
            # 刷新列表
            self._refresh_model_list()
            self._save_partial()  # 立即保存
        except Exception as e:
            self.copy_status.setText(f"❌ 复制失败：{str(e)}")
            self.copy_status.setStyleSheet("color: #f48771; font-size: 12px;")

        from PyQt5.QtCore import QTimer
        QTimer.singleShot(2000, lambda: self.copy_progress.setVisible(False))

    def _copy_all_models(self):
        folder = self.folder_edit.text().strip()
        if not folder:
            QMessageBox.warning(self, "提示", "请先指定下载文件夹")
            return

        source = self.cfg.get("comfyui.model_source", "Sulphur 2")
        models = check_models(folder, source)
        missing = [m for m in models if not m["exists"]]
        if not missing:
            return

        self.copy_progress.setVisible(True)
        self.copy_progress.setRange(0, len(missing))
        self.copy_progress.setValue(0)
        self.copy_all_btn.setEnabled(False)
        self.check_btn.setEnabled(False)

        self._copy_worker = CopyWorker(folder, source)
        self._copy_worker.progress.connect(self._on_copy_progress)
        self._copy_worker.finished_ok.connect(self._on_copy_finished)
        self._copy_worker.start()

    def _on_copy_progress(self, name: str, idx: int, total: int):
        self.copy_progress.setValue(idx)
        self.copy_status.setText(f"正在复制：{name} ({idx + 1}/{total})")

    def _on_copy_finished(self, ok: bool, msg: str, results: list):
        self.copy_progress.setVisible(False)
        self.copy_all_btn.setEnabled(True)
        self.check_btn.setEnabled(True)

        if ok:
            self.copy_status.setText(f"✅ {msg}")
            self.copy_status.setStyleSheet("color: #4ec9b0; font-size: 12px;")
            self._refresh_model_list()
            self._save_partial()  # 立即保存
        else:
            self.copy_status.setText(f"❌ {msg}")
            self.copy_status.setStyleSheet("color: #f48771; font-size: 12px;")
            QMessageBox.critical(self, "复制失败", msg)

    # ========== 步骤 3：工作流设置 ==========

    def _create_step3(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("第 3 步：设置工作流")
        title.setObjectName("stepTitle")
        layout.addWidget(title)

        desc = QLabel("需要在 ComfyUI 中开启开发者模式，导出 API 格式的工作流文件")
        desc.setObjectName("stepDesc")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 截图1：开启开发者模式
        scroll1 = QScrollArea()
        scroll1.setWidgetResizable(True)
        scroll1.setFixedHeight(160)
        scroll1.setStyleSheet("QScrollArea { border: 1px solid #3c3c3c; border-radius: 6px; background: #252526; }")
        img1 = QLabel()
        _load_screenshot(img1, "step3_dev_mode", 640)
        img1.setAlignment(Qt.AlignCenter)
        scroll1.setWidget(img1)
        layout.addWidget(scroll1)

        # 说明文字
        step3_info = QLabel()
        step3_info.setText(
            "📌 操作步骤：\n"
            "  a. 打开 ComfyUI 桌面版，点击右上角 ⚙️ 设置\n"
            "  b. 找到「Enable Dev mode Options」→ 勾选开启\n"
            "     （需要登录账号并且翻墙）\n"
            "  c. 关闭设置，点击「Save (API Format)」导出工作流 JSON\n"
            "  d. 将导出的 JSON 文件路径填到下方"
        )
        step3_info.setStyleSheet("""
            QLabel {
                background: #252526; color: #ccc; padding: 12px;
                border-radius: 6px; font-size: 12px; line-height: 1.6;
            }
        """)
        layout.addWidget(step3_info)

        # 工作流文件选择
        wf_group = QGroupBox("工作流文件")
        wl = QFormLayout(wf_group)
        wl.setSpacing(10)

        row = QHBoxLayout()
        self.workflow_edit = QLineEdit()
        self.workflow_edit.setPlaceholderText("选择导出的 API 格式工作流 JSON 文件")
        browse_btn = QPushButton("浏览...")
        browse_btn.setFixedWidth(72)
        browse_btn.clicked.connect(self._browse_workflow)
        row.addWidget(self.workflow_edit, 1)
        row.addWidget(browse_btn)
        w = QWidget()
        w.setLayout(row)
        wl.addRow("文件路径：", w)

        self.workflow_status = QLabel("尚未选择")
        self.workflow_status.setStyleSheet("color: #888; font-size: 11px;")
        wl.addRow("状态：", self.workflow_status)

        # 工作流名称
        self.workflow_name_edit = QLineEdit()
        self.workflow_name_edit.setPlaceholderText("工作流名称（例如：Sulphur 2 文生视频）")
        wl.addRow("显示名称：", self.workflow_name_edit)

        layout.addWidget(wf_group)

        layout.addStretch()
        return page

    def _browse_workflow(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择工作流文件", "",
            "工作流文件 (*.json);;所有文件 (*.*)"
        )
        if path:
            self.workflow_edit.setText(path)
            # 自动填名称
            name = os.path.splitext(os.path.basename(path))[0]
            if not self.workflow_name_edit.text():
                self.workflow_name_edit.setText(name)
            self._check_workflow()

    def _check_workflow(self):
        path = self.workflow_edit.text().strip()
        if not path:
            self.workflow_status.setText("尚未选择")
            self.workflow_status.setStyleSheet("color: #888; font-size: 11px;")
            return
        if not os.path.exists(path):
            self.workflow_status.setText("❌ 文件不存在")
            self.workflow_status.setStyleSheet("color: #f48771; font-size: 11px;")
            return
        try:
            import json
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                node_count = len(data)
                self.workflow_status.setText(f"✅ 有效工作流（{node_count} 个节点）")
                self.workflow_status.setStyleSheet("color: #4ec9b0; font-size: 11px;")
                # 验证通过后立即保存工作流到配置
                self._save_workflow_to_config(path, self.workflow_name_edit.text().strip())
                self._save_partial()
            else:
                self.workflow_status.setText("⚠️ 格式可能不对（不是对象结构）")
                self.workflow_status.setStyleSheet("color: #dcdcaa; font-size: 11px;")
        except Exception as e:
            self.workflow_status.setText(f"❌ 读取失败：{str(e)}")
            self.workflow_status.setStyleSheet("color: #f48771; font-size: 11px;")

    def _save_workflow_to_config(self, path: str, name: str):
        """把工作流文件保存到配置（立即生效）"""
        if not path or not os.path.exists(path):
            return
        import json
        import time
        try:
            with open(path, 'r', encoding='utf-8') as f:
                wf_data = json.load(f)
        except Exception:
            return

        cfg = self.cfg
        workflows = cfg.get("comfyui.workflows", [])

        # 检查是否已存在相同数据的工作流
        wf_id = f"wf-{int(time.time()*1000)}"
        workflows.append({
            "id": wf_id,
            "name": name or os.path.basename(path),
            "data": wf_data,
        })
        cfg.set("comfyui.workflows", workflows)
        cfg.set("comfyui.last_workflow", wf_id)
        cfg.save()

    # ========== 步骤 4：生成参数 ==========

    def _create_step4(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("第 4 步：视频生成参数")
        title.setObjectName("stepTitle")
        layout.addWidget(title)

        desc = QLabel("设置默认的视频生成参数，后续可以随时调整")
        desc.setObjectName("stepDesc")
        layout.addWidget(desc)

        # 截图
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(180)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #3c3c3c; border-radius: 6px; background: #252526; }")
        img_label = QLabel()
        _load_screenshot(img_label, "step4_workflow_params", 640)
        img_label.setAlignment(Qt.AlignCenter)
        scroll.setWidget(img_label)
        layout.addWidget(scroll)

        # 参数组
        param_group = QGroupBox("视频参数")
        pl = QFormLayout(param_group)
        pl.setSpacing(12)

        # 分辨率
        res_row = QHBoxLayout()
        self.width_spin = QSpinBox()
        self.width_spin.setRange(256, 2048)
        self.width_spin.setValue(768)
        self.width_spin.setSingleStep(64)
        self.width_spin.setSuffix(" px")
        self.height_spin = QSpinBox()
        self.height_spin.setRange(256, 2048)
        self.height_spin.setValue(432)
        self.height_spin.setSingleStep(64)
        self.height_spin.setSuffix(" px")
        res_row.addWidget(QLabel("宽："))
        res_row.addWidget(self.width_spin)
        res_row.addSpacing(20)
        res_row.addWidget(QLabel("高："))
        res_row.addWidget(self.height_spin)
        res_row.addStretch()
        w = QWidget()
        w.setLayout(res_row)
        pl.addRow("视频分辨率：", w)

        # 时长
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 100000)
        self.duration_spin.setValue(5)
        self.duration_spin.setSuffix(" 秒")
        pl.addRow("视频时长：", self.duration_spin)

        # FPS
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(8, 60)
        self.fps_spin.setValue(24)
        self.fps_spin.setSuffix(" fps")
        pl.addRow("帧率：", self.fps_spin)

        # 步数
        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(1, 100)
        self.steps_spin.setValue(20)
        pl.addRow("采样步数：", self.steps_spin)

        # CFG
        self.cfg_spin = QSpinBox()
        self.cfg_spin.setRange(1, 20)
        self.cfg_spin.setValue(6)
        pl.addRow("CFG 强度：", self.cfg_spin)

        layout.addWidget(param_group)

        # 提示词节点映射说明
        tip = QLabel(
            "💡 提示：生成视频时，程序会自动把提示词填入工作流中对应的文本节点。\n"
            "   你可以在主界面的「提示词目标节点」下拉框中选择具体节点。"
        )
        tip.setStyleSheet("""
            QLabel {
                background: #252526; color: #888; padding: 10px 12px;
                border-radius: 6px; font-size: 11px; line-height: 1.5;
            }
        """)
        tip.setWordWrap(True)
        layout.addWidget(tip)

        layout.addStretch()

        # 完成按钮文案
        self.finish_label = QLabel("🎉 设置完成！点击「完成」开始使用视频生成功能")
        self.finish_label.setAlignment(Qt.AlignCenter)
        self.finish_label.setStyleSheet("""
            QLabel {
                color: #4ec9b0; font-size: 13px; font-weight: bold;
                padding: 12px; background: #252526; border-radius: 6px;
            }
        """)
        layout.addWidget(self.finish_label)

        return page

    # ========== 步骤导航 ==========

    def _update_step_ui(self):
        self.stacked.setCurrentIndex(self.current_step)

        step_names = ["指定 ComfyUI", "模型文件", "工作流设置", "生成参数"]
        dots = ""
        for i in range(4):
            if i == self.current_step:
                dots += f" ● {i+1}.{step_names[i]} "
            elif i < self.current_step:
                dots += f" ✓ {i+1} "
            else:
                dots += f" ○ {i+1} "

        self.step_indicator.setText(dots)

        self.prev_btn.setEnabled(self.current_step > 0)

        if self.current_step == 3:
            self.next_btn.setText("完成 ✓")
        else:
            self.next_btn.setText("下一步 ▶")

    def _prev_step(self):
        if self.current_step > 0:
            self.current_step -= 1
            self._update_step_ui()

    def _next_step(self):
        if self.current_step == 0:
            # 验证第1步
            if not self.exe_edit.text().strip():
                QMessageBox.warning(self, "提示", "请选择 ComfyUI 可执行文件")
                return
        elif self.current_step == 1:
            # 验证第2步
            folder = self.folder_edit.text().strip()
            if not folder:
                QMessageBox.warning(self, "提示", "请指定下载文件夹")
                return
            source = self.cfg.get("comfyui.model_source", "Sulphur 2")
            models = check_models(folder, source)
            missing = [m for m in models if not m["exists"]]
            if missing:
                ret = QMessageBox.question(
                    self, "模型文件缺失",
                    f"还有 {len(missing)} 个模型文件缺失，确定要继续吗？\n\n"
                    "可以点击「一键复制缺失文件」自动复制。",
                    QMessageBox.Yes | QMessageBox.No
                )
                if ret != QMessageBox.Yes:
                    return
        elif self.current_step == 2:
            # 验证第3步
            if not self.workflow_edit.text().strip():
                QMessageBox.warning(self, "提示", "请选择工作流文件")
                return
            if not os.path.exists(self.workflow_edit.text().strip()):
                QMessageBox.warning(self, "提示", "工作流文件不存在")
                return
        elif self.current_step == 3:
            # 完成
            self._save_config()
            self.accept()
            return

        if self.current_step < 3:
            self.current_step += 1
            self._update_step_ui()

    # ========== 配置加载/保存 ==========

    def _load_config(self):
        cfg = self.cfg
        self.exe_edit.setText(cfg.get("comfyui.exe_path", ""))
        self.addr_edit.setText(cfg.get("comfyui.server_address", "127.0.0.1:8188"))
        self.folder_edit.setText(cfg.get("comfyui.download_folder", ""))

        # 加载视频参数
        self.width_spin.setValue(cfg.get("comfyui.default_width", 768))
        self.height_spin.setValue(cfg.get("comfyui.default_height", 432))
        self.duration_spin.setValue(cfg.get("comfyui.default_duration", 5))
        self.fps_spin.setValue(cfg.get("comfyui.default_fps", 24))
        self.steps_spin.setValue(cfg.get("comfyui.default_steps", 20))
        self.cfg_spin.setValue(cfg.get("comfyui.default_cfg", 6))

        if self.exe_edit.text():
            self._check_exe()
        if self.folder_edit.text():
            self._check_folder()

    def _save_partial(self):
        """保存当前步骤的设置（立即保存到配置文件，不关闭对话框）"""
        cfg = self.cfg

        # 第1步：ComfyUI 路径和地址
        cfg.set("comfyui.exe_path", self.exe_edit.text().strip())
        cfg.set("comfyui.server_address", self.addr_edit.text().strip() or "127.0.0.1:8188")

        # 第2步：下载文件夹
        cfg.set("comfyui.download_folder", self.folder_edit.text().strip())

        # 第4步：视频参数
        cfg.set("comfyui.default_width", self.width_spin.value())
        cfg.set("comfyui.default_height", self.height_spin.value())
        cfg.set("comfyui.default_duration", self.duration_spin.value())
        cfg.set("comfyui.default_fps", self.fps_spin.value())
        cfg.set("comfyui.default_steps", self.steps_spin.value())
        cfg.set("comfyui.default_cfg", self.cfg_spin.value())

        cfg.save()

    def closeEvent(self, event):
        """关闭时确保后台线程安全退出"""
        if hasattr(self, '_copy_worker') and self._copy_worker and self._copy_worker.isRunning():
            self._copy_worker.terminate()
            self._copy_worker.wait()
        # 关闭前也保存一下当前状态
        self._save_partial()
        super().closeEvent(event)

    def _save_config(self):
        cfg = self.cfg
        cfg.set("comfyui.exe_path", self.exe_edit.text().strip())
        cfg.set("comfyui.server_address", self.addr_edit.text().strip() or "127.0.0.1:8188")
        cfg.set("comfyui.download_folder", self.folder_edit.text().strip())

        cfg.set("comfyui.default_width", self.width_spin.value())
        cfg.set("comfyui.default_height", self.height_spin.value())
        cfg.set("comfyui.default_duration", self.duration_spin.value())
        cfg.set("comfyui.default_fps", self.fps_spin.value())
        cfg.set("comfyui.default_steps", self.steps_spin.value())
        cfg.set("comfyui.default_cfg", self.cfg_spin.value())

        # 保存工作流
        wf_path = self.workflow_edit.text().strip()
        wf_name = self.workflow_name_edit.text().strip()
        if wf_path and os.path.exists(wf_path):
            import json
            try:
                with open(wf_path, 'r', encoding='utf-8') as f:
                    wf_data = json.load(f)

                workflows = cfg.get("comfyui.workflows", [])
                # 检查是否已存在同名工作流
                wf_id = f"wf-{int(__import__('time').time()*1000)}"
                workflows.append({
                    "id": wf_id,
                    "name": wf_name or "未命名工作流",
                    "data": wf_data,
                })
                cfg.set("comfyui.workflows", workflows)
                cfg.set("comfyui.last_workflow", wf_id)
            except Exception:
                pass

        cfg.set("comfyui.setup_completed", True)
        cfg.save()
