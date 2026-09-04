"""
文件资源管理器 - 左侧面板
"""
import os
from PyQt5.QtWidgets import (
    QTreeView, QFileSystemModel, QVBoxLayout, QWidget, QLabel, QMenu,
    QAction, QInputDialog, QMessageBox, QHBoxLayout, QPushButton
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon, QFont


class FileExplorer(QWidget):
    """文件资源管理器"""

    file_opened = pyqtSignal(str)  # 文件被打开时发出信号

    def __init__(self, root_path: str, parent=None):
        super().__init__(parent)
        self.root_path = os.path.abspath(root_path)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 6)

        title = QLabel("资源管理器")
        title.setStyleSheet("color: #cccccc; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        # 新建文件按钮
        btn_new_file = QPushButton()
        btn_new_file.setFixedSize(24, 24)
        btn_new_file.setToolTip("新建文件")
        btn_new_file.setStyleSheet("""
            QPushButton { border: none; background: transparent; color: #969696; }
            QPushButton:hover { color: #ffffff; background: #2a2d2e; border-radius: 3px; }
        """)
        btn_new_file.setText("📄")
        btn_new_file.clicked.connect(self.new_file)
        header_layout.addWidget(btn_new_file)

        # 新建文件夹按钮
        btn_new_folder = QPushButton()
        btn_new_folder.setFixedSize(24, 24)
        btn_new_folder.setToolTip("新建文件夹")
        btn_new_folder.setStyleSheet("""
            QPushButton { border: none; background: transparent; color: #969696; }
            QPushButton:hover { color: #ffffff; background: #2a2d2e; border-radius: 3px; }
        """)
        btn_new_folder.setText("📁")
        btn_new_folder.clicked.connect(self.new_folder)
        header_layout.addWidget(btn_new_folder)

        # 刷新按钮
        btn_refresh = QPushButton()
        btn_refresh.setFixedSize(24, 24)
        btn_refresh.setToolTip("刷新")
        btn_refresh.setStyleSheet("""
            QPushButton { border: none; background: transparent; color: #969696; }
            QPushButton:hover { color: #ffffff; background: #2a2d2e; border-radius: 3px; }
        """)
        btn_refresh.setText("🔄")
        btn_refresh.clicked.connect(self.refresh)
        header_layout.addWidget(btn_refresh)

        layout.addWidget(header)

        # 分隔线
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #252526;")
        layout.addWidget(line)

        # 文件树
        self.model = QFileSystemModel()
        self.model.setRootPath(self.root_path)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(self.root_path))
        self.tree.setHeaderHidden(True)
        self.tree.setColumnHidden(1, True)
        self.tree.setColumnHidden(2, True)
        self.tree.setColumnHidden(3, True)
        self.tree.setIndentation(14)
        self.tree.setStyleSheet("""
            QTreeView {
                background: #252526;
                border: none;
                outline: none;
                color: #cccccc;
            }
            QTreeView::item {
                padding: 2px 0;
                height: 22px;
            }
            QTreeView::item:selected {
                background: #37373d;
                color: #ffffff;
            }
            QTreeView::item:hover {
                background: #2a2d2e;
            }
            QTreeView::branch {
                background: transparent;
            }
            QTreeView::branch:has-children:!has-siblings:closed,
            QTreeView::branch:closed:has-children:has-siblings {
                image: none;
            }
        """)

        # 设置字体
        font = QFont("Microsoft YaHei", 10)
        self.tree.setFont(font)

        self.tree.doubleClicked.connect(self.on_double_clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)

        layout.addWidget(self.tree)

    def on_double_clicked(self, index):
        path = self.model.filePath(index)
        if os.path.isfile(path):
            self.file_opened.emit(path)

    def show_context_menu(self, position):
        index = self.tree.indexAt(position)
        path = self.model.filePath(index) if index.isValid() else self.root_path

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #252526;
                color: #cccccc;
                border: 1px solid #454545;
                padding: 4px 0;
            }
            QMenu::item {
                padding: 6px 24px;
            }
            QMenu::item:selected {
                background: #094771;
            }
        """)

        if os.path.isfile(path):
            action_open = QAction("打开", self)
            action_open.triggered.connect(lambda: self.file_opened.emit(path))
            menu.addAction(action_open)

            menu.addSeparator()

            action_rename = QAction("重命名", self)
            action_rename.triggered.connect(lambda: self.rename_file(path))
            menu.addAction(action_rename)

            action_delete = QAction("删除", self)
            action_delete.triggered.connect(lambda: self.delete_file(path))
            menu.addAction(action_delete)
        else:
            action_new_file = QAction("新建文件", self)
            action_new_file.triggered.connect(lambda: self.new_file_in_dir(path))
            menu.addAction(action_new_file)

            action_new_folder = QAction("新建文件夹", self)
            action_new_folder.triggered.connect(lambda: self.new_folder_in_dir(path))
            menu.addAction(action_new_folder)

            menu.addSeparator()

            action_rename = QAction("重命名", self)
            action_rename.triggered.connect(lambda: self.rename_file(path))
            menu.addAction(action_rename)

            if path != self.root_path:
                action_delete = QAction("删除", self)
                action_delete.triggered.connect(lambda: self.delete_file(path))
                menu.addAction(action_delete)

        menu.exec_(self.tree.viewport().mapToGlobal(position))

    def new_file(self):
        self.new_file_in_dir(self.root_path)

    def new_file_in_dir(self, directory):
        name, ok = QInputDialog.getText(self, "新建文件", "文件名:")
        if ok and name:
            filepath = os.path.join(directory, name)
            if os.path.exists(filepath):
                QMessageBox.warning(self, "提示", "文件已存在！")
                return
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write('')
                self.file_opened.emit(filepath)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"创建文件失败: {str(e)}")

    def new_folder(self):
        self.new_folder_in_dir(self.root_path)

    def new_folder_in_dir(self, directory):
        name, ok = QInputDialog.getText(self, "新建文件夹", "文件夹名:")
        if ok and name:
            folderpath = os.path.join(directory, name)
            if os.path.exists(folderpath):
                QMessageBox.warning(self, "提示", "文件夹已存在！")
                return
            try:
                os.makedirs(folderpath)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"创建文件夹失败: {str(e)}")

    def rename_file(self, path):
        old_name = os.path.basename(path)
        new_name, ok = QInputDialog.getText(self, "重命名", "新名称:", text=old_name)
        if ok and new_name and new_name != old_name:
            new_path = os.path.join(os.path.dirname(path), new_name)
            try:
                os.rename(path, new_path)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"重命名失败: {str(e)}")

    def delete_file(self, path):
        name = os.path.basename(path)
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除 \"{name}\" 吗？\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                import shutil
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除失败: {str(e)}")

    def refresh(self):
        self.model.setRootPath(self.root_path)
        self.tree.setRootIndex(self.model.index(self.root_path))

    def set_root_path(self, new_path: str):
        """切换根目录（项目文件夹）"""
        import os
        new_path = os.path.abspath(new_path)
        if not os.path.isdir(new_path):
            return
        self.root_path = new_path
        self.model.setRootPath(new_path)
        self.tree.setRootIndex(self.model.index(new_path))
        # 更新路径标签
        if hasattr(self, 'path_label'):
            self.path_label.setText(os.path.basename(new_path))
