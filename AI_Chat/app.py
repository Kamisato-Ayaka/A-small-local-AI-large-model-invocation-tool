"""
A Small Local AI Runner - 本地 AI 代码开发助手
启动入口（含全局异常处理）
"""
import os
import sys
import traceback

# 添加当前目录到路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def show_error_dialog(title: str, message: str, detail: str = None):
    """显示错误对话框（兜底：优先 PyQt，失败则用 tkinter，再失败则打印）"""
    try:
        from PyQt5.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle(title)
        msg.setText(message)
        if detail:
            msg.setDetailedText(detail)
        msg.exec_()
    except ImportError:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            full_msg = message
            if detail:
                full_msg += f"\n\n详细信息:\n{detail}"
            messagebox.showerror(title, full_msg)
            root.destroy()
        except Exception:
            print(f"[{title}] {message}", file=sys.stderr)
            if detail:
                print(detail, file=sys.stderr)


def main():
    try:
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        from main import MainWindow
    except ImportError as e:
        show_error_dialog(
            "依赖缺失",
            "无法加载 PyQt5。\n\n请先安装依赖：\n  pip install PyQt5 requests\n\n或者运行 launcher.py 自动安装。",
            str(e)
        )
        sys.exit(1)
    except Exception as e:
        show_error_dialog(
            "启动错误",
            f"导入模块失败: {str(e)}",
            traceback.format_exc()
        )
        sys.exit(1)

    try:
        # 工作区目录
        workspace = os.path.join(BASE_DIR, "workspace")
        if not os.path.exists(workspace):
            os.makedirs(workspace)

        # LLM 服务器地址
        llm_url = os.environ.get("LLM_SERVER_URL", "http://127.0.0.1:8080")

        app = QApplication(sys.argv)
        app.setApplicationName("A Small Local AI Runner")
        app.setOrganizationName("A Small Local AI Runner")

        # 设置全局字体
        font = QFont("Microsoft YaHei", 10)
        app.setFont(font)

        # 全局异常捕获
        def global_exception_handler(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return

            tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))

            try:
                from PyQt5.QtWidgets import QMessageBox
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Critical)
                msg.setWindowTitle("程序错误")
                msg.setText("程序运行时发生错误。")
                msg.setInformativeText(str(exc_value))
                msg.setDetailedText(tb_str)
                msg.exec_()
            except Exception:
                print("未捕获的异常:", file=sys.stderr)
                print(tb_str, file=sys.stderr)

        sys.excepthook = global_exception_handler

        # 创建主窗口
        window = MainWindow(workspace_path=workspace, llm_url=llm_url)
        window.show()

        sys.exit(app.exec_())

    except Exception as e:
        tb_str = traceback.format_exc()
        show_error_dialog(
            "启动失败",
            f"A Small Local AI Runner 启动失败：\n{str(e)}",
            tb_str
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
