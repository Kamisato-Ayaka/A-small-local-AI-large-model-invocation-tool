"""
本地壁纸文件夹导入对话框

扫描本地壁纸根目录（默认 Background_Recommend/Wallpaper_File），
每个子文件夹代表一个从 Wallpaper Engine 复制出来的壁纸，
按 project.json 识别标题/类型，并挑选可直接使用的媒体文件。
"""
import json
import os
import shutil

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QFileDialog, QMessageBox,
)

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
GIF_EXTS = (".gif",)
VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".avi", ".mov")

_TYPE_LABEL = {
    "video": ("🎬", "视频动态壁纸"),
    "image": ("🖼️", "静态图片"),
    "scene": ("📷", "场景壁纸(仅静态预览)"),
    "web": ("📷", "网页壁纸(仅静态预览)"),
}


def default_wallpaper_root() -> str:
    """默认壁纸根目录：优先 程序目录同级 Background_Recommend/Wallpaper_File，其次程序目录内"""
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(os.path.dirname(app_dir), "Background_Recommend", "Wallpaper_File"),
        os.path.join(app_dir, "Background_Recommend", "Wallpaper_File"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[-1]


def pick_media_file(folder: str) -> str:
    """在一个壁纸文件夹里挑选可直接使用的媒体文件（含 extracted/ 子目录）
    优先级：GIF > 视频 > 普通图片，同类中取体积最大的"""
    files = []
    for d in (folder, os.path.join(folder, "extracted")):
        try:
            files += [os.path.join(d, n) for n in os.listdir(d)
                      if os.path.isfile(os.path.join(d, n))]
        except OSError:
            continue

    def best(exts):
        cands = [p for p in files if p.lower().endswith(exts)]
        if not cands:
            return ""
        return max(cands, key=lambda p: os.path.getsize(p))

    for exts in (GIF_EXTS, VIDEO_EXTS, IMAGE_EXTS):
        hit = best(exts)
        if hit:
            return hit
    return ""


def scan_local_wallpapers(root_dir: str) -> list:
    """扫描壁纸根目录：每个子文件夹 = 一个壁纸
    返回 [{path, file, title, type}]（无可用媒体的子文件夹跳过）"""
    results = []
    if not os.path.isdir(root_dir):
        return results
    for name in sorted(os.listdir(root_dir)):
        folder = os.path.join(root_dir, name)
        if not os.path.isdir(folder):
            continue
        wtype, title = "", name
        pj = os.path.join(folder, "project.json")
        if os.path.exists(pj):
            try:
                with open(pj, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                wtype = (data.get("type") or "").strip().lower()
                title = data.get("title") or name
            except (OSError, ValueError):
                pass
        media = pick_media_file(folder)
        if not media:
            continue
        # 提取出视频后按实际媒体类型显示
        if media.lower().endswith(VIDEO_EXTS + GIF_EXTS):
            wtype = "video"
        elif not wtype:
            wtype = "image"
        results.append({"path": folder, "file": media, "title": title, "type": wtype})
    return results


class WallpaperImportDialog(QDialog):
    """从本地壁纸文件夹选择壁纸；确认后回调 (媒体文件路径)"""

    DARK_QSS = """
        QDialog {
            background: #1a1a2e; color: #d4d4d4; font-family: "Microsoft YaHei";
        }
        QLabel { color: #d4d4d4; font-size: 12px; }
        QLineEdit {
            background: rgba(255,255,255,0.06); color: #e0f0ff;
            border: 1px solid rgba(0,212,255,0.3); border-radius: 4px;
            padding: 4px 8px; font-size: 12px;
        }
        QLineEdit:focus { border-color: #00d4ff; }
        QPushButton {
            background: rgba(255,255,255,0.08); color: #c0d8e8;
            border: 1px solid rgba(255,255,255,0.15); border-radius: 5px;
            padding: 5px 12px; font-size: 12px; font-weight: 600;
        }
        QPushButton:hover {
            background: rgba(0,212,255,0.2); color: #fff;
            border: 1px solid rgba(0,212,255,0.5);
        }
        QPushButton:disabled {
            background: rgba(80,80,80,0.3); color: #555;
            border: 1px solid rgba(80,80,80,0.3);
        }
        QPushButton#primaryBtn {
            background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #007acc, stop:1 #00d4ff);
            color: white; border: none; font-weight: 700;
        }
        QPushButton#primaryBtn:hover {
            background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #0a8bde, stop:1 #1fe0ff);
        }
        QPushButton#secondaryBtn {
            background: rgba(0,212,255,0.08); color: #00d4ff;
            border: 1px solid rgba(0,212,255,0.3); font-weight: 600;
        }
        QPushButton#secondaryBtn:hover {
            background: rgba(0,212,255,0.18); color: #fff;
        }
        QListWidget {
            background: rgba(0,0,0,0.4); color: #e0f0ff;
            border: 1px solid rgba(0,212,255,0.15); border-radius: 6px;
            font-size: 12px; padding: 4px;
        }
        QListWidget::item { padding: 6px 8px; border-radius: 3px; }
        QListWidget::item:selected {
            background: rgba(0,212,255,0.25); color: #fff;
        }
        QListWidget::item:hover {
            background: rgba(0,212,255,0.1);
        }
    """

    def __init__(self, parent=None, on_apply=None, root_dir: str = ""):
        super().__init__(parent)
        self.setWindowTitle("选择壁纸（本地壁纸文件夹）")
        self.resize(620, 520)
        self.setStyleSheet(self.DARK_QSS)
        self._on_apply = on_apply
        self._root = root_dir or default_wallpaper_root()

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        row = QHBoxLayout()
        row.addWidget(QLabel("壁纸目录："))
        from PyQt5.QtWidgets import QLineEdit
        self.dir_edit = QLineEdit(self._root)
        row.addWidget(self.dir_edit, 1)
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_dir)
        row.addWidget(browse_btn)
        scan_btn = QPushButton("扫描")
        scan_btn.clicked.connect(self._scan)
        row.addWidget(scan_btn)
        layout.addLayout(row)

        hint = QLabel(
            "每个子文件夹代表一个壁纸（从 Wallpaper Engine 复制出来即可）。\n"
            "双击或点「应用选中壁纸」立即设为整个程序窗口的背景（无需再点设置里的保存）。\n"
            "🎬视频 / 🖼️图片可直接使用；📷场景壁纸可点下方提取按钮挖出内嵌的视频/高清图。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda _: self._apply())
        self.list_widget.itemSelectionChanged.connect(self._update_extract_btn)
        layout.addWidget(self.list_widget, 1)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # .pkg 素材提取（后台线程）
        from PyQt5.QtCore import QThread, pyqtSignal
        self.extract_btn = QPushButton("🔓 提取选中壁纸的 .pkg 素材（视频/高清图）")
        self.extract_btn.setObjectName("secondaryBtn")
        self.extract_btn.setToolTip("解析壁纸文件夹里的 scene.pkg，把内嵌的 MP4 视频 / 高清纹理提取到 extracted/ 子文件夹")
        self.extract_btn.setEnabled(False)
        self.extract_btn.clicked.connect(self._start_extract)
        layout.addWidget(self.extract_btn)

        self.clean_btn = QPushButton("🗑 一键删除所有 [场景壁纸(仅静态预览)] 文件夹")
        self.clean_btn.setObjectName("secondaryBtn")
        self.clean_btn.setToolTip(
            "删除壁纸目录内 project.json 类型为 scene/web、且未提取出视频的壁纸文件夹\n"
            "（提取过视频的会显示为视频动态壁纸，不会被删除）。删除后不可恢复。")
        self.clean_btn.clicked.connect(self._clean_scene_folders)
        layout.addWidget(self.clean_btn)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        apply_btn = QPushButton("应用选中壁纸")
        apply_btn.setObjectName("primaryBtn")
        apply_btn.clicked.connect(self._apply)
        btn_row.addWidget(apply_btn)
        layout.addLayout(btn_row)

        self._scan()

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择壁纸根目录", self.dir_edit.text() or "")
        if d:
            self.dir_edit.setText(d)
            self._scan()

    def _scan(self):
        self.list_widget.clear()
        root = self.dir_edit.text().strip()
        if not os.path.isdir(root):
            self.status_label.setText("目录不存在，请点「浏览...」选择壁纸根目录。")
            self.extract_btn.setEnabled(False)
            return
        items = scan_local_wallpapers(root)
        for it in items:
            icon, label = _TYPE_LABEL.get(it["type"], ("🖼️", "图片"))
            item = QListWidgetItem(f"{icon} {it['title']}   [{label}]")
            item.setData(Qt.UserRole, it["file"])
            item.setData(Qt.UserRole + 1, it["path"])
            self.list_widget.addItem(item)
        self.status_label.setText(
            f"共 {len(items)} 个壁纸" if items else "未找到壁纸。每个壁纸应为子文件夹（含视频/图片或 preview.jpg）。")
        # 选中项所在文件夹含 .pkg 时启用提取
        cur = self.list_widget.currentItem()
        folder = cur.data(Qt.UserRole + 1) if cur else ""
        has_pkg = bool(folder) and any(
            n.lower().endswith(".pkg") for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n)))
        self.extract_btn.setEnabled(has_pkg)

    def _update_extract_btn(self):
        """选中项所在文件夹含 .pkg 时启用提取按钮"""
        item = self.list_widget.currentItem()
        folder = item.data(Qt.UserRole + 1) if item else ""
        has_pkg = False
        if folder and os.path.isdir(folder):
            has_pkg = any(
                n.lower().endswith(".pkg") and os.path.isfile(os.path.join(folder, n))
                for n in os.listdir(folder))
        self.extract_btn.setEnabled(has_pkg)

    def _start_extract(self):
        item = self.list_widget.currentItem()
        folder = item.data(Qt.UserRole + 1) if item else ""
        if not folder:
            QMessageBox.information(self, "提示", "请先在列表中选中一个壁纸。")
            return
        pkg = ""
        for n in os.listdir(folder):
            if n.lower().endswith(".pkg") and os.path.isfile(os.path.join(folder, n)):
                pkg = os.path.join(folder, n)
                break
        if not pkg:
            return
        self.extract_btn.setEnabled(False)
        self.status_label.setText("正在提取 .pkg 素材（大文件需要几十秒）...")
        from PyQt5.QtCore import QThread, pyqtSignal

        class _Worker(QThread):
            done = pyqtSignal(list, str)

            def __init__(self, pkg_path, out_dir):
                super().__init__()
                self._pkg, self._out = pkg_path, out_dir

            def run(self):
                try:
                    from core.we_pkg_extract import extract_media
                    saved = extract_media(self._pkg, self._out)
                    self.done.emit(saved, "")
                except Exception as e:  # noqa: BLE001
                    self.done.emit([], str(e))

        out_dir = os.path.join(folder, "extracted")
        self._worker = _Worker(pkg, out_dir)
        self._worker.done.connect(self._extract_done)
        self._worker.start()

    def _extract_done(self, saved: list, err: str):
        if err:
            self.status_label.setText(f"提取失败：{err}")
        else:
            self.status_label.setText(
                f"提取完成：{len(saved)} 个素材已保存到 extracted/，列表已刷新（可直接双击应用）。")
        self._scan()

    def _clean_scene_folders(self):
        """一键删除所有 [场景壁纸(仅静态预览)] 类型的壁纸文件夹"""
        root = self.dir_edit.text().strip()
        targets = [it for it in scan_local_wallpapers(root)
                   if it["type"] in ("scene", "web")]
        if not targets:
            QMessageBox.information(self, "提示", "没有找到 [场景壁纸(仅静态预览)] 类型的壁纸文件夹。")
            return

        names = "\n".join(f"· {it['title']}" for it in targets[:15])
        more = f"\n... 等共 {len(targets)} 个" if len(targets) > 15 else ""
        ret = QMessageBox.question(
            self, "确认删除",
            f"将删除 {len(targets)} 个场景壁纸文件夹（不可恢复）：\n\n{names}{more}\n\n确定删除？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return

        deleted, failed = 0, []
        for it in targets:
            try:
                shutil.rmtree(it["path"])
                deleted += 1
            except OSError as e:
                failed.append(f"· {it['title']}：{e}")
        if failed:
            QMessageBox.warning(
                self, "部分删除失败",
                f"已删除 {deleted} 个，{len(failed)} 个失败（可能正被程序用作当前壁纸）：\n\n"
                + "\n".join(failed[:10]))
        self._scan()

    def _apply(self):
        item = self.list_widget.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先在列表中选中一个壁纸。")
            return
        if self._on_apply:
            self._on_apply(item.data(Qt.UserRole))
        self.accept()
