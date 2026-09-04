"""
AI Chat — 依赖安装 & 启动器
双击运行此文件：先点「📦 安装依赖」装 PyQt5 / requests / fastapi 等，再点「🚀 启动 AI Chat」。
"""
import os
import sys
import subprocess
import threading
from pathlib import Path

# -------- 项目根目录 --------
PROJECT_ROOT = Path(__file__).resolve().parent
APP_PY = PROJECT_ROOT / "AI_Chat" / "app.py"

# -------- 依赖清单 --------
REQUIREMENTS = [
    ("PyQt5", "PyQt5>=5.15.0"),
    ("QScintilla", "QScintilla>=2.13.0"),
    ("requests", "requests>=2.28.0"),
    ("chardet", "chardet>=5.0.0"),
    ("psutil", "psutil>=5.9.0"),
    ("fastapi", "fastapi>=0.100.0"),
    ("uvicorn", "uvicorn>=0.23.0"),
]


def check_pip():
    """找可用的 pip（python -m pip 优先）"""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            return [sys.executable, "-m", "pip"]
    except Exception:
        pass
    # 回退：直接 pip
    return ["pip"]


def is_installed(pkg_name: str) -> bool:
    """检查某个包是否已安装"""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "show", pkg_name],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


# ============ GUI ============
try:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QTextEdit, QProgressBar, QMessageBox,
        QGroupBox,
    )
    from PyQt5.QtCore import Qt, QThread, pyqtSignal
except ImportError:
    # 连 PyQt5 都没装 — 用 tkinter 做最小安装器
    import tkinter as tk
    from tkinter import scrolledtext, messagebox

    class _TkInstaller:
        def __init__(self):
            self.root = tk.Tk()
            self.root.title("AI Chat 安装器 / 启动器")
            self.root.geometry("600x480")

            tk.Label(self.root, text="AI Chat — 依赖安装 & 启动",
                     font=("Microsoft YaHei", 16, "bold")).pack(pady=10)

            tk.Label(self.root, text=f"Python: {sys.executable}",
                     font=("Consolas", 9), fg="gray").pack()

            btn_frame = tk.Frame(self.root)
            btn_frame.pack(pady=10)

            self.install_btn = tk.Button(
                btn_frame, text="📦 安装依赖 (pip install)",
                command=self._install, width=24, height=2,
                bg="#2d2d30", fg="#00d4ff", activebackground="#3c3c3c",
            )
            self.install_btn.grid(row=0, column=0, padx=8)

            self.launch_btn = tk.Button(
                btn_frame, text="🚀 启动 AI Chat",
                command=self._launch, width=24, height=2,
                bg="#2d2d30", fg="#4CAF50", activebackground="#3c3c3c",
            )
            self.launch_btn.grid(row=0, column=1, padx=8)

            self.status = tk.Label(self.root, text="就绪", fg="gray",
                                   font=("Microsoft YaHei", 10))
            self.status.pack()

            self.log = scrolledtext.ScrolledText(self.root, height=14,
                                                  bg="#1e1e1e", fg="#d4d4d4",
                                                  font=("Consolas", 9))
            self.log.pack(padx=12, pady=8, fill=tk.BOTH, expand=True)

        def _log(self, msg):
            self.log.insert(tk.END, msg + "\n")
            self.log.see(tk.END)
            self.root.update()

        def _install(self):
            self.install_btn.config(state=tk.DISABLED)
            self.status.config(text="正在安装...", fg="#ff9800")
            self._log(f"\n=== 安装依赖 (python: {sys.executable}) ===")

            def worker():
                pip = check_pip()
                ok_count, fail_count = 0, 0
                for name, spec in REQUIREMENTS:
                    self.root.after(0, lambda n=name: self._log(f"\n--- {n} ---"))
                    self.root.after(0, lambda: self.status.config(text=f"安装中: {name}..."))
                    try:
                        r = subprocess.run(
                            pip + ["install", "-U", spec],
                            capture_output=True, text=True, timeout=180,
                        )
                        if r.returncode == 0:
                            self.root.after(0, lambda: self._log("  ✅ 安装成功"))
                            ok_count += 1
                        else:
                            self.root.after(0, lambda o=r: self._log(f"  ⚠️  输出: {o.stdout[-200:]}{o.stderr[-200:]}"))
                            # 再试一次
                            r2 = subprocess.run(
                                pip + ["install", "-U", spec],
                                capture_output=True, text=True, timeout=180,
                            )
                            if r2.returncode == 0:
                                self.root.after(0, lambda: self._log("  ✅ 重试成功"))
                                ok_count += 1
                            else:
                                self.root.after(0, lambda: self._log("  ❌ 安装失败"))
                                fail_count += 1
                    except subprocess.TimeoutExpired:
                        self.root.after(0, lambda: self._log("  ❌ 超时"))
                        fail_count += 1
                    except Exception as e:
                        self.root.after(0, lambda err=str(e): self._log(f"  ❌ {err}"))
                        fail_count += 1
                self.root.after(0, lambda: self.status.config(
                    text=f"完成: ✅{ok_count} ❌{fail_count}", fg="#4CAF50" if fail_count == 0 else "#f44336"))
                self.root.after(0, lambda: self.install_btn.config(state=tk.NORMAL))

            threading.Thread(target=worker, daemon=True).start()

        def _launch(self):
            if not APP_PY.exists():
                messagebox.showerror("错误", f"找不到 {APP_PY}")
                return
            self._log(f"\n🚀 启动 {APP_PY} ...")
            try:
                subprocess.Popen(
                    [sys.executable, "-X", "utf8", str(APP_PY)],
                    cwd=str(PROJECT_ROOT / "AI_Chat"),
                )
                self.status.config(text="已启动 AI Chat", fg="#4CAF50")
            except Exception as e:
                messagebox.showerror("启动失败", str(e))

        def run(self):
            self.root.mainloop()

    if __name__ == "__main__":
        _TkInstaller().run()
    sys.exit(0)


# ============ PyQt5 版本 ============
class InstallWorker(QThread):
    progress = pyqtSignal(str, int, int)   # 当前包名, 已完成, 总数
    log = pyqtSignal(str)
    finished_all = pyqtSignal(int, int)    # ok, fail

    def __init__(self):
        super().__init__()

    def run(self):
        pip = check_pip()
        total = len(REQUIREMENTS)
        ok, fail = 0, 0
        for i, (name, spec) in enumerate(REQUIREMENTS):
            self.progress.emit(name, i, total)
            self.log.emit(f"\n--- {name} ({spec}) ---")
            try:
                r = subprocess.run(
                    pip + ["install", "-U", spec],
                    capture_output=True, text=True, timeout=180,
                )
                if r.returncode == 0:
                    self.log.emit("  ✅ OK")
                    ok += 1
                else:
                    # 重试一次
                    self.log.emit("  ⚠️  第一次失败，重试...")
                    r2 = subprocess.run(
                        pip + ["install", "-U", spec],
                        capture_output=True, text=True, timeout=180,
                    )
                    if r2.returncode == 0:
                        self.log.emit("  ✅ 重试成功")
                        ok += 1
                    else:
                        self.log.emit(f"  ❌ 失败\n  {r2.stderr[-300:]}")
                        fail += 1
            except subprocess.TimeoutExpired:
                self.log.emit("  ❌ 超时 (180s)")
                fail += 1
            except Exception as e:
                self.log.emit(f"  ❌ {e}")
                fail += 1
        self.finished_all.emit(ok, fail)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Chat — 依赖安装 & 启动器")
        self.resize(720, 560)

        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(24, 20, 24, 20)
        main.setSpacing(14)

        # 标题
        title = QLabel("🎮 AI Chat 安装器 / 启动器")
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #00d4ff;")
        main.addWidget(title)

        pyinfo = QLabel(f"🐍 Python: {sys.executable}")
        pyinfo.setStyleSheet("color: #8aa0b0; font-size: 12px;")
        main.addWidget(pyinfo)

        # 按钮行
        btn_row = QHBoxLayout()
        self.install_btn = QPushButton("📦 安装依赖")
        self.install_btn.setFixedHeight(44)
        self.install_btn.setCursor(Qt.PointingHandCursor)
        self.install_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #007acc,stop:1 #00d4ff);
                color: white; border: none; border-radius: 10px;
                font-size: 15px; font-weight: 600;
            }
            QPushButton:hover { opacity: 0.9; }
            QPushButton:disabled { background: #3c3c3c; color: #808080; }
        """)
        self.install_btn.clicked.connect(self._start_install)
        btn_row.addWidget(self.install_btn)

        self.launch_btn = QPushButton("🚀 启动 AI Chat")
        self.launch_btn.setFixedHeight(44)
        self.launch_btn.setCursor(Qt.PointingHandCursor)
        self.launch_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #2e7d32,stop:1 #66bb6a);
                color: white; border: none; border-radius: 10px;
                font-size: 15px; font-weight: 600;
            }
            QPushButton:hover { opacity: 0.9; }
        """)
        self.launch_btn.clicked.connect(self._launch)
        btn_row.addWidget(self.launch_btn)

        main.addLayout(btn_row)

        # 进度条
        self.progress = QProgressBar()
        self.progress.setFixedHeight(22)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setStyleSheet("""
            QProgressBar {
                background: #2d2d30; border: 1px solid #3c3c3c;
                border-radius: 6px; text-align: center; color: #d4d4d4;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #007acc,stop:1 #00d4ff);
                border-radius: 5px;
            }
        """)
        main.addWidget(self.progress)

        # 依赖清单
        dep_group = QGroupBox("📋 依赖清单")
        dep_group.setStyleSheet("""
            QGroupBox { color: #8aa0b0; border: 1px solid #3c3c3c; border-radius: 8px;
                        margin-top: 12px; padding-top: 16px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
        """)
        dep_layout = QVBoxLayout(dep_group)
        self.dep_labels = {}
        for name, spec in REQUIREMENTS:
            lbl = QLabel(f"  ⚪  {name}")
            lbl.setStyleSheet("color: #d4d4d4; font-size: 13px;")
            dep_layout.addWidget(lbl)
            self.dep_labels[name] = lbl
        main.addWidget(dep_group)

        # 日志
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("""
            QTextEdit {
                background: #1e1e1e; color: #d4d4d4; border: 1px solid #3c3c3c;
                border-radius: 8px; font-family: Consolas, monospace; font-size: 12px;
            }
        """)
        main.addWidget(self.log_box, 1)

        self._worker = None
        self._check_installed()

    def _check_installed(self):
        for name, _ in REQUIREMENTS:
            if is_installed(name):
                self.dep_labels[name].setText(f"  ✅  {name}  (已安装)")
                self.dep_labels[name].setStyleSheet("color: #66bb6a; font-size: 13px;")

    def _start_install(self):
        if self._worker and self._worker.isRunning():
            return
        self.install_btn.setEnabled(False)
        self.progress.setValue(0)
        self.log_box.clear()

        self._worker = InstallWorker()
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self._on_log)
        self._worker.finished_all.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, name, i, total):
        pct = int((i / total) * 100)
        self.progress.setValue(pct)
        self.install_btn.setText(f"📦 安装中 ({i}/{total}) - {name}")
        self.dep_labels[name].setText(f"  🔄  {name}  安装中...")
        self.dep_labels[name].setStyleSheet("color: #ff9800; font-size: 13px;")

    def _on_log(self, msg):
        self.log_box.append(msg)

    def _on_finished(self, ok, fail):
        self.progress.setValue(100)
        self.install_btn.setEnabled(True)
        self.install_btn.setText("📦 重新安装")
        if fail == 0:
            self._on_log(f"\n🎉 全部完成！✅ {ok} 个依赖安装成功")
            QMessageBox.information(self, "完成", f"全部 {ok} 个依赖安装成功！")
        else:
            self._on_log(f"\n⚠️  完成: ✅ {ok}  ❌ {fail}")
            QMessageBox.warning(self, "部分失败",
                                f"{ok} 个成功，{fail} 个失败。\n请查看日志后点击重试。")
        self._check_installed()

    def _launch(self):
        if not APP_PY.exists():
            QMessageBox.critical(self, "错误", f"找不到 {APP_PY}")
            return
        try:
            subprocess.Popen(
                [sys.executable, "-X", "utf8", str(APP_PY)],
                cwd=str(PROJECT_ROOT / "AI_Chat"),
            )
            QMessageBox.information(self, "已启动", "AI Chat 已启动！")
        except Exception as e:
            QMessageBox.critical(self, "启动失败", str(e))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # 深色主题
    app.setStyleSheet("""
        QWidget { background: #1e1e1e; color: #d4d4d4; }
        QMainWindow { background: #1a1a2e; }
    """)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
