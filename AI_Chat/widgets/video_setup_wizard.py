"""
视频模型设置向导 - 三步设置
第1步：ComfyUI 可执行文件路径
第2步：工作流 API 文件
第3步：实例目录 + 模型文件检测
"""
import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QMessageBox, QSpinBox,
    QGroupBox, QFormLayout, QFrame, QProgressBar, QScrollArea,
    QWidget
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap, QFont

from core.config import get_config_manager
from core.comfyui_client import load_workflow_json, convert_ui_to_api, find_text_nodes


def _find_best_screenshot(base_name: str) -> str:
    """找到最佳质量的截图"""
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


def _load_screenshot(label, base_name: str, max_width: int = 560):
    path = _find_best_screenshot(base_name)
    if path:
        pix = QPixmap(path)
        label.setPixmap(pix.scaledToWidth(max_width, Qt.SmoothTransformation))
    else:
        label.setText("（截图未找到）")


def verify_comfyui_exe(path: str) -> tuple:
    """验证 ComfyUI 可执行文件"""
    if not path:
        return False, "未指定"
    if not os.path.exists(path):
        return False, "文件不存在"
    if not os.path.isfile(path):
        return False, "不是文件"
    name = os.path.basename(path).lower()
    if name.endswith(('.exe', '.bat', '.cmd', '.ps1')):
        return True, f"可执行文件已确认"
    return True, "文件已选择（请确认是 ComfyUI 启动程序）"


def verify_download_folder(path: str) -> tuple:
    """验证下载文件夹/实例目录"""
    if not path:
        return False, "未指定"
    if not os.path.exists(path):
        return False, "路径不存在"
    if not os.path.isdir(path):
        return False, "不是文件夹"
    # 检查是否有 models 或 checkpoints 子目录（ComfyUI 特征）
    subdirs = [d.lower() for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]
    has_comfy = any(d in subdirs for d in ['models', 'checkpoints', 'custom_nodes', 'input', 'output'])
    if has_comfy:
        return True, "实例目录已确认"
    return True, "目录已选择（请确认是 ComfyUI 实例目录）"


class CopyWorker(QThread):
    """复制模型文件的后台线程"""
    progress = pyqtSignal(str, int, int)  # 文件名, 当前, 总数
    finished_ok = pyqtSignal(str, list)  # 消息, 结果列表
    error = pyqtSignal(str)

    def __init__(self, download_folder: str, source_folder: str, files: list):
        super().__init__()
        self.download_folder = download_folder
        self.source_folder = source_folder
        self.files = files  # [{filename, subfolder, name}]

    def run(self):
        import shutil
        results = []
        total = len(self.files)
        copied = 0

        for i, f in enumerate(self.files):
            self.progress.emit(f["name"], i + 1, total)
            src = os.path.join(self.source_folder, f["filename"])
            dst_dir = os.path.join(self.download_folder, f["subfolder"])
            dst = os.path.join(dst_dir, f["filename"])

            try:
                if not os.path.exists(src):
                    results.append({"name": f["name"], "ok": False, "msg": "源文件不存在"})
                    continue

                os.makedirs(dst_dir, exist_ok=True)

                if os.path.exists(dst):
                    results.append({"name": f["name"], "ok": True, "msg": "已存在"})
                    copied += 1
                    continue

                shutil.copy2(src, dst)
                results.append({"name": f["name"], "ok": True, "msg": "复制成功"})
                copied += 1
            except Exception as e:
                results.append({"name": f["name"], "ok": False, "msg": str(e)})

        self.progress.emit("", total, total)
        self.finished_ok.emit(f"已复制 {copied}/{total} 个文件", results)


# ========== 模型文件清单 ==========
LTX_SULPHUR_MODELS = [
    {
        "filename": "gemma-3-12b-it-ablit-norms-biproj-fp8mixed.safetensors",
        "subfolder": "text_encoders",
        "name": "文本编码器 (Gemma 3 12B)",
    },
    {
        "filename": "10Eros_v1.4_DMD_int8_convrot.safetensors",
        "subfolder": "checkpoints",
        "name": "扩散主模型 (10Eros v1.4 INT8)",
    },
    {
        "filename": "ltx-2.3-22b-distilled-lora-384.safetensors",
        "subfolder": "loras",
        "name": "LoRA 模型 (LTX 2.3 Distilled)",
    },
    {
        "filename": "ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
        "subfolder": "latent_upscale_models",
        "name": "潜空间超分模型 (Spatial Upscaler)",
    },
]


def check_models(download_folder: str, source_model_folder: str) -> list:
    """检查模型文件是否存在"""
    app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    source_dir = os.path.join(app_root, "models", source_model_folder)

    results = []
    for m in LTX_SULPHUR_MODELS:
        dst = os.path.join(download_folder, m["subfolder"], m["filename"])
        src = os.path.join(source_dir, m["filename"])
        results.append({
            **m,
            "exists": os.path.exists(dst),
            "source_exists": os.path.exists(src),
            "source_path": src,
            "dest_path": dst,
        })
    return results


class VideoSetupWizard(QDialog):
    """视频模型设置向导（3步）"""

    # 工作流保存到配置后发出，通知嵌入它的面板立即刷新下拉框
    workflow_saved = pyqtSignal()

    def __init__(self, parent=None, mode: str = "t2v"):
        super().__init__(parent)
        self.cfg = get_config_manager()
        self.mode = mode  # t2v=文生视频 / i2v=图生视频（工作流与截图不同，设置分键保存）
        self.setWindowTitle("模型设置 - LTX-2.3 + Sulphur 2")
        self.setMinimumSize(720, 640)
        self.setStyleSheet("""
            QDialog { background: #1e1e1e; color: #e6edf3; }
            QLabel { color: #e6edf3; font-family: "Microsoft YaHei"; }
            QLineEdit {
                background: #252526; color: #ccc; border: 1px solid #3c3c3c;
                border-radius: 4px; padding: 6px 10px; font-size: 12px;
            }
            QLineEdit:focus { border-color: #007acc; }
            QPushButton {
                background: #007acc; color: white; border: none;
                padding: 6px 16px; border-radius: 4px; font-size: 12px;
            }
            QPushButton:hover { background: #0e639c; }
            QPushButton:disabled { background: #3a3a3a; color: #666; }
            QGroupBox {
                color: #e6edf3; border: 1px solid #3c3c3c;
                border-radius: 6px; margin-top: 10px; padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px; padding: 0 4px;
                color: #007acc; font-size: 12px; font-weight: bold;
            }
            QSpinBox {
                background: #252526; color: #ccc; border: 1px solid #3c3c3c;
                border-radius: 4px; padding: 4px 8px;
            }
            QProgressBar {
                border: 1px solid #3c3c3c; border-radius: 4px;
                background: #252526; text-align: center; color: #fff; height: 20px;
            }
            QProgressBar::chunk { background: #007acc; border-radius: 3px; }
        """)

        self._copy_worker = None
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 标题
        title = QLabel("🎬 LTX-2.3 + Sulphur 2 模型设置")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #fff;")
        layout.addWidget(title)

        # 步骤指示器
        step_bar = QHBoxLayout()
        step_bar.setSpacing(4)
        self.step_labels = []
        steps = ["1. 下载目录", "2. 工作流", "3. 模型文件"]
        for i, s in enumerate(steps):
            lbl = QLabel(s)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedHeight(28)
            lbl.setStyleSheet("""
                QLabel {
                    background: #2d2d30; color: #888;
                    border-radius: 4px; font-size: 11px; padding: 0 12px;
                }
            """)
            self.step_labels.append(lbl)
            step_bar.addWidget(lbl)
        layout.addLayout(step_bar)

        # 步骤内容容器
        self.stacked = QWidget()
        self.stack_layout = QVBoxLayout(self.stacked)
        self.stack_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stacked, 1)

        # 三个步骤页面
        self.step1_widget = self._create_step1()
        self.step2_widget = self._create_step2()
        self.step3_widget = self._create_step3()

        self.stack_layout.addWidget(self.step1_widget)
        self.stack_layout.addWidget(self.step2_widget)
        self.stack_layout.addWidget(self.step3_widget)

        self.step2_widget.setVisible(False)
        self.step3_widget.setVisible(False)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_prev = QPushButton("← 上一步")
        self.btn_prev.setFixedSize(90, 32)
        self.btn_prev.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.08); color: #ccc;
                border: 1px solid rgba(255,255,255,0.15); border-radius: 4px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.15); }
            QPushButton:disabled { color: #555; }
        """)
        self.btn_prev.clicked.connect(self._prev_step)
        self.btn_prev.setEnabled(False)

        self.btn_next = QPushButton("下一步 →")
        self.btn_next.setFixedSize(100, 32)
        self.btn_next.clicked.connect(self._next_step)

        self.btn_finish = QPushButton("✅ 完成")
        self.btn_finish.setFixedSize(100, 32)
        self.btn_finish.clicked.connect(self.accept)
        self.btn_finish.setVisible(False)

        btn_row.addStretch()
        btn_row.addWidget(self.btn_prev)
        btn_row.addWidget(self.btn_next)
        btn_row.addWidget(self.btn_finish)
        layout.addLayout(btn_row)

        self._current_step = 0
        self._update_step_ui()

    # ========== 第1步：下载目录 ==========

    def _create_step1(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 说明
        desc = QLabel("第一步：指定模型下载文件夹\n\n"
                      "请在 ComfyUI 中找到「下载」目录，复制其完整路径粘贴到下方。\n"
                      "这是存放所有模型文件的根目录，程序会在此目录下检测和复制模型文件。\n\n"
                      "⚠️ 使用前请确保 ComfyUI 已经启动并运行在本机。")
        desc.setStyleSheet("color: #ccc; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 截图
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(220)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: #2d2d30; width: 10px; }
            QScrollBar::handle:vertical {
                background: #555; border-radius: 5px; min-height: 30px;
            }
        """)
        img_label = QLabel()
        _load_screenshot(img_label, "step1_download_folder", 560)
        img_label.setAlignment(Qt.AlignCenter)
        scroll.setWidget(img_label)
        layout.addWidget(scroll)

        # 下载文件夹路径
        folder_group = QGroupBox("模型下载文件夹")
        fg = QVBoxLayout(folder_group)
        fg.setSpacing(8)

        row1 = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("例如：C:\\ComfyUI\\models  或下载目录路径")
        self.folder_edit.textChanged.connect(lambda: self._check_folder())
        btn1 = QPushButton("浏览...")
        btn1.setFixedSize(70, 28)
        btn1.clicked.connect(self._browse_folder)
        row1.addWidget(self.folder_edit, 1)
        row1.addWidget(btn1)
        fg.addLayout(row1)

        self.folder_status = QLabel("尚未设置")
        self.folder_status.setStyleSheet("color: #888; font-size: 11px;")
        fg.addWidget(self.folder_status)

        # 服务器地址
        row2 = QHBoxLayout()
        addr_label = QLabel("ComfyUI 地址:")
        addr_label.setFixedWidth(90)
        addr_label.setStyleSheet("color: #aaa; font-size: 12px;")
        self.addr_edit = QLineEdit()
        self.addr_edit.setText("127.0.0.1:8188")
        self.addr_edit.setFixedWidth(160)
        self.addr_edit.setStyleSheet("background: #252526; color: #ccc; border: 1px solid #3c3c3c; border-radius: 4px; padding: 4px 8px;")
        hint = QLabel("请确保 ComfyUI 已启动")
        hint.setStyleSheet("color: #888; font-size: 10px;")
        row2.addWidget(addr_label)
        row2.addWidget(self.addr_edit)
        row2.addWidget(hint)
        row2.addStretch()
        fg.addLayout(row2)

        tip = QLabel("💡 在 ComfyUI 的模型管理/下载页面，复制带「下载」字样的目录路径，粘贴到上面。")
        tip.setStyleSheet("color: #888; font-size: 10px;")
        tip.setWordWrap(True)
        fg.addWidget(tip)

        layout.addWidget(folder_group)
        layout.addStretch()
        return w

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择模型下载文件夹")
        if path:
            self.folder_edit.setText(path)

    # ========== 第2步：工作流 ==========

    def _create_step2(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        if self.mode == "i2v":
            desc = QLabel("第二步：设置工作流 API 文件（图生视频）\n\n"
                          "必须要指定工作流API文件。\n"
                          "1.先在ComfyUI里面打开开发者模式\n"
                          "2.在模板中选择LTX-2.3:图生视频\n"
                          "随后配置工作流程:\n"
                          "a.先完成第一步的下载文件夹指定(必须是截图里ComfyUI的下载文件夹)。\n"
                          "b.然后在第三步检测模型文件，会显示缺失，然后点击一键复制缺失文件进行模型文件复制。\n"
                          "c.随后如第二步截图所示在ckpt_name和distilled_lora和txt_encoder和latent_upscale_model和lora后面的下拉菜单中指定模型文件，如果第三步复制无误，这里应当都可以有选项供选择。\n"
                          "d.指定完成后选择导出(API)用以导出API文件(工作流里的加载图像节点无需手动选图，加载API文件后在下方底栏用图片节点下拉框指定注入哪个加载图像节点，生成时会自动上传你在本界面选择的图片)。\n"
                          "e.在这里加载API文件。\n"
                          "f.务必确保ComfyUI桌面端程序在运行，然后就可以在本界面进行图生视频。")
        else:
            desc = QLabel("第二步：设置工作流 API 文件\n\n"
                          "必须要指定工作流API文件。\n"
                          "1.先在ComfyUI里面打开开发者模式\n"
                          "2.在模板中选择LTX-2.3:文生视频\n"
                          "随后配置工作流程:\n"
                          "a.先完成第一步的下载文件夹指定(必须是截图里ComfyUI的下载文件夹)。\n"
                          "b.然后在第三步检测模型文件，会显示缺失，然后点击一键复制缺失文件进行模型文件复制。\n"
                          "c.随后如第二步截图所示在ckpt_name和distilled_lora和txt_encoder和latent_upscale_model和lora后面的下拉菜单中指定模型文件，如果第三步复制无误，这里应当都可以有选项供选择。\n"
                          "d.指定完成后(右侧工作流总览无报错)后选择导出(API)用以导出API文件。\n"
                          "e.在这里加载API文件。\n"
                          "f.务必确保ComfyUI桌面端程序在运行然后就可以进行文生图功能。")
        desc.setStyleSheet("color: #ccc; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 截图
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(180)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: #2d2d30; width: 10px; }
            QScrollBar::handle:vertical {
                background: #555; border-radius: 5px; min-height: 30px;
            }
        """)
        img_label = QLabel()
        if self.mode == "i2v":
            _load_screenshot(img_label, "step2_workflow_i2v", 560)
        else:
            _load_screenshot(img_label, "step2_workflow_api", 560)
        img_label.setAlignment(Qt.AlignCenter)
        scroll.setWidget(img_label)
        layout.addWidget(scroll)

        # 工作流文件
        wf_group = QGroupBox("工作流文件")
        wg = QVBoxLayout(wf_group)
        wg.setSpacing(8)

        row1 = QHBoxLayout()
        self.workflow_edit = QLineEdit()
        if self.mode == "i2v":
            self.workflow_edit.setPlaceholderText("必填：选择图生视频工作流的 API 文件")
        else:
            self.workflow_edit.setPlaceholderText("使用默认工作流（留空则自动加载）")
        self.workflow_edit.textChanged.connect(lambda: self._check_workflow())
        btn1 = QPushButton("浏览...")
        btn1.setFixedSize(70, 28)
        btn1.clicked.connect(self._browse_workflow)
        row1.addWidget(self.workflow_edit, 1)
        row1.addWidget(btn1)
        wg.addLayout(row1)

        self.workflow_status = QLabel("使用默认工作流")
        self.workflow_status.setStyleSheet("color: #3fb950; font-size: 11px;")
        wg.addWidget(self.workflow_status)

        # 提示词节点（仅文生视频需要；图生视频的提示词节点由面板自动识别，不显示）
        if self.mode != "i2v":
            row2 = QHBoxLayout()
            node_label = QLabel("提示词节点:")
            node_label.setFixedWidth(80)
            node_label.setStyleSheet("color: #aaa; font-size: 12px;")
            self.prompt_node_edit = QLineEdit()
            self.prompt_node_edit.setText("267:327: TextGenerateLTX2Prompt")
            self.prompt_node_edit.setStyleSheet("background: #252526; color: #ccc; border: 1px solid #3c3c3c; border-radius: 4px; padding: 4px 8px;")
            row2.addWidget(node_label)
            row2.addWidget(self.prompt_node_edit, 1)
            wg.addLayout(row2)

        tip = QLabel("💡 默认工作流会自动加载，无需手动指定。只有自定义工作流时才需要选择。")
        tip.setStyleSheet("color: #888; font-size: 10px;")
        tip.setWordWrap(True)
        wg.addWidget(tip)

        layout.addWidget(wf_group)
        layout.addStretch()
        return w

    def _browse_workflow(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择工作流 JSON", "",
            "工作流文件 (*.json);;所有文件 (*.*)"
        )
        if path:
            self.workflow_edit.setText(path)

    def _check_workflow(self):
        path = self.workflow_edit.text().strip()
        if not path:
            self.workflow_status.setText("使用默认工作流")
            self.workflow_status.setStyleSheet("color: #3fb950; font-size: 11px;")
            return
        if not os.path.exists(path):
            self.workflow_status.setText("❌ 文件不存在")
            self.workflow_status.setStyleSheet("color: #f85149; font-size: 11px;")
            return
        try:
            import json
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                if "prompt" in data and isinstance(data["prompt"], dict):
                    count = len(data["prompt"])
                elif "nodes" in data:
                    count = len(data["nodes"])
                else:
                    count = len(data)
                self.workflow_status.setText(f"✅ 有效工作流（{count} 个节点）")
                self.workflow_status.setStyleSheet("color: #3fb950; font-size: 11px;")
                # 立即保存到配置并通知面板刷新（嵌入模式没有"完成"按钮可点）
                self._save_workflow_only()
            else:
                self.workflow_status.setText("⚠️ 格式不正确")
                self.workflow_status.setStyleSheet("color: #dcdcaa; font-size: 11px;")
        except Exception as e:
            self.workflow_status.setText(f"❌ 读取失败：{str(e)}")
            self.workflow_status.setStyleSheet("color: #f85149; font-size: 11px;")

    def _save_workflow_only(self):
        """把当前选中的工作流解析并保存到配置（按模式分键），成功后发信号"""
        wf_path = self.workflow_edit.text().strip()
        if not wf_path or not os.path.exists(wf_path):
            return
        try:
            wf_data = load_workflow_json(wf_path)
            if "prompt" in wf_data and isinstance(wf_data["prompt"], dict):
                api_wf = wf_data["prompt"]
            elif "nodes" in wf_data:
                api_wf = convert_ui_to_api(wf_data)
            else:
                api_wf = wf_data

            import time
            wf_name = os.path.basename(wf_path)
            workflows = self.cfg.get("comfyui.workflows", [])
            # 按文件名去重，避免反复选择时堆积重复条目
            workflows = [w for w in workflows if w.get("name") != wf_name]
            wf_id = f"wf-{int(time.time()*1000)}"
            workflows.append({
                "id": wf_id,
                "name": wf_name,
                "path": wf_path,
                "data": api_wf,
            })
            self.cfg.set("comfyui.workflows", workflows)
            # t2v / i2v 是不同工作流，分开记录最近使用
            self.cfg.set(f"comfyui.last_workflow_{self.mode}", wf_id)
            self.cfg.save()
            self.workflow_saved.emit()
        except Exception as e:
            QMessageBox.warning(self, "工作流加载失败", str(e))

    # ========== 第3步：模型文件 ==========

    def _create_step3(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        desc = QLabel("第三步：检测模型文件\n\n"
                      "程序会自动检测第一步指定的下载目录中所需的模型文件是否存在。\n"
                      "缺失的文件可以一键从 models/Sulphur 2 文件夹复制过去。")
        desc.setStyleSheet("color: #ccc; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 当前目录提示
        self.step3_folder_label = QLabel("当前目录：尚未设置")
        self.step3_folder_label.setStyleSheet("color: #888; font-size: 11px;")
        self.step3_folder_label.setWordWrap(True)
        layout.addWidget(self.step3_folder_label)

        # 模型文件列表
        model_group = QGroupBox("模型文件检测")
        mg = QVBoxLayout(model_group)
        mg.setSpacing(6)

        self.model_summary = QLabel("检测中...")
        self.model_summary.setStyleSheet("color: #888; font-size: 12px; font-weight: bold;")
        mg.addWidget(self.model_summary)

        # 每个模型一行
        self.model_row_widget = QWidget()
        self.model_row_layout = QVBoxLayout(self.model_row_widget)
        self.model_row_layout.setContentsMargins(0, 4, 0, 4)
        self.model_row_layout.setSpacing(4)
        mg.addWidget(self.model_row_widget)

        # 复制进度
        self.copy_progress = QProgressBar()
        self.copy_progress.setVisible(False)
        mg.addWidget(self.copy_progress)

        self.copy_status = QLabel("")
        self.copy_status.setStyleSheet("color: #888; font-size: 11px;")
        mg.addWidget(self.copy_status)

        # 按钮行
        btn_row = QHBoxLayout()
        self.check_btn = QPushButton("🔄 重新检测")
        self.check_btn.setFixedSize(90, 28)
        self.check_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.08); color: #ccc;
                border: 1px solid rgba(255,255,255,0.15); border-radius: 4px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.15); }
        """)
        self.check_btn.clicked.connect(self._refresh_model_list)

        self.copy_all_btn = QPushButton("📋 一键复制缺失文件")
        self.copy_all_btn.setFixedSize(150, 28)
        self.copy_all_btn.clicked.connect(self._copy_all_models)
        self.copy_all_btn.setEnabled(False)

        btn_row.addWidget(self.check_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.copy_all_btn)
        mg.addLayout(btn_row)

        layout.addWidget(model_group)
        layout.addStretch()
        return w

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择实例目录")
        if path:
            self.folder_edit.setText(path)

    def _check_folder(self):
        path = self.folder_edit.text().strip()
        ok, msg = verify_download_folder(path)
        if ok:
            self.folder_status.setText(f"✅ {msg}")
            self.folder_status.setStyleSheet("color: #3fb950; font-size: 11px;")
            self._refresh_model_list()
            self.copy_all_btn.setEnabled(True)
            self._save_partial()
        else:
            self.folder_status.setText(f"⚠️ {msg}")
            self.folder_status.setStyleSheet("color: #dcdcaa; font-size: 11px;")
            self.copy_all_btn.setEnabled(False)

    def _refresh_model_list(self):
        folder = self.folder_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            return

        # 清空
        while self.model_row_layout.count() > 0:
            item = self.model_row_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        models = check_models(folder, "Sulphur 2")
        total = len(models)
        ready = sum(1 for m in models if m["exists"])

        if ready == total:
            self.model_summary.setText(f"✅ 全部就绪 ({ready}/{total})")
            self.model_summary.setStyleSheet("color: #3fb950; font-size: 12px; font-weight: bold;")
        else:
            self.model_summary.setText(f"⚠️ {ready}/{total} 个文件就绪")
            self.model_summary.setStyleSheet("color: #dcdcaa; font-size: 12px; font-weight: bold;")

        for m in models:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)

            icon = QLabel("✅" if m["exists"] else "⚠️")
            icon.setFixedWidth(24)
            icon.setStyleSheet("font-size: 12px;")

            name = QLabel(m["name"])
            name.setStyleSheet("color: #ccc; font-size: 11px;")
            name.setToolTip(m["filename"])

            row.addWidget(icon)
            row.addWidget(name, 1)

            if not m["exists"]:
                if m["source_exists"]:
                    copy_btn = QPushButton("复制")
                    copy_btn.setFixedSize(56, 24)
                    copy_btn.setStyleSheet("""
                        QPushButton {
                            background: #007acc; color: white; border: none;
                            border-radius: 3px; font-size: 11px; padding: 2px 8px;
                        }
                        QPushButton:hover { background: #0e639c; }
                    """)
                    info = m
                    copy_btn.clicked.connect(lambda _, mi=info: self._copy_single_model(mi))
                    row.addWidget(copy_btn)
                else:
                    miss = QLabel("源文件缺失")
                    miss.setStyleSheet("color: #f85149; font-size: 10px;")
                    row.addWidget(miss)

            w = QWidget()
            w.setLayout(row)
            self.model_row_layout.addWidget(w)

    def _copy_single_model(self, model_info: dict):
        """复制单个模型文件"""
        folder = self.folder_edit.text().strip()
        if not folder:
            return

        self.copy_progress.setVisible(True)
        self.copy_progress.setRange(0, 0)  # 不确定进度
        self.copy_status.setText(f"正在复制 {model_info['name']}...")
        self.copy_all_btn.setEnabled(False)
        self.check_btn.setEnabled(False)

        # 用线程复制
        worker = CopyWorker(folder, os.path.dirname(model_info["source_path"]), [model_info])
        self._copy_worker = worker
        worker.finished_ok.connect(lambda msg, results: self._on_single_copy_done(msg, results, model_info))
        worker.start()

    def _on_single_copy_done(self, msg: str, results: list, model_info: dict):
        self.copy_progress.setVisible(False)
        self.copy_all_btn.setEnabled(True)
        self.check_btn.setEnabled(True)
        self.copy_status.setText(f"✅ {model_info['name']} 复制完成")
        self.copy_status.setStyleSheet("color: #3fb950; font-size: 11px;")
        self._refresh_model_list()
        self._save_partial()

    def _copy_all_models(self):
        """复制所有缺失的模型文件"""
        folder = self.folder_edit.text().strip()
        if not folder:
            return

        models = check_models(folder, "Sulphur 2")
        missing = [m for m in models if not m["exists"] and m["source_exists"]]

        if not missing:
            QMessageBox.information(self, "提示", "所有模型文件都已就绪，无需复制。")
            return

        self.copy_progress.setVisible(True)
        self.copy_progress.setRange(0, len(missing))
        self.copy_progress.setValue(0)
        self.copy_status.setText("正在复制文件...")
        self.copy_all_btn.setEnabled(False)
        self.check_btn.setEnabled(False)

        app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        source_dir = os.path.join(app_root, "models", "Sulphur 2")

        worker = CopyWorker(folder, source_dir, missing)
        self._copy_worker = worker
        worker.progress.connect(self._on_copy_progress)
        worker.finished_ok.connect(self._on_copy_finished)
        worker.start()

    def _on_copy_progress(self, name: str, current: int, total: int):
        self.copy_progress.setValue(current)
        if name:
            self.copy_status.setText(f"正在复制 {name}... ({current}/{total})")

    def _on_copy_finished(self, msg: str, results: list):
        self.copy_progress.setVisible(False)
        self.copy_all_btn.setEnabled(True)
        self.check_btn.setEnabled(True)
        self.copy_status.setText(f"✅ {msg}")
        self.copy_status.setStyleSheet("color: #3fb950; font-size: 11px;")
        self._refresh_model_list()
        self._save_partial()

    # ========== 步骤切换 ==========

    def _prev_step(self):
        if self._current_step > 0:
            self._current_step -= 1
            self._update_step_ui()

    def _next_step(self):
        # 验证当前步骤
        if self._current_step == 0:
            if not self.folder_edit.text().strip():
                QMessageBox.warning(self, "提示", "请指定模型下载文件夹路径")
                return
        elif self._current_step == 1:
            # 工作流可以留空（用默认）
            pass
        elif self._current_step == 2:
            # 最后一步
            self._save_config()
            self.accept()
            return

        if self._current_step < 2:
            self._current_step += 1
            self._update_step_ui()
            # 到第3步时刷新模型列表并显示目录
            if self._current_step == 2 and self.folder_edit.text().strip():
                folder = self.folder_edit.text().strip()
                self.step3_folder_label.setText(f"当前目录：{folder}")
                self._refresh_model_list()

    def _update_step_ui(self):
        self.step1_widget.setVisible(self._current_step == 0)
        self.step2_widget.setVisible(self._current_step == 1)
        self.step3_widget.setVisible(self._current_step == 2)

        # 更新步骤指示器
        for i, lbl in enumerate(self.step_labels):
            if i < self._current_step:
                lbl.setStyleSheet("""
                    QLabel {
                        background: #007acc; color: white;
                        border-radius: 4px; font-size: 11px; padding: 0 12px;
                    }
                """)
            elif i == self._current_step:
                lbl.setStyleSheet("""
                    QLabel {
                        background: #0e639c; color: white; font-weight: bold;
                        border-radius: 4px; font-size: 11px; padding: 0 12px;
                    }
                """)
            else:
                lbl.setStyleSheet("""
                    QLabel {
                        background: #2d2d30; color: #888;
                        border-radius: 4px; font-size: 11px; padding: 0 12px;
                    }
                """)

        self.btn_prev.setEnabled(self._current_step > 0)

        if self._current_step == 2:
            self.btn_next.setVisible(False)
            self.btn_finish.setVisible(True)
        else:
            self.btn_next.setVisible(True)
            self.btn_finish.setVisible(False)
            self.btn_next.setText("下一步 →" if self._current_step < 1 else "下一步 →")

    # ========== 保存/加载 ==========

    def _save_partial(self):
        """保存当前步骤设置（不关闭对话框）"""
        cfg = self.cfg
        cfg.set("comfyui.server_address", self.addr_edit.text().strip() or "127.0.0.1:8188")
        cfg.set("comfyui.download_folder", self.folder_edit.text().strip())
        cfg.set("comfyui.last_model", "ltx23_sulphur2")
        cfg.save()

    def closeEvent(self, event):
        if hasattr(self, '_copy_worker') and self._copy_worker and self._copy_worker.isRunning():
            self._copy_worker.terminate()
            self._copy_worker.wait()
        self._save_partial()
        super().closeEvent(event)

    def _save_config(self):
        """保存所有设置"""
        cfg = self.cfg

        cfg.set("comfyui.server_address", self.addr_edit.text().strip() or "127.0.0.1:8188")
        cfg.set("comfyui.download_folder", self.folder_edit.text().strip())
        cfg.set("comfyui.last_model", "ltx23_sulphur2")
        cfg.set("comfyui.setup_completed", True)

        # 工作流（保存并发刷新信号）
        self._save_workflow_only()

        cfg.save()

    def _load_settings(self):
        comfy_cfg = self.cfg.get("comfyui", {})

        self.addr_edit.setText(comfy_cfg.get("server_address", "127.0.0.1:8188"))
        self.folder_edit.setText(comfy_cfg.get("download_folder", ""))

        # 回填当前模式已保存的工作流路径（没有则留空用默认）
        last_id = comfy_cfg.get(f"last_workflow_{self.mode}", "")
        wf_entry = next(
            (w for w in comfy_cfg.get("workflows", []) if w.get("id") == last_id),
            None,
        )
        if wf_entry and wf_entry.get("path") and os.path.exists(wf_entry["path"]):
            self.workflow_edit.setText(wf_entry["path"])
        else:
            self.workflow_edit.setText("")

        if self.folder_edit.text():
            self._check_folder()
