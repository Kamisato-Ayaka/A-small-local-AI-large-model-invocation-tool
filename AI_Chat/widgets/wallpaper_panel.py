"""
壁纸页面 - 独立选项卡，极简版：导入壁纸 + 透明度 + 背景色
"""
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QGroupBox, QSpinBox, QFormLayout, QMessageBox, QScrollArea
)
from PyQt5.QtCore import Qt, pyqtSignal


class WallpaperPanel(QWidget):
    """壁纸配置独立页面（极简）"""

    wallpaper_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        from core.config import get_config_manager
        self.cfg = get_config_manager()
        self._init_ui()
        self._load_config()

    def _init_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # 标题
        title = QLabel("🖼️ 壁纸与外观")
        title.setStyleSheet("color: #00d4ff; font-size: 18px; font-weight: 800; letter-spacing: 1px;")
        layout.addWidget(title)

        # 当前壁纸状态（一行文字）
        self.cur_wp_label = QLabel("当前壁纸：（未设置，使用纯色背景）")
        self.cur_wp_label.setStyleSheet("color: #8aa0b0; font-size: 12px; padding: 4px 0;")
        self.cur_wp_label.setWordWrap(True)
        layout.addWidget(self.cur_wp_label)

        # ---- 壁纸操作组 ----
        pick_group = QGroupBox("壁纸")
        pick_layout = QVBoxLayout(pick_group)
        pick_layout.setSpacing(10)

        row = QHBoxLayout()
        self.btn_we_import = QPushButton("📁 导入 Wallpaper Engine 壁纸文件夹...")
        self.btn_we_import.setFixedHeight(36)
        self.btn_we_import.setCursor(Qt.PointingHandCursor)
        self.btn_we_import.setStyleSheet(self._btn_primary())
        self.btn_we_import.setToolTip("扫描本地壁纸文件夹（每个子文件夹=一个壁纸，支持 Wallpaper Engine 复制出来的目录）")
        row.addWidget(self.btn_we_import)

        self.btn_clear_wp = QPushButton("❌ 清除壁纸")
        self.btn_clear_wp.setFixedSize(120, 36)
        self.btn_clear_wp.setCursor(Qt.PointingHandCursor)
        self.btn_clear_wp.setStyleSheet(self._btn_danger())
        row.addWidget(self.btn_clear_wp)

        row.addStretch()
        pick_layout.addLayout(row)

        layout.addWidget(pick_group)

        # ---- 透明度设置 ----
        trans_group = QGroupBox("外观透明度")
        trans_form = QFormLayout(trans_group)
        trans_form.setSpacing(12)

        self.text_opacity_spin = QSpinBox()
        self.text_opacity_spin.setRange(0, 100)
        self.text_opacity_spin.setSuffix(" %")
        self.text_opacity_spin.setToolTip("所有文字的最终透明度（已自动补偿界面前端透明度的衰减）")
        trans_form.addRow("文字透明度：", self.text_opacity_spin)

        self.ui_transparency_spin = QSpinBox()
        self.ui_transparency_spin.setRange(0, 100)
        self.ui_transparency_spin.setSuffix(" %")
        self.ui_transparency_spin.setToolTip("调到 100% 时界面元素完全隐藏，只剩壁纸")
        trans_form.addRow("界面前端透明度：", self.ui_transparency_spin)

        layout.addWidget(trans_group)

        # ---- 背景颜色 ----
        color_group = QGroupBox("纯色背景（未设壁纸时使用）")
        color_form = QFormLayout(color_group)
        color_form.setSpacing(12)

        self.bg_color_combo = QComboBox()
        self.bg_color_combo.addItems(["#16213e", "#1e1e2e", "#0f0f23", "#1a1a2e", "#252526", "#111111"])
        self.bg_color_combo.setEditable(True)
        color_form.addRow("背景颜色：", self.bg_color_combo)

        layout.addWidget(color_group)

        # ---- 保存 ----
        save_row = QHBoxLayout()
        save_row.addStretch()
        self.btn_save = QPushButton("💾 保存全部设置")
        self.btn_save.setFixedHeight(36)
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setStyleSheet(self._btn_primary())
        save_row.addWidget(self.btn_save)
        layout.addLayout(save_row)

        layout.addStretch()

        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # 信号
        self.btn_we_import.clicked.connect(self._open_we_import)
        self.btn_clear_wp.clicked.connect(self._clear_wallpaper)
        self.btn_save.clicked.connect(self._save_all)
        self.text_opacity_spin.valueChanged.connect(lambda v: self.cfg.set("theme.text_opacity", v))
        self.ui_transparency_spin.valueChanged.connect(lambda v: self.cfg.set("theme.ui_transparency", v))
        self.bg_color_combo.currentTextChanged.connect(lambda t: self.cfg.set("theme.chat_bg_color", t))

    # ============================================================
    # 样式
    # ============================================================

    def _btn_primary(self) -> str:
        return ("QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                "stop:0 #007acc, stop:1 #00d4ff); color: white; border: none;"
                " border-radius: 6px; font-weight: 700; padding: 6px 16px; }"
                "QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                "stop:0 #0a8bde, stop:1 #1fe0ff); }")

    def _btn_danger(self) -> str:
        return ("QPushButton { background: rgba(244,67,54,0.15); color: #f44336;"
                " border: 1px solid rgba(244,67,54,0.4); border-radius: 6px;"
                " font-weight: 600; padding: 6px 14px; }"
                "QPushButton:hover { background: rgba(244,67,54,0.3); }")

    # ============================================================
    # 配置加载/保存
    # ============================================================

    def _load_config(self):
        theme = self.cfg.get("theme", {})
        self.text_opacity_spin.setValue(int(theme.get("text_opacity", 100)))
        self.ui_transparency_spin.setValue(int(theme.get("ui_transparency", 50)))
        color = theme.get("chat_bg_color", "#16213e")
        idx = self.bg_color_combo.findText(color)
        if idx >= 0:
            self.bg_color_combo.setCurrentIndex(idx)
        else:
            self.bg_color_combo.setCurrentText(color)
        self._update_current_wp_label()

    def _save_all(self):
        self.cfg.set("theme.text_opacity", self.text_opacity_spin.value())
        self.cfg.set("theme.ui_transparency", self.ui_transparency_spin.value())
        self.cfg.set("theme.chat_bg_color", self.bg_color_combo.currentText())
        self.wallpaper_changed.emit()
        QMessageBox.information(self, "保存成功", "壁纸与外观设置已保存")

    # ============================================================
    # 壁纸操作
    # ============================================================

    def _update_current_wp_label(self):
        path = self.cfg.get("theme.chat_bg_image", "")
        if path:
            name = os.path.basename(path)
            self.cur_wp_label.setText(f"当前壁纸：📁 {name}")
        else:
            self.cur_wp_label.setText("当前壁纸：（未设置，使用纯色背景）")

    def _clear_wallpaper(self):
        self.cfg.set("theme.chat_bg_image", "")
        self._update_current_wp_label()
        self.wallpaper_changed.emit()

    def _open_we_import(self):
        from widgets.wallpaper_import_dialog import WallpaperImportDialog
        def on_apply(media_path: str):
            self.cfg.set("theme.chat_bg_image", media_path)
            self._update_current_wp_label()
            self.wallpaper_changed.emit()

        dlg = WallpaperImportDialog(self, on_apply=on_apply)
        dlg.exec_()

    # ============================================================
    # 外部接口
    # ============================================================

    def apply_theme(self):
        self._load_config()

    def set_ui_opacity(self, opacity: float):
        pass

    def reload_theme(self):
        self.apply_theme()
