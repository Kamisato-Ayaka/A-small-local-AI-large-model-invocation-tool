"""
Web 服务对话框 - 显示二维码、控制 Web 服务器
支持 WiFi 局域网访问和 ngrok 外网远程访问
"""
import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QMessageBox, QWidget, QTabWidget,
    QFormLayout, QCheckBox
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap, QFont, QIcon

from web.web_server import WebServer
from core.config import get_config_manager


class WebServerDialog(QDialog):
    """Web 服务设置对话框"""

    def __init__(self, charter_dir: str = None, llm_base_url: str = None,
                 server_manager=None, system_monitor=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📱 移动端访问")
        self.setFixedSize(460, 600)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self.charter_dir = charter_dir
        self.llm_base_url = llm_base_url
        self.web_server = WebServer(
            charter_dir=charter_dir,
            llm_base_url=llm_base_url,
            server_manager=server_manager,
            system_monitor=system_monitor
        )
        self.cfg = get_config_manager()

        self._init_ui()
        self._load_saved_config()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 标题
        title = QLabel("📱 移动端访问")
        title.setStyleSheet("""
            font-size: 20px;
            font-weight: 700;
            color: #e6edf3;
            font-family: "Microsoft YaHei";
        """)
        layout.addWidget(title)

        # 标签页
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #333;
                border-radius: 8px;
                background: #1e1e1e;
                top: -1px;
            }
            QTabBar::tab {
                background: #252526;
                color: #888;
                padding: 8px 16px;
                border: 1px solid #333;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 13px;
                font-family: "Microsoft YaHei";
            }
            QTabBar::tab:selected {
                background: #1e1e1e;
                color: #e6edf3;
            }
        """)

        # WiFi 标签页
        self.wifi_tab = QWidget()
        self._init_wifi_tab()
        self.tabs.addTab(self.wifi_tab, "📶 WiFi 局域网")

        # 远程访问标签页
        self.remote_tab = QWidget()
        self._init_remote_tab()
        self.tabs.addTab(self.remote_tab, "🌐 远程访问")

        layout.addWidget(self.tabs, 1)

        # 底部启动/停止按钮
        self.toggle_btn = QPushButton("🚀 启动 Web 服务")
        self.toggle_btn.setFixedHeight(44)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle_server)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                background: #0e639c;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 15px;
                font-weight: 600;
                font-family: "Microsoft YaHei";
            }
            QPushButton:hover {
                background: #1177bb;
            }
            QPushButton:disabled {
                background: #333;
                color: #666;
            }
        """)
        layout.addWidget(self.toggle_btn)

        # 状态
        self.status_label = QLabel("● 服务未启动")
        self.status_label.setStyleSheet("""
            color: #888;
            font-size: 12px;
            font-family: "Microsoft YaHei";
        """)
        layout.addWidget(self.status_label)

    def _init_wifi_tab(self):
        """WiFi 局域网标签页"""
        layout = QVBoxLayout(self.wifi_tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # 说明
        desc = QLabel("手机和电脑连接同一个 WiFi，扫描二维码即可使用。")
        desc.setWordWrap(True)
        desc.setStyleSheet("""
            color: #888;
            font-size: 13px;
            line-height: 1.6;
            font-family: "Microsoft YaHei";
        """)
        layout.addWidget(desc)

        # 端口设置
        port_row = QHBoxLayout()
        port_label = QLabel("端口:")
        port_label.setStyleSheet("color: #ccc; font-size: 13px; min-width: 60px;")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(8765)
        self.port_spin.setStyleSheet("""
            QSpinBox {
                background: #252526;
                border: 1px solid #333;
                color: #e6edf3;
                padding: 6px 10px;
                border-radius: 6px;
                font-size: 13px;
            }
        """)
        port_row.addWidget(port_label)
        port_row.addWidget(self.port_spin)
        port_row.addStretch()
        layout.addLayout(port_row)

        # 二维码区域
        qr_container = QWidget()
        qr_container.setFixedHeight(200)
        qr_container.setStyleSheet("""
            background: #252526;
            border: 1px solid #333;
            border-radius: 10px;
        """)
        qr_layout = QVBoxLayout(qr_container)
        qr_layout.setAlignment(Qt.AlignCenter)

        self.qr_label = QLabel("启动服务后显示二维码")
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setFixedSize(180, 180)
        self.qr_label.setStyleSheet("""
            color: #666;
            font-size: 13px;
            font-family: "Microsoft YaHei";
        """)
        qr_layout.addWidget(self.qr_label)
        layout.addWidget(qr_container)

        # URL 显示
        url_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setReadOnly(True)
        self.url_input.setPlaceholderText("服务未启动")
        self.url_input.setStyleSheet("""
            QLineEdit {
                background: #252526;
                border: 1px solid #333;
                color: #4caf50;
                padding: 8px 12px;
                border-radius: 6px;
                font-size: 12px;
                font-family: Consolas, monospace;
            }
        """)
        url_row.addWidget(self.url_input, 1)

        self.copy_btn = QPushButton("复制")
        self.copy_btn.setFixedSize(60, 32)
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(lambda: self._copy_url(self.url_input, self.copy_btn))
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background: #37373d;
                color: #e6edf3;
                border: none;
                border-radius: 6px;
                font-size: 12px;
                font-family: "Microsoft YaHei";
            }
            QPushButton:hover {
                background: #454550;
            }
        """)
        url_row.addWidget(self.copy_btn)
        layout.addLayout(url_row)

        layout.addStretch()

    def _init_remote_tab(self):
        """远程访问标签页"""
        layout = QVBoxLayout(self.remote_tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # 说明
        desc = QLabel("通过 ngrok 外网穿透，手机在任何网络下都能访问（需要 ngrok 账号）。")
        desc.setWordWrap(True)
        desc.setStyleSheet("""
            color: #888;
            font-size: 13px;
            line-height: 1.6;
            font-family: "Microsoft YaHei";
        """)
        layout.addWidget(desc)

        # ngrok Auth Token
        token_label = QLabel("ngrok Auth Token:")
        token_label.setStyleSheet("color: #ccc; font-size: 13px;")
        layout.addWidget(token_label)

        self.ngrok_token_input = QLineEdit()
        self.ngrok_token_input.setPlaceholderText("输入你的 ngrok authtoken")
        self.ngrok_token_input.setEchoMode(QLineEdit.Password)
        self.ngrok_token_input.setStyleSheet("""
            QLineEdit {
                background: #252526;
                border: 1px solid #333;
                color: #e6edf3;
                padding: 8px 12px;
                border-radius: 6px;
                font-size: 13px;
                font-family: Consolas, monospace;
            }
            QLineEdit:focus {
                border-color: #0e639c;
            }
        """)
        layout.addWidget(self.ngrok_token_input)

        # 提示
        tip = QLabel('<a href="https://dashboard.ngrok.com/get-started/your-authtoken" style="color: #0e639c;">获取 ngrok Auth Token →</a>')
        tip.setOpenExternalLinks(True)
        tip.setStyleSheet("font-size: 12px;")
        layout.addWidget(tip)

        layout.addSpacing(8)

        # 启动隧道按钮
        self.ngrok_btn = QPushButton("🔗 启动远程访问")
        self.ngrok_btn.setFixedHeight(38)
        self.ngrok_btn.setCursor(Qt.PointingHandCursor)
        self.ngrok_btn.setEnabled(False)
        self.ngrok_btn.clicked.connect(self._toggle_ngrok)
        self.ngrok_btn.setStyleSheet("""
            QPushButton {
                background: #6a1b9a;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: 600;
                font-family: "Microsoft YaHei";
            }
            QPushButton:hover {
                background: #7b1fa2;
            }
            QPushButton:disabled {
                background: #333;
                color: #666;
            }
        """)
        layout.addWidget(self.ngrok_btn)

        layout.addSpacing(8)

        # 远程二维码区域
        remote_qr_container = QWidget()
        remote_qr_container.setFixedHeight(200)
        remote_qr_container.setStyleSheet("""
            background: #252526;
            border: 1px solid #333;
            border-radius: 10px;
        """)
        remote_qr_layout = QVBoxLayout(remote_qr_container)
        remote_qr_layout.setAlignment(Qt.AlignCenter)

        self.remote_qr_label = QLabel("启动远程访问后显示")
        self.remote_qr_label.setAlignment(Qt.AlignCenter)
        self.remote_qr_label.setFixedSize(180, 180)
        self.remote_qr_label.setStyleSheet("""
            color: #666;
            font-size: 13px;
            font-family: "Microsoft YaHei";
        """)
        remote_qr_layout.addWidget(self.remote_qr_label)
        layout.addWidget(remote_qr_container)

        # 远程 URL 显示
        remote_url_row = QHBoxLayout()
        self.remote_url_input = QLineEdit()
        self.remote_url_input.setReadOnly(True)
        self.remote_url_input.setPlaceholderText("未启动远程访问")
        self.remote_url_input.setStyleSheet("""
            QLineEdit {
                background: #252526;
                border: 1px solid #333;
                color: #9c27b0;
                padding: 8px 12px;
                border-radius: 6px;
                font-size: 11px;
                font-family: Consolas, monospace;
            }
        """)
        remote_url_row.addWidget(self.remote_url_input, 1)

        self.remote_copy_btn = QPushButton("复制")
        self.remote_copy_btn.setFixedSize(60, 32)
        self.remote_copy_btn.setCursor(Qt.PointingHandCursor)
        self.remote_copy_btn.clicked.connect(lambda: self._copy_url(self.remote_url_input, self.remote_copy_btn))
        self.remote_copy_btn.setStyleSheet("""
            QPushButton {
                background: #37373d;
                color: #e6edf3;
                border: none;
                border-radius: 6px;
                font-size: 12px;
                font-family: "Microsoft YaHei";
            }
            QPushButton:hover {
                background: #454550;
            }
        """)
        remote_url_row.addWidget(self.remote_copy_btn)
        layout.addLayout(remote_url_row)

        layout.addStretch()

        # 保存 token 勾选
        self.save_token_check = QCheckBox("记住 Auth Token")
        self.save_token_check.setChecked(True)
        self.save_token_check.setStyleSheet("""
            QCheckBox {
                color: #888;
                font-size: 12px;
                font-family: "Microsoft YaHei";
            }
        """)
        layout.addWidget(self.save_token_check)

    def _load_saved_config(self):
        """加载保存的配置"""
        try:
            port = self.cfg.get("web_port", 8765)
            self.port_spin.setValue(port)
        except Exception:
            pass

        try:
            token = self.cfg.get("ngrok_token", "")
            if token:
                self.ngrok_token_input.setText(token)
        except Exception:
            pass

    def _save_config(self):
        """保存配置"""
        try:
            self.cfg.set("web_port", self.port_spin.value())
            if self.save_token_check.isChecked():
                self.cfg.set("ngrok_token", self.ngrok_token_input.text())
            self.cfg.save()
        except Exception:
            pass

    def _toggle_server(self):
        """启动/停止服务"""
        if self.web_server.is_running:
            self._stop_server()
        else:
            self._start_server()

    def _start_server(self):
        """启动服务"""
        try:
            port = self.port_spin.value()
            self.web_server.start(port=port)

            self.toggle_btn.setText("⏳ 启动中...")
            self.toggle_btn.setEnabled(False)
            self.status_label.setText("● 正在启动...")
            self.status_label.setStyleSheet("color: #ff9800; font-size: 12px;")

            self._save_config()

            # 轮询检测服务是否真正启动成功
            self._start_check_count = 0
            self._check_server_started()
        except Exception as e:
            QMessageBox.critical(self, "启动失败", str(e))

    def _check_server_started(self):
        """轮询检查服务是否启动成功"""
        self._start_check_count += 1

        # 尝试访问服务，检测是否可用
        import urllib.request
        try:
            url = f"http://127.0.0.1:{self.port_spin.value()}/api/status"
            req = urllib.request.Request(url)
            resp = urllib.request.urlopen(req, timeout=1)
            if resp.status == 200:
                # 服务启动成功
                self._on_server_started()
                return
        except Exception:
            pass

        # 最多等 10 秒（20 次 * 0.5 秒）
        if self._start_check_count > 20:
            self._on_server_start_failed("服务启动超时，请检查端口是否被占用")
            return

        # 继续等待
        QTimer.singleShot(500, self._check_server_started)

    def _on_server_start_failed(self, msg: str):
        """服务启动失败"""
        self.toggle_btn.setText("🚀 启动 Web 服务")
        self.toggle_btn.setEnabled(True)
        self.status_label.setText(f"● 启动失败: {msg}")
        self.status_label.setStyleSheet("color: #f44336; font-size: 12px;")
        QMessageBox.warning(self, "启动失败", msg)

    def _on_server_started(self):
        """服务启动完成"""
        # WiFi URL
        url = self.web_server.get_url()
        self.url_input.setText(url)

        # 生成 WiFi 二维码
        qr_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "web", "static", "qr_current.png"
        ))
        os.makedirs(os.path.dirname(qr_path), exist_ok=True)
        saved_path = self.web_server.generate_qr_code(qr_path)

        if saved_path and os.path.exists(saved_path):
            pixmap = QPixmap(saved_path)
            self.qr_label.setPixmap(pixmap.scaled(180, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.qr_label.setText("")
        else:
            self.qr_label.setText("二维码生成失败")

        self.toggle_btn.setText("⏹ 停止服务")
        self.toggle_btn.setEnabled(True)
        self.ngrok_btn.setEnabled(True)
        self.status_label.setText("● 服务运行中")
        self.status_label.setStyleSheet("color: #4caf50; font-size: 12px;")

    def _stop_server(self):
        """停止服务"""
        # 先停止 ngrok
        self._stop_ngrok()

        self.web_server.stop()
        self.toggle_btn.setText("🚀 启动 Web 服务")
        self.ngrok_btn.setEnabled(False)

        # 清空 WiFi
        self.url_input.clear()
        self.url_input.setPlaceholderText("服务未启动")
        self.qr_label.clear()
        self.qr_label.setText("启动服务后显示二维码")
        self.qr_label.setStyleSheet("""
            color: #666;
            font-size: 13px;
            font-family: "Microsoft YaHei";
        """)

        self.status_label.setText("● 服务未启动")
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")

    def _toggle_ngrok(self):
        """启动/停止 ngrok 隧道"""
        if self.web_server.get_ngrok_url():
            self._stop_ngrok()
        else:
            self._start_ngrok()

    def _start_ngrok(self):
        """启动 ngrok 隧道"""
        token = self.ngrok_token_input.text().strip()
        if not token:
            QMessageBox.warning(self, "提示", "请先输入 ngrok Auth Token")
            return

        self.ngrok_btn.setText("⏳ 连接中...")
        self.ngrok_btn.setEnabled(False)
        self._save_config()

        # 在线程中启动（避免阻塞 UI）
        import threading
        threading.Thread(target=self._ngrok_start_thread, args=(token,), daemon=True).start()

    def _ngrok_start_thread(self, token: str):
        """ngrok 启动线程"""
        try:
            url = self.web_server.start_ngrok_tunnel(auth_token=token)
            # 回到主线程更新 UI
            QTimer.singleShot(0, lambda: self._on_ngrok_started(url))
        except Exception as e:
            QTimer.singleShot(0, lambda: self._on_ngrok_error(str(e)))

    def _on_ngrok_started(self, url: str):
        """ngrok 启动成功"""
        self.remote_url_input.setText(url)

        # 生成二维码
        qr_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "web", "static", "qr_ngrok_current.png"
        ))
        os.makedirs(os.path.dirname(qr_path), exist_ok=True)
        saved_path = self.web_server.generate_ngrok_qr_code(qr_path)

        if saved_path and os.path.exists(saved_path):
            pixmap = QPixmap(saved_path)
            self.remote_qr_label.setPixmap(pixmap.scaled(180, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.remote_qr_label.setText("")
        else:
            self.remote_qr_label.setText("二维码生成失败")

        self.ngrok_btn.setText("⏹ 停止远程访问")
        self.ngrok_btn.setEnabled(True)

    def _on_ngrok_error(self, error: str):
        """ngrok 启动失败"""
        QMessageBox.critical(self, "远程访问启动失败", error)
        self.ngrok_btn.setText("🔗 启动远程访问")
        self.ngrok_btn.setEnabled(True)

    def _stop_ngrok(self):
        """停止 ngrok 隧道"""
        self.web_server.stop_ngrok_tunnel()
        self.ngrok_btn.setText("🔗 启动远程访问")

        # 清空远程
        self.remote_url_input.clear()
        self.remote_url_input.setPlaceholderText("未启动远程访问")
        self.remote_qr_label.clear()
        self.remote_qr_label.setText("启动远程访问后显示")
        self.remote_qr_label.setStyleSheet("""
            color: #666;
            font-size: 13px;
            font-family: "Microsoft YaHei";
        """)

    def _copy_url(self, line_edit, btn):
        """复制 URL"""
        url = line_edit.text()
        if url:
            from PyQt5.QtWidgets import QApplication
            QApplication.clipboard().setText(url)
            btn.setText("已复制!")
            QTimer.singleShot(1500, lambda: btn.setText("复制"))

    def closeEvent(self, event):
        """关闭时不停止服务，只隐藏窗口"""
        self._save_config()
        event.accept()

    def is_server_running(self) -> bool:
        return self.web_server.is_running
