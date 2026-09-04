"""
A Small Local AI Runner GUI 启动器
- 深色主题，VS Code 风格
- 显示依赖检查和安装进度
- 实时日志输出
- 一键启动主程序
"""
import os
import sys
import subprocess
import threading
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QTextEdit, QFrame, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor, QTextCursor


class InstallWorker(QObject):
    """后台安装工作线程"""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)  # success, message

    def __init__(self, requirements, python_exe):
        super().__init__()
        self.requirements = requirements
        self.python_exe = python_exe
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            total = len(self.requirements)
            missing = []

            # 第一步：检查
            self.status_signal.emit("检查依赖...")
            for i, (name, pkg) in enumerate(self.requirements):
                if self._stop:
                    return

                self.progress_signal.emit(int((i / total) * 30))  # 前 30% 检查
                self.log_signal.emit(f"🔍 检查 {name}...")

                try:
                    __import__(name)
                    self.log_signal.emit(f"   ✓ {name} 已安装")
                except ImportError:
                    self.log_signal.emit(f"   ✗ {name} 未安装")
                    missing.append((name, pkg))

            if not missing:
                self.progress_signal.emit(100)
                self.status_signal.emit("所有依赖已就绪")
                self.log_signal.emit("")
                self.log_signal.emit("✓ 所有依赖已就绪，可以启动")
                self.finished_signal.emit(True, "ready")
                return

            # 第二步：安装
            self.log_signal.emit("")
            self.log_signal.emit(f"📦 发现 {len(missing)} 个缺失依赖，开始安装...")
            self.log_signal.emit("")

            for i, (name, pkg) in enumerate(missing):
                if self._stop:
                    return

                self.status_signal.emit(f"正在安装 {name}...")
                self.progress_signal.emit(30 + int((i / len(missing)) * 60))  # 30%-90% 安装
                self.log_signal.emit(f"⚙️  正在安装 {name} ({i+1}/{len(missing)})...")
                self.log_signal.emit(f"   命令: pip install {pkg}")

                success, output = self._install_package(pkg)

                if success:
                    # 验证
                    try:
                        __import__(name)
                        self.log_signal.emit(f"   ✓ {name} 安装成功")
                    except ImportError:
                        self.log_signal.emit(f"   ✗ {name} 安装后仍无法导入")
                        self.finished_signal.emit(False, f"{name} 安装失败")
                        return
                else:
                    self.log_signal.emit(f"   ✗ {name} 安装失败")
                    if output:
                        for line in output.strip().split("\n")[-5:]:
                            self.log_signal.emit(f"     {line}")
                    self.finished_signal.emit(False, f"{name} 安装失败")
                    return

                self.log_signal.emit("")

            # 完成
            self.progress_signal.emit(100)
            self.status_signal.emit("安装完成")
            self.log_signal.emit("✓ 所有依赖安装完成！")
            self.finished_signal.emit(True, "installed")

        except Exception as e:
            self.log_signal.emit(f"")
            self.log_signal.emit(f"❌ 错误: {e}")
            import traceback
            self.log_signal.emit(traceback.format_exc())
            self.finished_signal.emit(False, str(e))

    def _install_package(self, pkg: str):
        """安装 pip 包并捕获输出"""
        try:
            result = subprocess.run(
                [self.python_exe, "-m", "pip", "install", pkg],
                capture_output=True,
                text=True,
                timeout=300
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "安装超时（超过 5 分钟）"
        except Exception as e:
            return False, str(e)


class LauncherWindow(QMainWindow):
    """启动器主窗口"""

    def __init__(self, requirements, app_script, parent=None):
        super().__init__(parent)
        self.requirements = requirements
        self.app_script = app_script
        self.python_exe = sys.executable
        self._worker = None
        self._thread = None

        self._init_ui()
        self._set_style()

        # 延迟开始检查
        QTimer.singleShot(300, self._start_check)

    def _init_ui(self):
        self.setWindowTitle("A Small Local AI Runner 启动器")
        self.setFixedSize(560, 480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        # 居中
        self.move(
            (self.screen().width() - self.width()) // 2,
            (self.screen().height() - self.height()) // 2
        )

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(0)

        # 标题
        title = QLabel("A Small Local AI Runner")
        title.setStyleSheet("font-size: 28px; font-weight: bold; color: #007acc;")
        title.setFont(QFont("Microsoft YaHei", 28, QFont.Bold))
        layout.addWidget(title)

        subtitle = QLabel("本地 AI 代码开发助手")
        subtitle.setStyleSheet("color: #808080; font-size: 13px; margin-top: 2px;")
        subtitle.setFont(QFont("Microsoft YaHei", 10))
        layout.addWidget(subtitle)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #2d2d30; margin-top: 18px; margin-bottom: 18px;")
        layout.addWidget(line)

        # 状态文字
        self.status_label = QLabel("正在初始化...")
        self.status_label.setStyleSheet("color: #cccccc; font-size: 13px;")
        self.status_label.setFont(QFont("Microsoft YaHei", 10))
        layout.addWidget(self.status_label)
        layout.addSpacing(8)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: #2d2d30;
                border: none;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: #007acc;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.progress_bar)
        layout.addSpacing(16)

        # 日志区域
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("""
            QTextEdit {
                background: #252526;
                color: #9cdcfe;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        layout.addWidget(self.log_text, 1)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedSize(80, 32)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.cancel_btn)

        self.start_btn = QPushButton("启动")
        self.start_btn.setFixedSize(100, 32)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._on_start)
        btn_layout.addWidget(self.start_btn)

        layout.addSpacing(16)
        layout.addLayout(btn_layout)

    def _set_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #1e1e1e;
            }
            QPushButton {
                background: #007acc;
                color: white;
                border: none;
                border-radius: 4px;
                font-family: "Microsoft YaHei";
                font-size: 13px;
            }
            QPushButton:hover {
                background: #1177bb;
            }
            QPushButton:pressed {
                background: #005a9e;
            }
            QPushButton:disabled {
                background: #3c3c3c;
                color: #808080;
            }
        """)

    def _append_log(self, text: str):
        """添加日志"""
        # 处理 emoji 和特殊字符
        self.log_text.moveCursor(QTextCursor.End)
        self.log_text.insertPlainText(text + "\n")
        self.log_text.moveCursor(QTextCursor.End)

    def _set_status(self, text: str):
        self.status_label.setText(text)

    def _set_progress(self, value: int):
        self.progress_bar.setValue(value)

    def _start_check(self):
        """开始检查依赖"""
        self._thread = threading.Thread(target=self._run_check, daemon=True)
        self._thread.start()

    def _run_check(self):
        """运行检查和安装（后台线程）"""
        self._worker = InstallWorker(self.requirements, self.python_exe)

        # 连接信号
        self._worker.log_signal.connect(self._append_log)
        self._worker.progress_signal.connect(self._set_progress)
        self._worker.status_signal.connect(self._set_status)
        self._worker.finished_signal.connect(self._on_finished)

        self._worker.run()

    def _on_finished(self, success: bool, message: str):
        """安装完成"""
        if success:
            self._set_status("✓ 准备就绪")
            self.start_btn.setEnabled(True)
            self.cancel_btn.setText("关闭")
        else:
            self._set_status("✗ 安装失败")
            self.start_btn.setText("重试")
            self.start_btn.setEnabled(True)
            QMessageBox.critical(
                self, "安装失败",
                f"依赖安装失败：{message}\n\n请检查网络连接后点击重试，或手动安装依赖。"
            )

    def _on_start(self):
        """启动主程序"""
        if self.start_btn.text() == "重试":
            # 重试
            self.start_btn.setEnabled(False)
            self.start_btn.setText("启动")
            self.log_text.clear()
            self.progress_bar.setValue(0)
            self._start_check()
            return

        # 启动主程序
        self._set_status("正在启动 A Small Local AI Runner...")
        self.start_btn.setEnabled(False)

        try:
            subprocess.Popen([self.python_exe, self.app_script])
            QTimer.singleShot(800, self.close)
        except Exception as e:
            QMessageBox.critical(self, "启动失败", f"无法启动 A Small Local AI Runner:\n{str(e)}")
            self.start_btn.setEnabled(True)
            self._set_status("启动失败")

    def _on_cancel(self):
        """取消/关闭"""
        if self._worker:
            self._worker.stop()
        self.close()


if __name__ == "__main__":
    # 测试用
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    win = LauncherWindow(
        requirements=[("requests", "requests>=2.28.0")],
        app_script="app.py"
    )
    win.show()
    sys.exit(app.exec_())
