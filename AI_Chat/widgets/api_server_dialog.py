"""
对外提供 AI 对话框 - 把本程序的 AI 以 OpenAI Chat Completions 格式提供给外部程序接入。
字段与外部程序的「自定义模型」表单一一对应：请求地址 / 完整URL / 模型ID / API密钥 / 连通性测试。
"""
import secrets

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QSpinBox, QCheckBox, QMessageBox, QApplication, QFrame,
)

from core.config import get_config_manager
from core.api_server import get_api_server, get_local_ip


class _ConnTestWorker(QThread):
    """连通性测试线程：向本程序对外接口发起一次真实请求"""
    finished_test = pyqtSignal(bool, str)

    def __init__(self, url: str, api_key: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.api_key = api_key

    def run(self):
        import requests
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            r = requests.post(
                self.url,
                json={"messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                headers=headers,
                timeout=(5, 60),
            )
            if r.status_code == 200:
                self.finished_test.emit(True, "连接成功，外部程序可以正常使用本程序的 AI")
            else:
                self.finished_test.emit(False, f"HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            self.finished_test.emit(False, str(e))


class ApiServerDialog(QDialog):
    """对外开放 AI（OpenAI Chat Completions 兼容）"""

    def __init__(self, parent=None, server_manager=None):
        super().__init__(parent)
        self.server_manager = server_manager
        self.api = get_api_server()
        self._test_thread = None

        cfg = get_config_manager()
        self.port = int(cfg.get("api_server.port", 8900) or 8900)
        self.api_key = str(cfg.get("api_server.api_key", "") or "")
        self.require_key = bool(cfg.get("api_server.require_key", True))
        if not self.api_key:
            self.api_key = secrets.token_hex(16)
            cfg.set("api_server.api_key", self.api_key)

        self.setWindowTitle("对外开放 AI（自定义模型）")
        self.setMinimumWidth(520)
        self._init_ui()
        self._refresh_address()
        self._refresh_model_id()
        self._update_status()

    # ---------------- UI ----------------

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 16, 20, 16)

        self.setStyleSheet("""
            QDialog { background: #1e1e1e; }
            QLabel { color: #cccccc; font-size: 12px; }
            QLineEdit, QComboBox, QSpinBox {
                background: #2d2d30; color: #cccccc;
                border: 1px solid #3c3c3c; border-radius: 6px;
                padding: 6px 10px; font-size: 12px;
            }
            QLineEdit:focus, QSpinBox:focus { border-color: #007acc; }
            QCheckBox { color: #cccccc; font-size: 12px; }
            QPushButton { font-size: 12px; border-radius: 6px; padding: 6px 14px;
                          background: #2d2d30; color: #cccccc; border: 1px solid #3c3c3c; }
            QPushButton:hover { border-color: #007acc; }
            QPushButton:disabled { color: #606060; border-color: #2a2a2a; }
        """)

        # 标题
        title = QLabel("把本程序的 AI 提供给外部程序使用")
        title.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: 600;")
        layout.addWidget(title)

        # API 格式（固定）
        layout.addWidget(self._label("*API 格式"))
        fmt = QComboBox()
        fmt.addItems(["OpenAI Chat Completions 格式"])
        fmt.setEnabled(False)
        layout.addWidget(fmt)

        # 服务地址 + 完整URL 开关 + 端口
        addr_row = QHBoxLayout()
        addr_row.addWidget(self._label("*本程序服务地址"))
        addr_row.addStretch()
        self.full_url_cb = QCheckBox("完整 URL")
        self.full_url_cb.toggled.connect(self._refresh_address)
        addr_row.addWidget(self.full_url_cb)
        addr_row.addWidget(QLabel("端口"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(self.port)
        self.port_spin.setFixedWidth(90)
        self.port_spin.valueChanged.connect(self._on_port_changed)
        addr_row.addWidget(self.port_spin)
        layout.addLayout(addr_row)

        hint = QLabel("把此地址填入外部程序的「自定义请求地址」。不勾选完整URL时，"
                      "外部程序会在地址末尾自动补充 /chat/completions。")
        hint.setStyleSheet("color: #6a6a6a; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        addr_row2 = QHBoxLayout()
        self.addr_edit = QLineEdit()
        self.addr_edit.setReadOnly(True)
        self.addr_edit.setStyleSheet("color: #9cdcfe;")
        addr_row2.addWidget(self.addr_edit)
        addr_row2.addWidget(self._copy_btn(lambda: self.addr_edit.text()))
        layout.addLayout(addr_row2)

        self.local_hint = QLabel("")
        self.local_hint.setStyleSheet("color: #6a6a6a; font-size: 11px;")
        layout.addWidget(self.local_hint)

        # 模型 ID
        mid_row = QHBoxLayout()
        mid_row.addWidget(self._label("*模型 ID"))
        mid_row.addStretch()
        refresh_btn = QPushButton("↻ 获取")
        refresh_btn.setFixedHeight(26)
        refresh_btn.clicked.connect(self._refresh_model_id)
        mid_row.addWidget(refresh_btn)
        layout.addLayout(mid_row)

        mid_row2 = QHBoxLayout()
        self.model_edit = QLineEdit()
        self.model_edit.setReadOnly(True)
        self.model_edit.setStyleSheet("color: #9cdcfe;")
        mid_row2.addWidget(self.model_edit)
        mid_row2.addWidget(self._copy_btn(lambda: self.model_edit.text()))
        layout.addLayout(mid_row2)

        # API 密钥
        key_row = QHBoxLayout()
        key_row.addWidget(self._label("*API 密钥"))
        key_row.addStretch()
        self.require_key_cb = QCheckBox("要求密钥")
        self.require_key_cb.setChecked(self.require_key)
        self.require_key_cb.toggled.connect(self._on_require_key_changed)
        key_row.addWidget(self.require_key_cb)
        reset_btn = QPushButton("重置")
        reset_btn.setFixedHeight(26)
        reset_btn.clicked.connect(self._reset_key)
        key_row.addWidget(reset_btn)
        layout.addLayout(key_row)

        key_row2 = QHBoxLayout()
        self.key_edit = QLineEdit(self.api_key)
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.textChanged.connect(self._on_key_edited)
        key_row2.addWidget(self.key_edit)
        self.eye_btn = QPushButton("👁")
        self.eye_btn.setFixedWidth(40)
        self.eye_btn.setCheckable(True)
        self.eye_btn.toggled.connect(self._toggle_echo)
        key_row2.addWidget(self.eye_btn)
        key_row2.addWidget(self._copy_btn(lambda: self.key_edit.text()))
        layout.addLayout(key_row2)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #333333;")
        layout.addWidget(line)

        # 状态 + 启动/停止
        st_row = QHBoxLayout()
        self.status_label = QLabel("● 服务未启动")
        self.status_label.setStyleSheet("color: #f48771; font-size: 12px;")
        st_row.addWidget(self.status_label)
        st_row.addStretch()
        self.toggle_btn = QPushButton("🚀 启动服务")
        self.toggle_btn.setStyleSheet("""
            QPushButton { background: #007acc; color: white; border: none;
                          border-radius: 6px; padding: 7px 18px; font-weight: 600; }
            QPushButton:hover { background: #1177bb; }
        """)
        self.toggle_btn.clicked.connect(self._toggle_server)
        st_row.addWidget(self.toggle_btn)
        layout.addLayout(st_row)

        # 说明 + 测试
        info = QLabel("ℹ 连通性测试会发起一次真实请求，会消耗少量模型Token；"
                      "外部调用前请先在本程序启动模型服务。")
        info.setStyleSheet("color: #6a6a6a; font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_row = QHBoxLayout()
        test_btn = QPushButton("🔗 测试连接")
        test_btn.clicked.connect(self._run_conn_test)
        btn_row.addWidget(test_btn)
        copy_all_btn = QPushButton("📋 复制接入信息")
        copy_all_btn.clicked.connect(self._copy_all)
        btn_row.addWidget(copy_all_btn)
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 600;")
        return lbl

    def _copy_btn(self, getter) -> QPushButton:
        btn = QPushButton("复制")
        btn.setFixedHeight(26)
        btn.clicked.connect(lambda: self._copy(getter()))
        return btn

    def _copy(self, text: str):
        if text:
            QApplication.clipboard().setText(text)

    # ---------------- 行为 ----------------

    def _refresh_address(self):
        ip = get_local_ip()
        if self.full_url_cb.isChecked():
            self.addr_edit.setText(f"http://{ip}:{self.port_spin.value()}/v1/chat/completions")
        else:
            self.addr_edit.setText(f"http://{ip}:{self.port_spin.value()}/v1")
        self.local_hint.setText(f"本机访问: http://127.0.0.1:{self.port_spin.value()}/v1"
                                f"    ·    局域网设备使用上面显示的 {ip} 地址")

    def _on_port_changed(self):
        self.port = self.port_spin.value()
        get_config_manager().set("api_server.port", self.port)
        self._refresh_address()

    def _refresh_model_id(self):
        """模型 ID：优先取 llama-server 已加载的模型，回退配置里的当前模型名"""
        model_id = ""
        try:
            import requests
            from core.config import get_config_manager as _gc
            cfg = _gc()
            llm = cfg.get("llm", {}) or {}
            base = f"http://{llm.get('host', '127.0.0.1')}:{llm.get('port', 8080)}"
            r = requests.get(f"{base}/v1/models", timeout=3)
            if r.status_code == 200:
                data = r.json().get("data", [])
                if data:
                    model_id = data[0].get("id", "")
        except Exception:
            pass
        if not model_id:
            try:
                cur = get_config_manager().get_current_model() or {}
                model_id = cur.get("name") or cur.get("id") or ""
            except Exception:
                model_id = ""
        self.model_edit.setText(model_id or "（未获取到，请先启动本地模型）")

    def _on_require_key_changed(self, checked: bool):
        self.require_key = bool(checked)
        get_config_manager().set("api_server.require_key", self.require_key)
        # 运行中即时生效
        if self.api.is_running:
            self.api.require_key = self.require_key
        self._update_status()

    def _on_key_edited(self, text: str):
        self.api_key = text.strip()
        get_config_manager().set("api_server.api_key", self.api_key)
        if self.api.is_running:
            self.api.api_key = self.api_key

    def _reset_key(self):
        self.key_edit.setText(secrets.token_hex(16))

    def _toggle_echo(self, checked: bool):
        self.key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    def _toggle_server(self):
        if self.api.is_running:
            self.api.stop()
            self._update_status()
            return
        ok, err = self.api.start(
            port=self.port_spin.value(),
            api_key=self.api_key,
            require_key=self.require_key_cb.isChecked(),
            llm_base_url=self._llm_base_url(),
        )
        if not ok:
            QMessageBox.warning(self, "启动失败", err or "启动失败")
        self._update_status()

    def _llm_base_url(self) -> str:
        llm = get_config_manager().get("llm", {}) or {}
        return f"http://{llm.get('host', '127.0.0.1')}:{llm.get('port', 8080)}"

    def _update_status(self):
        if self.api.is_running:
            self.status_label.setText(
                f"● 运行中  {self.api.get_base_url(lan=False)}  （密钥{'启用' if self.api.require_key and self.api.api_key else '未启用'}）")
            self.status_label.setStyleSheet("color: #4ec9b0; font-size: 12px;")
            self.toggle_btn.setText("⏹ 停止服务")
        else:
            self.status_label.setText("● 服务未启动")
            self.status_label.setStyleSheet("color: #f48771; font-size: 12px;")
            self.toggle_btn.setText("🚀 启动服务")
        # 本地模型状态提示
        running = bool(self.server_manager and self.server_manager.status == "running")
        if running:
            self.local_hint.setText(self.local_hint.text())
        else:
            tip = "（提示：本地模型未启动，外部调用前请先在本程序启动模型）"
            if tip not in self.local_hint.text():
                self.local_hint.setText(self.local_hint.text() + "  " + tip)

    def _run_conn_test(self):
        if not self.api.is_running:
            QMessageBox.information(self, "提示", "请先点击「启动服务」后再测试连接。")
            return
        if self._test_thread is not None and self._test_thread.isRunning():
            return
        url = f"http://127.0.0.1:{self.port_spin.value()}/v1/chat/completions"
        key = self.api_key if self.require_key_cb.isChecked() else ""
        self._test_thread = _ConnTestWorker(url, key, self)
        self._test_thread.finished_test.connect(self._on_conn_test_done)
        self._test_thread.start()

    def _on_conn_test_done(self, ok: bool, msg: str):
        if ok:
            QMessageBox.information(self, "连通性测试", msg)
        else:
            QMessageBox.warning(self, "连通性测试失败",
                                f"测试失败：\n{msg}\n\n请确认本地模型服务已启动、密钥正确。")

    def _copy_all(self):
        """复制完整接入信息，方便直接粘贴进外部程序的「自定义模型」表单"""
        base = f"http://{get_local_ip()}:{self.port_spin.value()}/v1"
        full = base + "/chat/completions"
        key = self.key_edit.text() if self.require_key_cb.isChecked() else "（未启用密钥校验）"
        text = (
            "【本程序 AI 对外接入信息（OpenAI Chat Completions 格式）】\n"
            f"API 格式: OpenAI Chat Completions 格式\n"
            f"自定义请求地址: {base}\n"
            f"完整 URL: {full}\n"
            f"模型 ID: {self.model_edit.text()}\n"
            f"API 密钥: {key}\n"
            f"本机地址: http://127.0.0.1:{self.port_spin.value()}/v1\n"
        )
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "已复制",
                                "接入信息已复制到剪贴板，可直接粘贴到外部程序的对应输入框。")

    def closeEvent(self, event):
        # 关闭对话框不停止服务，保持对外提供
        event.accept()
