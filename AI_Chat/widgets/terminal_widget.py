"""
终端组件 - 底部面板
"""
import os
import subprocess
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit, QLabel, QPushButton
)
from PyQt5.QtCore import Qt, QProcess, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor, QColor


class TerminalWidget(QWidget):
    """终端组件"""

    output_received = pyqtSignal(str)

    def __init__(self, cwd: str = None, parent=None):
        super().__init__(parent)
        self.cwd = cwd or os.getcwd()
        self.process = None
        self._init_ui()
        self._start_process()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 输出区域
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet("""
            QTextEdit {
                background: #1e1e1e;
                color: #d4d4d4;
                border: none;
                padding: 8px;
                font-family: Consolas, monospace;
                font-size: 12px;
            }
        """)
        self.output.setFont(QFont("Consolas", 10))
        layout.addWidget(self.output, 1)

        # 输入行
        input_row = QWidget()
        input_row.setStyleSheet("background: #1e1e1e; border-top: 1px solid #333;")
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(8, 6, 8, 6)
        input_layout.setSpacing(8)

        prompt = QLabel("$")
        prompt.setStyleSheet("color: #4ec9b0; font-family: Consolas, monospace; font-size: 12px;")
        input_layout.addWidget(prompt)

        self.input_edit = QLineEdit()
        self.input_edit.setStyleSheet("""
            QLineEdit {
                background: transparent;
                color: #d4d4d4;
                border: none;
                font-family: Consolas, monospace;
                font-size: 12px;
                padding: 2px 0;
            }
            QLineEdit:focus { outline: none; }
        """)
        self.input_edit.setFont(QFont("Consolas", 10))
        self.input_edit.returnPressed.connect(self.execute_command)
        input_layout.addWidget(self.input_edit, 1)

        layout.addWidget(input_row)

        self.command_history = []
        self.history_index = -1

    def _start_process(self):
        """启动 PowerShell 进程"""
        self.process = QProcess(self)
        self.process.setProgram("powershell.exe")
        self.process.setArguments(["-NoLogo", "-NoProfile"])
        self.process.setWorkingDirectory(self.cwd)

        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)

        self.process.start()
        self.process.waitForStarted(2000)

        # 发送一个空命令来获取提示符
        QTimer.singleShot(300, lambda: self._write_input(""))

    def _on_stdout(self):
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._append_output(data)

    def _on_stderr(self):
        data = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        self._append_output(data, is_error=True)

    def _on_finished(self):
        self._append_output("\n[进程已结束]\n")

    def _append_output(self, text: str, is_error: bool = False):
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.End)

        if is_error:
            fmt = cursor.charFormat()
            fmt.setForeground(QColor("#f48771"))
            cursor.setCharFormat(fmt)
        else:
            fmt = cursor.charFormat()
            fmt.setForeground(QColor("#d4d4d4"))
            cursor.setCharFormat(fmt)

        cursor.insertText(text)
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()
        self.output_received.emit(text)

    def _write_input(self, text: str):
        if self.process and self.process.state() == QProcess.Running:
            self.process.write((text + "\n").encode("utf-8"))

    def execute_command(self):
        command = self.input_edit.text()
        if not command.strip():
            return

        self.command_history.append(command)
        self.history_index = len(self.command_history)

        self._append_output(f"> {command}\n")
        self._write_input(command)
        self.input_edit.clear()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Up and self.input_edit.hasFocus():
            if self.history_index > 0:
                self.history_index -= 1
                self.input_edit.setText(self.command_history[self.history_index])
            return
        elif event.key() == Qt.Key_Down and self.input_edit.hasFocus():
            if self.history_index < len(self.command_history) - 1:
                self.history_index += 1
                self.input_edit.setText(self.command_history[self.history_index])
            else:
                self.history_index = len(self.command_history)
                self.input_edit.clear()
            return
        super().keyPressEvent(event)

    def set_cwd(self, path: str):
        """设置工作目录"""
        self.cwd = path
        if self.process and self.process.state() == QProcess.Running:
            self._write_input(f"cd '{path}'")

    def clear(self):
        self.output.clear()

    def close(self):
        if self.process:
            self.process.kill()
            self.process.waitForFinished(1000)
