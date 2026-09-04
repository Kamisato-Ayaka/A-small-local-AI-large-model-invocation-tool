"""
角色创建向导（游戏世界模式）：
  1. 指定 角色基础模板 txt（角色名 = 模板文件名）
  2. 指定 玩家模板 txt（仅玩家背景）
  3. 指定生成对话世界的模型 → 点击「生成对话世界」启动模型并生成世界
     → 保存为 角色文件夹/游戏背景_编号.txt
  4. 点击「创建角色」→ 创建对话文件夹 角色名_编号/
     （内含 游戏背景.txt 副本 + 空 对话历史.txt）
"""
import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QFileDialog, QMessageBox, QComboBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QPixmap, QIcon, QFont


class _WorldGenWorker(QObject):
    """后台流式生成游戏世界"""
    chunk_received = pyqtSignal(str)
    finished = pyqtSignal(str)   # 完整世界文本
    error = pyqtSignal(str)

    def __init__(self, base_url: str, messages):
        super().__init__()
        self._base_url = base_url
        self._messages = messages
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        try:
            from core.llm_client import LLMClient
            from core.llm_client import sanitize_history_text
            llm = LLMClient(base_url=self._base_url)
            full = ""
            for chunk in llm.chat_stream(self._messages, temperature=0.8, max_tokens=4096):
                if self._stopped:
                    return
                full += chunk
                self.chunk_received.emit(chunk)
            cleaned, _ = sanitize_history_text(full)
            if not cleaned.strip():
                cleaned = full.strip()
            if self._stopped:
                return
            self.finished.emit(cleaned.strip())
        except Exception as e:
            if not self._stopped:
                self.error.emit(str(e))


class CharacterDialog(QDialog):
    """角色创建向导（游戏世界模式）"""

    def __init__(self, character_manager, character_name: str = None, parent=None,
                 server_manager=None, config=None):
        super().__init__(parent)
        self.character_manager = character_manager
        self.character_name = character_name
        self.server_manager = server_manager
        self.config = config
        self.icon_path = ""
        self.template_path = ""       # 角色基础模板 txt 路径
        self.player_template_path = ""  # 玩家模板 txt 路径
        self.world_text = ""          # 已生成的游戏世界文本
        self.world_file = ""          # 已保存的 游戏背景_编号.txt
        self._is_editing = character_name is not None

        self._gen_thread = None
        self._gen_worker = None
        self._waiting_server = False  # 正在等模型服务就绪

        self.setWindowTitle("编辑角色" if self._is_editing else "新建角色（游戏世界）")
        self.setMinimumSize(640, 700)
        self.setWindowIcon(QIcon(":/icons/settings.png"))

        self._init_ui()

        if self._is_editing:
            self._load_character()

    # ---------------- UI ----------------

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        # 对话框级兜底样式：所有无自定义样式的 QPushButton 都用深色主题渲染，
        # 防止 Windows 深色模式下系统默认样式把按钮画成与背景同色（不可见）
        self.setStyleSheet("""
            QDialog { background: #1e1e1e; }
            QPushButton {
                background: #3c3c3c; color: #ffffff;
                border: 1px solid #007acc; border-radius: 6px;
                padding: 5px 10px; font-size: 12px;
            }
            QPushButton:hover { background: #0a6ebd; border-color: #33bbff; }
            QPushButton:pressed { background: #095a9a; }
        """)

        title = QLabel("🎮 创建角色扮演游戏世界")
        title.setStyleSheet("color: #cccccc; font-size: 15px; font-weight: 700;")
        layout.addWidget(title)

        # ---- 1. 角色基础模板 ----
        t1 = QLabel("① 角色基础模板（txt 文件，文件名 = AI 角色名；含 角色背景 / 核心属性值 / 行为逻辑 / 互动）")
        t1.setStyleSheet("color: #cccccc; font-size: 12px; font-weight: 600;")
        t1.setWordWrap(True)
        layout.addWidget(t1)

        tpl_row = QHBoxLayout()
        self.template_label = QLabel("未选择")
        self.template_label.setStyleSheet("color: #888; font-size: 12px;")
        self.template_label.setWordWrap(True)
        tpl_row.addWidget(self.template_label, 1)
        self.select_tpl_btn = QPushButton("选择角色模板")
        self.select_tpl_btn.setFixedHeight(32)
        self.select_tpl_btn.setCursor(Qt.PointingHandCursor)
        self.select_tpl_btn.setToolTip("选择角色基础模板 txt（文件名 = AI 角色名；含 角色背景 / 核心属性值 / 行为逻辑 / 互动）")
        self.select_tpl_btn.clicked.connect(self._select_template)
        tpl_row.addWidget(self.select_tpl_btn)
        layout.addLayout(tpl_row)

        self.template_preview = QTextEdit()
        self.template_preview.setReadOnly(True)
        self.template_preview.setPlaceholderText("（选择角色基础模板后此处显示内容预览）")
        self._style_edit(self.template_preview)
        self.template_preview.setFixedHeight(90)
        layout.addWidget(self.template_preview)

        # ---- 2. 玩家模板 ----
        t2 = QLabel("② 玩家模板（txt 文件，仅需玩家背景，无需属性 / 互动）")
        t2.setStyleSheet("color: #cccccc; font-size: 12px; font-weight: 600;")
        layout.addWidget(t2)

        p_row = QHBoxLayout()
        self.player_label = QLabel("未选择")
        self.player_label.setStyleSheet("color: #888; font-size: 12px;")
        self.player_label.setWordWrap(True)
        p_row.addWidget(self.player_label, 1)
        self.select_player_btn = QPushButton("选择玩家模板")
        self.select_player_btn.setFixedHeight(32)
        self.select_player_btn.setCursor(Qt.PointingHandCursor)
        self.select_player_btn.setToolTip("选择玩家模板 txt（仅需玩家背景，无需属性 / 互动）")
        self.select_player_btn.clicked.connect(self._select_player_template)
        p_row.addWidget(self.select_player_btn)
        layout.addLayout(p_row)

        self.player_preview = QTextEdit()
        self.player_preview.setReadOnly(True)
        self.player_preview.setPlaceholderText("（选择玩家模板后此处显示内容预览）")
        self._style_edit(self.player_preview)
        self.player_preview.setFixedHeight(60)
        layout.addWidget(self.player_preview)

        # ---- 3. 模型选择 + 生成对话世界 ----
        t3 = QLabel("③ 选择生成对话世界的模型 → 点击「生成对话世界」")
        t3.setStyleSheet("color: #cccccc; font-size: 12px; font-weight: 600;")
        layout.addWidget(t3)

        gen_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(240)
        self.model_combo.setStyleSheet("""
            QComboBox {
                background: #2d2d30; color: #cccccc; border: 1px solid #3c3c3c;
                border-radius: 6px; padding: 5px 10px; font-size: 12px;
            }
            QComboBox:hover { border-color: #007acc; }
            QComboBox QAbstractItemView {
                background: #252526; color: #cccccc; border: 1px solid #3c3c3c;
                selection-background-color: #094771;
            }
        """)
        gen_row.addWidget(self.model_combo, 1)

        self.gen_world_btn = QPushButton("🌍 生成对话世界")
        self.gen_world_btn.setFixedSize(130, 32)
        self.gen_world_btn.setCursor(Qt.PointingHandCursor)
        self.gen_world_btn.setStyleSheet("""
            QPushButton {
                background: #007acc; color: white; border: none;
                border-radius: 6px; font-size: 12px; font-weight: 600;
            }
            QPushButton:hover { background: #1177bb; }
            QPushButton:disabled { background: #3c3c3c; color: #808080; }
        """)
        self.gen_world_btn.clicked.connect(self._on_generate_world)
        gen_row.addWidget(self.gen_world_btn)
        layout.addLayout(gen_row)

        self.gen_status = QLabel("")
        self.gen_status.setStyleSheet("color: #888; font-size: 11px;")
        self.gen_status.setWordWrap(True)
        layout.addWidget(self.gen_status)

        self.world_preview = QTextEdit()
        self.world_preview.setReadOnly(True)
        self.world_preview.setPlaceholderText("（生成的游戏世界将在此显示：玩家/角色日常生活、交际圈、可互动场所地点、社交方式）")
        self._style_edit(self.world_preview)
        layout.addWidget(self.world_preview, 1)

        # ---- 图标（可选） ----
        icon_row = QHBoxLayout()
        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(36, 36)
        self.icon_preview.setAlignment(Qt.AlignCenter)
        self.icon_preview.setStyleSheet("""
            QLabel { background: #2d2d30; border: 2px dashed #3c3c3c;
                     border-radius: 6px; font-size: 18px; }
        """)
        self.icon_preview.setText("👤")
        icon_row.addWidget(self.icon_preview)

        icon_btn = QPushButton("选择图标")
        icon_btn.setFixedHeight(28)
        icon_btn.setStyleSheet("""
            QPushButton { background: #3c3c3c; color: #cccccc; border: none;
                          border-radius: 4px; padding: 4px 12px; font-size: 11px; }
            QPushButton:hover { background: #4a4a4a; }
        """)
        icon_btn.clicked.connect(self._select_icon)
        icon_row.addWidget(icon_btn)
        icon_row.addStretch()
        layout.addLayout(icon_row)

        # ---- 底部按钮 ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(80, 36)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet("""
            QPushButton { background: #3c3c3c; color: #cccccc; border: none;
                          border-radius: 6px; font-size: 13px; }
            QPushButton:hover { background: #4a4a4a; }
        """)
        cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(cancel_btn)

        self.ok_btn = QPushButton("✅ 创建角色" if not self._is_editing else "保存")
        self.ok_btn.setFixedSize(110, 36)
        self.ok_btn.setCursor(Qt.PointingHandCursor)
        self.ok_btn.setStyleSheet("""
            QPushButton { background: #007acc; color: white; border: none;
                          border-radius: 6px; font-size: 13px; font-weight: 600; }
            QPushButton:hover { background: #1177bb; }
            QPushButton:disabled { background: #3c3c3c; color: #808080; }
        """)
        self.ok_btn.clicked.connect(self._on_ok)
        btn_row.addWidget(self.ok_btn)
        layout.addLayout(btn_row)

        self._refresh_models()

        # 监听模型服务状态（生成世界前等待就绪）
        if self.server_manager:
            try:
                self.server_manager.status_changed.connect(self._on_server_status)
            except Exception:
                pass

    def _style_edit(self, edit: QTextEdit):
        edit.setStyleSheet("""
            QTextEdit {
                background: #2d2d30; color: #cccccc; border: 1px solid #3c3c3c;
                border-radius: 6px; padding: 6px 10px; font-size: 12px;
            }
        """)
        edit.setFont(QFont("Microsoft YaHei", 9))

    # ---------------- 模板选择 ----------------

    def _select_template(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择角色基础模板", "", "文本文件 (*.txt)")
        if file_path:
            self.template_path = file_path
            name = os.path.splitext(os.path.basename(file_path))[0]
            self.template_label.setText(f"✅ {os.path.basename(file_path)}（角色名：{name}）")
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.template_preview.setPlainText(f.read()[:3000])
            except Exception:
                self.template_preview.setPlainText("（无法读取模板文件）")

    def _select_player_template(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择玩家模板", "", "文本文件 (*.txt)")
        if file_path:
            self.player_template_path = file_path
            self.player_label.setText(f"✅ {os.path.basename(file_path)}")
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.player_preview.setPlainText(f.read()[:3000])
            except Exception:
                self.player_preview.setPlainText("（无法读取模板文件）")

    def _select_icon(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择图标图片", "", "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if file_path:
            self.icon_path = file_path
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.icon_preview.setPixmap(scaled)
                self.icon_preview.setText("")
            else:
                QMessageBox.warning(self, "提示", "无法加载图片文件")

    def _refresh_models(self):
        """填充可用本地模型列表"""
        self.model_combo.clear()
        if not self.config:
            self.model_combo.addItem("（无配置）", "")
            return
        try:
            models = self.config.get_models()
        except Exception:
            models = []
        current_id = ""
        try:
            cur = self.config.get_current_model()
            current_id = cur.get("id", "") if cur else ""
        except Exception:
            pass
        count = 0
        for m in models:
            if m.get("type") != "local":
                continue
            path = m.get("model_path", "")
            ready = bool(path) and os.path.exists(path)
            mark = "✅ " if ready else "⭕ "
            self.model_combo.addItem(mark + m.get("name", m.get("id", "")), m.get("id", ""))
            if m.get("id") == current_id:
                self.model_combo.setCurrentIndex(self.model_combo.count() - 1)
            count += 1
        if count == 0:
            self.model_combo.addItem("（无可用本地模型）", "")

    # ---------------- 生成对话世界 ----------------

    def _on_generate_world(self):
        """点击「生成对话世界」：启动模型 → 等待就绪 → 流式生成世界 → 保存"""
        if self._gen_thread is not None:
            return  # 正在生成

        # 校验
        if not self.template_path and not self._is_editing:
            QMessageBox.warning(self, "提示", "请先选择角色基础模板（txt 文件）")
            return
        if not self.player_template_path and not self._is_editing:
            QMessageBox.warning(self, "提示", "请先选择玩家模板（txt 文件）")
            return
        model_id = self.model_combo.currentData()
        if not model_id:
            QMessageBox.warning(self, "提示", "请先选择用于生成对话世界的模型")
            return
        if not self.server_manager:
            self.gen_status.setText("❌ 无法访问模型服务管理器，请从主界面创建角色")
            return

        # 确保角色文件夹存在（模板复制进去）
        name = self._resolve_name()
        if not name:
            return
        try:
            if not self.character_manager.character_exists(name):
                self.character_manager.create_character(
                    name=name,
                    template_path=self.template_path or None,
                    player_template_path=self.player_template_path or None,
                    icon_path=self.icon_path if os.path.exists(self.icon_path) else None,
                )
            else:
                self.character_manager.update_character(
                    name=name,
                    template_path=self.template_path or None,
                    player_template_path=self.player_template_path or None,
                    icon_path=self.icon_path if os.path.exists(self.icon_path) else None,
                )
        except Exception as e:
            QMessageBox.warning(self, "错误", f"创建角色文件夹失败：{e}")
            return
        self.character_name = name

        # 切换到所选模型
        try:
            self.config.set_current_model(model_id)
        except Exception:
            pass

        self._pending_model_id = model_id
        status = self.server_manager.status
        if status == "running":
            # 当前模型是否就是所选模型？不是则重启
            try:
                cur = self.config.get_current_model()
                loaded = getattr(self.server_manager, "model_name", "")
                if loaded and cur and loaded != cur.get("name", ""):
                    self.gen_status.setText("🔄 正在切换模型加载，请稍候…")
                    self._waiting_server = True
                    self.server_manager.restart_server()
                    return
            except Exception:
                pass
            self._start_world_generation()
        elif status == "starting":
            self.gen_status.setText("⏳ 模型服务正在启动，就绪后将自动开始生成…")
            self._waiting_server = True
        else:
            self.gen_status.setText("🚀 正在启动模型服务（大模型加载可能需要几分钟）…")
            self._waiting_server = True
            self.server_manager.start_server()

    def _on_server_status(self, status: str):
        if not self._waiting_server:
            return
        if status == "running":
            self._waiting_server = False
            self._start_world_generation()
        elif status == "error":
            self._waiting_server = False
            self.gen_status.setText("❌ 模型服务启动失败，请检查模型配置/内存后重试")

    def _start_world_generation(self):
        """开始流式生成游戏世界"""
        char = self.character_manager.get_character(self.character_name)
        if not char:
            self.gen_status.setText("❌ 角色不存在")
            return
        template = self._read_file(self.template_path) or char.get_template()
        player_tpl = self._read_file(self.player_template_path) or char.get_player_template()
        if not template.strip():
            QMessageBox.warning(self, "提示", "角色基础模板内容为空")
            return
        if not player_tpl.strip():
            QMessageBox.warning(self, "提示", "玩家模板内容为空")
            return

        from core.character_manager import build_world_prompt
        messages = build_world_prompt(template, player_tpl)

        base_url = "http://127.0.0.1:8080"
        if self.server_manager:
            try:
                url = self.server_manager.get_server_url()
                if url:
                    base_url = url
            except Exception:
                pass

        self.world_preview.clear()
        self.gen_status.setText("🌍 正在生成对话世界…（玩家/角色生活、交际圈、场所地点、社交方式）")
        self.gen_world_btn.setEnabled(False)
        self.ok_btn.setEnabled(False)

        self._gen_thread = QThread()
        self._gen_worker = _WorldGenWorker(base_url, messages)
        self._gen_worker.moveToThread(self._gen_thread)
        self._gen_worker.chunk_received.connect(self._on_world_chunk)
        self._gen_worker.finished.connect(self._on_world_finished)
        self._gen_worker.error.connect(self._on_world_error)
        self._gen_thread.started.connect(self._gen_worker.run)
        self._gen_thread.start()

    def _on_world_chunk(self, chunk: str):
        self.world_preview.insertPlainText(chunk)
        sb = self.world_preview.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_world_finished(self, text: str):
        self._cleanup_gen_thread()
        self.world_text = text
        self.world_preview.setPlainText(text)
        # 保存 游戏背景_编号.txt 到角色文件夹
        try:
            char = self.character_manager.get_character(self.character_name)
            self.world_file = char.save_world_file(text)
            self.gen_status.setText(f"✅ 游戏世界已生成并保存：{os.path.basename(self.world_file)}\n"
                                    f"现在可以点击「创建角色」开始游戏。")
        except Exception as e:
            self.gen_status.setText(f"⚠️ 世界已生成但保存失败：{e}")
        self.gen_world_btn.setEnabled(True)
        self.ok_btn.setEnabled(True)

    def _on_world_error(self, err: str):
        self._cleanup_gen_thread()
        self.gen_status.setText(f"❌ 生成失败：{err[:300]}")
        self.gen_world_btn.setEnabled(True)
        self.ok_btn.setEnabled(True)

    def _cleanup_gen_thread(self):
        if self._gen_thread:
            self._gen_thread.quit()
            self._gen_thread.wait(2000)
        self._gen_thread = None
        self._gen_worker = None

    # ---------------- 创建角色 ----------------

    def _resolve_name(self) -> str:
        """角色名 = 模板文件名（去扩展名）"""
        if self._is_editing and self.character_name:
            return self.character_name
        if not self.template_path:
            return ""
        name = os.path.splitext(os.path.basename(self.template_path))[0].strip()
        invalid_chars = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']
        if not name or any(c in name for c in invalid_chars):
            QMessageBox.warning(self, "提示", "模板文件名不能作为角色名（含特殊字符或为空）\n"
                                            f"当前：{name!r}")
            return ""
        if not self._is_editing and self.character_manager.character_exists(name):
            # 已存在：允许（视为重新生成世界/更新模板）
            reply = QMessageBox.question(
                self, "角色已存在",
                f"角色 '{name}' 已存在，将更新其模板并重新生成世界。\n继续吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if reply != QMessageBox.Yes:
                return ""
        return name

    def _on_ok(self):
        """创建角色：创建对话文件夹 角色名_编号/（游戏背景.txt + 对话历史.txt）"""
        name = self._resolve_name()
        if not name:
            return

        try:
            if not self.character_manager.character_exists(name):
                self.character_manager.create_character(
                    name=name,
                    template_path=self.template_path or None,
                    player_template_path=self.player_template_path or None,
                    icon_path=self.icon_path if os.path.exists(self.icon_path) else None,
                )
            else:
                self.character_manager.update_character(
                    name=name,
                    template_path=self.template_path or None,
                    player_template_path=self.player_template_path or None,
                    icon_path=self.icon_path if os.path.exists(self.icon_path) else None,
                )
            self.character_name = name
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存角色失败：{e}")
            return

        if self._is_editing:
            # 编辑模式：不新建对话文件夹
            self.accept()
            return

        # 未生成世界时提示（仍允许创建，游戏背景为空）
        char = self.character_manager.get_character(name)
        has_world = bool(self.world_file) or bool(char.get_latest_world_file())
        if not has_world:
            reply = QMessageBox.question(
                self, "未生成游戏世界",
                "尚未生成游戏背景（点击「生成对话世界」可自动构建世界）。\n"
                "仍要创建角色吗？（游戏背景将为空）",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        # 创建对话文件夹（角色名_编号）
        try:
            session_path = char.create_game_session(world_src=self.world_file or None)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"创建对话文件夹失败：{e}")
            return

        self.created_session_path = session_path
        self.accept()

    def _on_cancel(self):
        if self._gen_thread is not None:
            reply = QMessageBox.question(
                self, "正在生成", "游戏世界正在生成中，确定要取消吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            if self._gen_worker:
                self._gen_worker.stop()
            self._cleanup_gen_thread()
        self.reject()

    # ---------------- 编辑模式加载 ----------------

    def _read_file(self, path: str) -> str:
        if path and os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception:
                pass
        return ""

    def _load_character(self):
        char = self.character_manager.get_character(self.character_name)
        if not char:
            return
        self.template_path = char.template_file if os.path.exists(char.template_file) else ""
        self.template_label.setText(f"✅ {char.name}（角色基础模板）")
        self.template_preview.setPlainText(char.get_template()[:3000])

        self.player_template_path = char.player_template_file if os.path.exists(char.player_template_file) else ""
        if self.player_template_path:
            self.player_label.setText(f"✅ {os.path.basename(self.player_template_path)}")
            self.player_preview.setPlainText(self._read_file(self.player_template_path)[:3000])
        else:
            self.player_label.setText("未设置（可在上方选择玩家模板）")

        world = char.get_latest_world_file()
        if world:
            self.world_file = world
            self.world_preview.setPlainText(self._read_file(world))

        if char.has_icon:
            self.icon_path = char.icon_file
            pixmap = QPixmap(char.icon_file)
            if not pixmap.isNull():
                scaled = pixmap.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.icon_preview.setPixmap(scaled)
                self.icon_preview.setText("")

    def closeEvent(self, event):
        if self._gen_worker:
            self._gen_worker.stop()
        self._cleanup_gen_thread()
        super().closeEvent(event)
