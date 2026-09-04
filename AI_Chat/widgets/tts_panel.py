"""
语音系统配置面板 - GPT-SoVITS + CosyVoice 双引擎管理
"""
import os
import sys
import subprocess
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QGroupBox, QFileDialog, QTextEdit, QSplitter, QCheckBox,
    QDoubleSpinBox, QSpinBox, QMessageBox, QFrame, QScrollArea, QSizePolicy,
    QToolButton
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer


class TestSynthesizeWorker(QThread):
    """后台测试合成"""
    finished = pyqtSignal(str)        # wav 路径
    error = pyqtSignal(str)

    def __init__(self, engine: str, text: str, params: dict):
        super().__init__()
        self.engine = engine
        self.text = text
        self.params = params

    def run(self):
        try:
            text = self.text.strip() or "你好，这是一段测试语音。"
            if self.engine == "gpt_sovits":
                from core.gpt_sovits_client import GptSovitsClient
                client = GptSovitsClient()
                # 不传 refer_wav_path/prompt_text — 让服务用启动时 -dr/-dt 设置的 default_refer
                path = client.synthesize(
                    text=text,
                    text_language=self.params.get("text_language", "zh"),
                    refer_wav_path="",
                    prompt_text="",
                    prompt_language=self.params.get("refer_lang", "zh"),
                    top_k=self.params.get("top_k", 5),
                    top_p=self.params.get("top_p", 1.0),
                    temperature=self.params.get("temperature", 1.0),
                    speed=self.params.get("speed", 1.0),
                )
            else:
                from core.tts_client import TTSClient
                client = TTSClient()
                path = client.synthesize(
                    text=text,
                    voice=self.params.get("voice", ""),
                    speed=self.params.get("speed", 1.0),
                    ref_path=self.params.get("ref_path", ""),
                )
            self.finished.emit(path)
        except Exception as e:
            self.error.emit(str(e))


class TTSPanel(QWidget):
    """语音系统配置面板（图生视频右边的独立选项卡）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        from core.config import get_config_manager
        self.cfg = get_config_manager()
        self._init_ui()
        self._connect_signals()
        self._load_config()
        # 音频播放器
        self._media_player = QMediaPlayer(self)
        self._media_player.stateChanged.connect(self._on_player_state_changed)
        self._last_wav = ""

    # ============================================================
    # UI 构建
    # ============================================================

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # 顶部标题栏（引擎选择由顶栏 combo_tts 统一管理，这里只显示状态）
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        top_bar.addWidget(QLabel("🎤 语音系统"))
        top_bar.addStretch()

        self.status_label = QLabel("● 未启动")
        self.status_label.setStyleSheet(self._status_style("stopped"))
        top_bar.addWidget(self.status_label)

        outer.addLayout(top_bar)

        # 分割器：左侧配置 + 右侧日志
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_config_area())
        splitter.addWidget(self._build_log_area())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([600, 400])
        outer.addWidget(splitter, 1)

    def _build_config_area(self) -> QWidget:
        """左侧配置区（滚动）"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        container.setStyleSheet("""
            /* 所有下拉框 — 修复 popup list 一半黑的问题 */
            QComboBox {
                background: rgba(30,30,46,0.95);
                color: #e0f0ff;
                border: 1px solid rgba(0,212,255,0.4);
                border-radius: 4px;
                padding: 4px 8px;
                min-height: 20px;
            }
            QComboBox:hover { border-color: #00d4ff; background: rgba(0,212,255,0.12); }
            QComboBox::drop-down {
                border: none;
                width: 18px;
                background: rgba(0,212,255,0.15);
                border-left: 1px solid rgba(0,212,255,0.4);
            }
            QComboBox QAbstractItemView {
                background: #1a1a2e;
                color: #e0f0ff;
                border: 1px solid rgba(0,212,255,0.5);
                selection-background-color: rgba(0,212,255,0.35);
                selection-color: #ffffff;
                outline: 0;
                padding: 2px;
            }
            QComboBox QAbstractItemView::item {
                padding: 4px 8px;
                min-height: 18px;
            }
            QComboBox QAbstractItemView::item:selected {
                background: rgba(0,212,255,0.35);
                color: #ffffff;
            }
            QComboBox QAbstractItemView::item:hover {
                background: rgba(0,212,255,0.18);
            }
            /* 数字输入框 */
            QSpinBox, QDoubleSpinBox {
                background: rgba(30,30,46,0.95);
                color: #e0f0ff;
                border: 1px solid rgba(0,212,255,0.4);
                border-radius: 4px;
                padding: 2px 6px;
            }
            QSpinBox:focus, QDoubleSpinBox:focus { border-color: #00d4ff; }
            /* 文本输入框 */
            QLineEdit {
                background: rgba(30,30,46,0.95);
                color: #e0f0ff;
                border: 1px solid rgba(0,212,255,0.4);
                border-radius: 4px;
                padding: 4px 8px;
            }
            QLineEdit:focus { border-color: #00d4ff; }
        """)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ---- GPT-SoVITS 配置组 ----
        self.gs_group = QGroupBox("GPT-SoVITS 配置")
        gs_layout = QVBoxLayout(self.gs_group)
        gs_layout.setSpacing(8)

        # 下载地址提示
        self.gs_download_hint = QLabel(
            '📥 <b>GPT-SoVITS-v2pro 下载</b>：'
            '<a href="https://x-jzy.github.io/2025/10/31/GPT-SoVITS%E7%9A%84%E6%9C%AC%E5%9C%B0%E9%83%A8%E7%BD%B2%E4%B8%8E%E4%BD%BF%E7%94%A8/" style="color:#58a6ff;">'
            '第三方教程页（x-jzy.github.io）</a>'
            ''
        )
        self.gs_download_hint.setOpenExternalLinks(True)
        self.gs_download_hint.setStyleSheet(
            "color: #888; font-size: 11px; padding: 4px 0px;"
        )
        self.gs_download_hint.setWordWrap(True)
        gs_layout.addWidget(self.gs_download_hint)

        # 整合包路径
        row = QHBoxLayout()
        row.addWidget(QLabel("整合包路径:"))
        self.gs_repo_edit = QLineEdit()
        self.gs_repo_edit.setPlaceholderText("GPT-SoVITS-v2pro-20250604 文件夹路径")
        row.addWidget(self.gs_repo_edit, 1)
        self.gs_repo_btn = QPushButton("浏览...")
        row.addWidget(self.gs_repo_btn)
        gs_layout.addLayout(row)

        # 设备
        row = QHBoxLayout()
        row.addWidget(QLabel("推理设备:"))
        self.gs_device_combo = QComboBox()
        self.gs_device_combo.addItems(["cuda", "cpu"])
        row.addWidget(self.gs_device_combo)
        row.addSpacing(16)
        row.addWidget(QLabel("端口:"))
        self.gs_port_edit = QLineEdit()
        self.gs_port_edit.setFixedWidth(80)
        self.gs_port_edit.setPlaceholderText("9880")
        row.addWidget(self.gs_port_edit)
        row.addStretch()
        gs_layout.addLayout(row)

        # SoVITS 权重
        row = QHBoxLayout()
        row.addWidget(QLabel("SoVITS 权重 (.pth):"))
        self.gs_sovits_edit = QLineEdit()
        self.gs_sovits_edit.setPlaceholderText("浏览选择 .pth 文件")
        row.addWidget(self.gs_sovits_edit, 1)
        self.gs_sovits_btn = QPushButton("选择...")
        row.addWidget(self.gs_sovits_btn)
        gs_layout.addLayout(row)

        # GPT 权重
        row = QHBoxLayout()
        row.addWidget(QLabel("GPT 权重 (.ckpt):"))
        self.gs_gpt_edit = QLineEdit()
        self.gs_gpt_edit.setPlaceholderText("浏览选择 .ckpt 文件")
        row.addWidget(self.gs_gpt_edit, 1)
        self.gs_gpt_btn = QPushButton("选择...")
        row.addWidget(self.gs_gpt_btn)
        gs_layout.addLayout(row)

        # 参考音频组
        ref_frame = QFrame()
        ref_frame.setStyleSheet("QFrame { border: 1px solid rgba(0,212,255,0.2); border-radius: 6px; background: rgba(0,212,255,0.04); }")
        ref_layout = QVBoxLayout(ref_frame)
        ref_layout.setContentsMargins(8, 8, 8, 8)
        ref_layout.setSpacing(6)

        ref_title = QLabel("🔊 默认参考音频（零样本克隆）")
        ref_title.setStyleSheet("color: #00d4ff; font-weight: 600;")
        ref_layout.addWidget(ref_title)

        row = QHBoxLayout()
        row.addWidget(QLabel("音频文件:"))
        self.gs_refer_wav_edit = QLineEdit()
        self.gs_refer_wav_edit.setPlaceholderText("参考 wav 文件（5-10秒清晰人声）")
        row.addWidget(self.gs_refer_wav_edit, 1)
        self.gs_refer_wav_btn = QPushButton("选择...")
        row.addWidget(self.gs_refer_wav_btn)
        ref_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("参考文本:"))
        self.gs_refer_text_edit = QLineEdit()
        self.gs_refer_text_edit.setPlaceholderText("参考音频的文字内容")
        row.addWidget(self.gs_refer_text_edit, 1)
        ref_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("参考语种:"))
        self.gs_refer_lang_combo = QComboBox()
        self.gs_refer_lang_combo.addItems(["zh", "en", "ja", "ko", "yue"])
        row.addWidget(self.gs_refer_lang_combo)
        row.addStretch()
        ref_layout.addLayout(row)

        gs_layout.addWidget(ref_frame)

        # 推理参数组
        params_frame = QFrame()
        params_frame.setStyleSheet("QFrame { border: 1px solid rgba(0,212,255,0.2); border-radius: 6px; background: rgba(0,212,255,0.04); }")
        params_layout = QVBoxLayout(params_frame)
        params_layout.setContentsMargins(8, 8, 8, 8)
        params_layout.setSpacing(6)

        params_title = QLabel("⚙️ 推理参数")
        params_title.setStyleSheet("color: #00d4ff; font-weight: 600;")
        params_layout.addWidget(params_title)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("top_k:"))
        self.gs_topk_spin = QSpinBox()
        self.gs_topk_spin.setRange(1, 50)
        self.gs_topk_spin.setValue(5)
        row1.addWidget(self.gs_topk_spin)
        row1.addSpacing(12)
        row1.addWidget(QLabel("top_p:"))
        self.gs_topp_spin = QDoubleSpinBox()
        self.gs_topp_spin.setRange(0.0, 1.0)
        self.gs_topp_spin.setSingleStep(0.05)
        self.gs_topp_spin.setValue(1.0)
        self.gs_topp_spin.setDecimals(2)
        row1.addWidget(self.gs_topp_spin)
        row1.addSpacing(12)
        row1.addWidget(QLabel("temperature:"))
        self.gs_temp_spin = QDoubleSpinBox()
        self.gs_temp_spin.setRange(0.0, 2.0)
        self.gs_temp_spin.setSingleStep(0.1)
        self.gs_temp_spin.setValue(1.0)
        self.gs_temp_spin.setDecimals(1)
        row1.addWidget(self.gs_temp_spin)
        params_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("语速:"))
        self.gs_speed_spin = QDoubleSpinBox()
        self.gs_speed_spin.setRange(0.25, 4.0)
        self.gs_speed_spin.setSingleStep(0.1)
        self.gs_speed_spin.setValue(1.0)
        self.gs_speed_spin.setDecimals(2)
        row2.addWidget(self.gs_speed_spin)
        row2.addSpacing(12)
        row2.addWidget(QLabel("文本语种:"))
        self.gs_text_lang_combo = QComboBox()
        self.gs_text_lang_combo.addItems(["zh", "en", "ja", "ko", "yue"])
        row2.addWidget(self.gs_text_lang_combo)
        row2.addStretch()
        params_layout.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("切分符号:"))
        self.gs_cutpunc_edit = QLineEdit()
        self.gs_cutpunc_edit.setPlaceholderText('如 ",.，。" 留空使用默认')
        self.gs_cutpunc_edit.setFixedWidth(200)
        row3.addWidget(self.gs_cutpunc_edit)
        row3.addStretch()
        params_layout.addLayout(row3)

        gs_layout.addWidget(params_frame)

        # CosyVoice 配置组（与设置页一致：语音模型 + 语速 + 字数上限 + 分步安装）
        self.cv_group = QGroupBox("CosyVoice 配置")
        cv_layout = QVBoxLayout(self.cv_group)
        cv_layout.setSpacing(8)

        # 语音模型选择
        row = QHBoxLayout()
        row.addWidget(QLabel("语音模型:"))
        self.cv_model_combo = QComboBox()
        self.cv_model_combo.addItem("CosyVoice2-0.5B（推荐，约 5GB）", "CosyVoice2-0.5B")
        self.cv_model_combo.addItem("Fun-CosyVoice3-0.5B-2512（约 9.1GB，效果更好）", "Fun-CosyVoice3-0.5B-2512")
        row.addWidget(self.cv_model_combo, 1)
        cv_layout.addLayout(row)

        # 默认音色
        row = QHBoxLayout()
        row.addWidget(QLabel("默认音色:"))
        self.cv_voice_combo = QComboBox()
        self.cv_voice_combo.setEditable(True)
        for v in ["中文女", "中文男", "英文女", "英文男", "日文女", "日文男", "粤语女", "韩语女"]:
            self.cv_voice_combo.addItem(v)
        self.btn_refresh_voices = QPushButton("🔄 刷新")
        self.btn_refresh_voices.setFixedWidth(60)
        self.btn_refresh_voices.clicked.connect(self._refresh_cv_voices)
        row.addWidget(self.cv_voice_combo, 1)
        row.addWidget(self.btn_refresh_voices)
        cv_layout.addLayout(row)

        # 语速 + 字数上限
        row = QHBoxLayout()
        row.addWidget(QLabel("语速:"))
        self.cv_speed_spin = QDoubleSpinBox()
        self.cv_speed_spin.setRange(0.5, 2.0)
        self.cv_speed_spin.setSingleStep(0.1)
        self.cv_speed_spin.setValue(1.0)
        self.cv_speed_spin.setDecimals(2)
        self.cv_speed_spin.setFixedWidth(80)
        row.addWidget(self.cv_speed_spin)
        row.addSpacing(16)
        row.addWidget(QLabel("朗读字数上限:"))
        self.cv_max_chars_spin = QSpinBox()
        self.cv_max_chars_spin.setRange(100, 10000)
        self.cv_max_chars_spin.setSingleStep(100)
        self.cv_max_chars_spin.setValue(1000)
        self.cv_max_chars_spin.setToolTip("每次朗读的最大文本字数，超出部分截断。字数越多合成耗时越长")
        self.cv_max_chars_spin.setFixedWidth(90)
        row.addWidget(self.cv_max_chars_spin)
        row.addStretch()
        cv_layout.addLayout(row)

        # 服务端口
        row = QHBoxLayout()
        row.addWidget(QLabel("服务端口:"))
        self.cv_port_spin = QSpinBox()
        self.cv_port_spin.setRange(1024, 65535)
        self.cv_port_spin.setValue(8901)
        self.cv_port_spin.setFixedWidth(90)
        row.addWidget(self.cv_port_spin)
        row.addStretch()
        cv_layout.addLayout(row)

        # 分步安装面板
        try:
            from widgets.tts_install_panel import CosyVoiceInstallPanel
            self.cv_install_panel = CosyVoiceInstallPanel()
            self.cv_install_panel.setStyleSheet(
                "CosyVoiceInstallPanel { border: 1px solid rgba(0,212,255,0.2); border-radius: 6px;"
                " background: rgba(0,212,255,0.04); }")
            cv_layout.addWidget(self.cv_install_panel)
        except Exception as e:
            cv_layout.addWidget(QLabel(f"⚠️ CosyVoiceInstallPanel 加载失败: {e}"))

        # 启动/停止按钮行（两个引擎共用，放在 group 外面）
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_start = QPushButton("▶️ 启动服务")
        self.btn_start.setFixedHeight(34)
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setStyleSheet(self._btn_primary_style())
        btn_row.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹ 停止服务")
        self.btn_stop.setFixedHeight(34)
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setStyleSheet(self._btn_danger_style())
        self.btn_stop.setEnabled(False)
        btn_row.addWidget(self.btn_stop)

        self.btn_save = QPushButton("💾 保存配置")
        self.btn_save.setFixedHeight(34)
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setStyleSheet(self._btn_secondary_style())
        btn_row.addWidget(self.btn_save)

        btn_row.addStretch()

        self.btn_autostart = QCheckBox("启动程序时自动启动服务")
        self.btn_autostart.setStyleSheet("color: #8aa0b0;")
        btn_row.addWidget(self.btn_autostart)

        # 先加引擎配置组，再加大按钮行
        layout.addWidget(self.gs_group)
        layout.addWidget(self.cv_group)
        layout.addLayout(btn_row)

        # 测试合成
        test_group = QGroupBox("🔬 测试合成")
        test_layout = QVBoxLayout(test_group)
        test_layout.setSpacing(8)

        self.test_edit = QLineEdit()
        self.test_edit.setPlaceholderText("输入测试文本...")
        test_layout.addWidget(self.test_edit)

        # CosyVoice 参考音频（zero-shot 克隆用，仅 CosyVoice 引擎时显示）
        row_ref = QHBoxLayout()
        self.test_ref_label = QLabel("🎙️ 参考音频:")
        self.test_ref_label.setToolTip("CosyVoice zero-shot 克隆用的参考 wav 文件（5-10秒清晰人声）")
        row_ref.addWidget(self.test_ref_label)
        self.test_ref_edit = QLineEdit()
        self.test_ref_edit.setPlaceholderText("留空=使用默认音色；选择 wav=zero-shot 克隆该音色")
        row_ref.addWidget(self.test_ref_edit, 1)
        self.btn_pick_ref = QPushButton("选择音频...")
        self.btn_pick_ref.setFixedSize(88, 28)
        self.btn_pick_ref.setCursor(Qt.PointingHandCursor)
        self.btn_pick_ref.setStyleSheet(self._btn_secondary_style())
        self.btn_pick_ref.clicked.connect(self._pick_test_ref)
        row_ref.addWidget(self.btn_pick_ref)
        test_layout.addLayout(row_ref)
        self._test_ref_row_widgets = [self.test_ref_label, self.test_ref_edit, self.btn_pick_ref]

        # 合成按钮行
        row = QHBoxLayout()
        self.btn_test = QPushButton("🎵 合成测试")
        self.btn_test.setFixedHeight(34)
        self.btn_test.setCursor(Qt.PointingHandCursor)
        self.btn_test.setStyleSheet(self._btn_primary_style())
        row.addWidget(self.btn_test)

        # 播放控件行（初始禁用，合成成功后启用）
        self.btn_play = QPushButton("▶️ 播放")
        self.btn_play.setFixedHeight(34)
        self.btn_play.setCursor(Qt.PointingHandCursor)
        self.btn_play.setStyleSheet(self._btn_secondary_style())
        self.btn_play.setEnabled(False)
        self.btn_play.clicked.connect(self._toggle_play)
        row.addWidget(self.btn_play)

        self.btn_open_file = QPushButton("📂 打开文件位置")
        self.btn_open_file.setFixedHeight(34)
        self.btn_open_file.setCursor(Qt.PointingHandCursor)
        self.btn_open_file.setStyleSheet(self._btn_secondary_style())
        self.btn_open_file.setEnabled(False)
        self.btn_open_file.clicked.connect(self._open_wav_location)
        row.addWidget(self.btn_open_file)

        row.addStretch()
        test_layout.addLayout(row)

        self.test_status = QLabel("")
        self.test_status.setStyleSheet("color: #8aa0b0; font-size: 12px;")
        test_layout.addWidget(self.test_status)

        layout.addWidget(test_group)
        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _build_log_area(self) -> QWidget:
        """右侧日志区"""
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.addWidget(QLabel("📜 服务日志"))
        header.addStretch()
        self.btn_clear_log = QPushButton("清空")
        self.btn_clear_log.setFixedSize(60, 24)
        self.btn_clear_log.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.08); color: #8aa0b0; border: none; border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.15); }")
        header.addWidget(self.btn_clear_log)
        layout.addLayout(header)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            "QTextEdit { background: rgba(0,0,0,0.4); color: #c0d8e8; border: 1px solid rgba(0,212,255,0.15);"
            " border-radius: 6px; font-family: Consolas, monospace; font-size: 12px; }")
        layout.addWidget(self.log_text, 1)

        return frame

    # ============================================================
    # 样式
    # ============================================================

    def _status_style(self, status: str) -> str:
        colors = {
            "stopped": ("#888", "rgba(255,255,255,0.04)", "rgba(255,255,255,0.06)"),
            "starting": ("#ff9800", "rgba(255,152,0,0.1)", "rgba(255,152,0,0.3)"),
            "running": ("#4caf50", "rgba(76,175,80,0.1)", "rgba(76,175,80,0.3)"),
            "error": ("#f44336", "rgba(244,67,54,0.1)", "rgba(244,67,54,0.3)"),
        }
        fg, bg, bd = colors.get(status, colors["stopped"])
        return (f"color: {fg}; padding: 4px 10px; border-radius: 10px;"
                f" background: {bg}; border: 1px solid {bd}; font-size: 12px;")

    def _btn_primary_style(self) -> str:
        return ("QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                "stop:0 #007acc, stop:1 #00d4ff); color: white; border: none;"
                " border-radius: 6px; font-weight: 700; padding: 6px 16px; }"
                "QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                "stop:0 #0a8bde, stop:1 #1fe0ff); }"
                "QPushButton:disabled { background: rgba(100,100,100,0.4); color: rgba(200,200,200,0.5); }")

    def _btn_danger_style(self) -> str:
        return ("QPushButton { background: rgba(244,67,54,0.8); color: white; border: none;"
                " border-radius: 6px; font-weight: 700; padding: 6px 16px; }"
                "QPushButton:hover { background: rgba(244,67,54,1.0); }"
                "QPushButton:disabled { background: rgba(100,100,100,0.4); color: rgba(200,200,200,0.5); }")

    def _btn_secondary_style(self) -> str:
        return ("QPushButton { background: rgba(0,212,255,0.08); color: #00d4ff;"
                " border: 1px solid rgba(0,212,255,0.4); border-radius: 6px;"
                " font-weight: 600; padding: 6px 14px; }"
                "QPushButton:hover { background: rgba(0,212,255,0.18); color: white;"
                " border: 1px solid rgba(0,212,255,0.7); }"
                "QPushButton:disabled { background: rgba(100,100,100,0.2); color: rgba(200,200,200,0.4); }")

    # ============================================================
    # 信号连接
    # ============================================================

    def _connect_signals(self):
        # 引擎切换

        # GPT-SoVITS 文件选择
        self.gs_repo_btn.clicked.connect(self._choose_repo)
        self.gs_sovits_btn.clicked.connect(lambda: self._choose_file(self.gs_sovits_edit, "SoVITS 权重 (*.pth)", True))
        self.gs_gpt_btn.clicked.connect(lambda: self._choose_file(self.gs_gpt_edit, "GPT 权重 (*.ckpt)", True))
        self.gs_refer_wav_btn.clicked.connect(lambda: self._choose_file(self.gs_refer_wav_edit, "参考音频 (*.wav *.mp3)", True))

        # CosyVoice 刷新音色（btn_refresh_voices 已在 _build_config_area 创建，这里只连信号）
        self.btn_refresh_voices.clicked.connect(self._refresh_cv_voices)

        # 启动/停止/保存
        self.btn_start.clicked.connect(self._start_service)
        self.btn_stop.clicked.connect(self._stop_service)
        self.btn_save.clicked.connect(self._save_config)

        # 日志
        self.btn_clear_log.clicked.connect(lambda: self.log_text.clear())

        # 测试
        self.btn_test.clicked.connect(self._test_synthesize)

    # ============================================================
    # 配置读写
    # ============================================================

    def _load_config(self):
        cfg = self.cfg.load()

        # TTS 引擎
        engine = cfg.get("tts_engine", "cosyvoice")
        self._on_engine_changed(self._engine_idx())

        # GPT-SoVITS
        gs = cfg.get("gpt_sovits", {})
        self.gs_repo_edit.setText(gs.get("repo_dir", ""))
        self.gs_device_combo.setCurrentText(gs.get("device", "cuda"))
        self.gs_port_edit.setText(str(gs.get("port", 9880)))
        self.gs_sovits_edit.setText(gs.get("sovits_model", ""))
        self.gs_gpt_edit.setText(gs.get("gpt_model", ""))
        self.gs_refer_wav_edit.setText(gs.get("default_refer_wav", ""))
        self.gs_refer_text_edit.setText(gs.get("default_refer_text", ""))
        self.gs_refer_lang_combo.setCurrentText(gs.get("default_refer_lang", "zh"))
        self.gs_text_lang_combo.setCurrentText(gs.get("default_text_language", "zh"))
        self.gs_topk_spin.setValue(int(gs.get("top_k", 5)))
        self.gs_topp_spin.setValue(float(gs.get("top_p", 1.0)))
        self.gs_temp_spin.setValue(float(gs.get("temperature", 1.0)))
        self.gs_speed_spin.setValue(float(gs.get("speed", 1.0)))
        self.gs_cutpunc_edit.setText(gs.get("cut_punc", ""))
        self.btn_autostart.setChecked(gs.get("auto_start", False))

        # CosyVoice
        tts = cfg.get("tts", {})
        # 语音模型
        model_key = tts.get("model_key", "CosyVoice2-0.5B")
        idx = self.cv_model_combo.findData(model_key)
        if idx >= 0:
            self.cv_model_combo.setCurrentIndex(idx)
        # 默认音色
        voice = tts.get("voice", "中文女")
        v_idx = self.cv_voice_combo.findText(voice)
        if v_idx >= 0:
            self.cv_voice_combo.setCurrentIndex(v_idx)
        else:
            self.cv_voice_combo.setCurrentText(voice)
        # 语速
        self.cv_speed_spin.setValue(float(tts.get("speed", 1.0)))
        # 朗读字数上限
        self.cv_max_chars_spin.setValue(int(tts.get("max_read_chars", 1000)))
        # 服务端口
        self.cv_port_spin.setValue(int(tts.get("port", 8901)))
        # 刷新音色列表
        self._refresh_cv_voices()

        # 状态监听
        self._setup_status_listener()

    def _save_config(self):
        """保存所有配置到 config.json"""
        from core.config import get_config_manager
        cfg = get_config_manager()

        cfg.set("tts_engine", "cosyvoice" if self._engine_idx() == 0 else "gpt_sovits")

        # GPT-SoVITS
        gs = {
            "repo_dir": self.gs_repo_edit.text().strip(),
            "device": self.gs_device_combo.currentText(),
            "host": "127.0.0.1",
            "port": int(self.gs_port_edit.text() or 9880),
            "sovits_model": self.gs_sovits_edit.text().strip(),
            "gpt_model": self.gs_gpt_edit.text().strip(),
            "default_refer_wav": self.gs_refer_wav_edit.text().strip(),
            "default_refer_text": self.gs_refer_text_edit.text().strip(),
            "default_refer_lang": self.gs_refer_lang_combo.currentText(),
            "default_text_language": self.gs_text_lang_combo.currentText(),
            "top_k": self.gs_topk_spin.value(),
            "top_p": self.gs_topp_spin.value(),
            "temperature": self.gs_temp_spin.value(),
            "speed": self.gs_speed_spin.value(),
            "cut_punc": self.gs_cutpunc_edit.text().strip(),
            "auto_start": self.btn_autostart.isChecked(),
        }
        for k, v in gs.items():
            cfg.set(f"gpt_sovits.{k}", v)

        # CosyVoice
        cfg.set("tts.model_key", self.cv_model_combo.currentData() or "CosyVoice2-0.5B")
        cfg.set("tts.voice", self.cv_voice_combo.currentText().strip() or "中文女")
        cfg.set("tts.speed", self.cv_speed_spin.value())
        cfg.set("tts.max_read_chars", self.cv_max_chars_spin.value())
        cfg.set("tts.port", self.cv_port_spin.value())

        self._append_log("✅ 配置已保存", "info")
        QMessageBox.information(self, "保存成功", "配置已保存到 config.json")

    # ============================================================
    # 引擎切换（由顶栏 combo_tts 统一驱动）
    # ============================================================

    def _engine_idx(self) -> int:
        """当前引擎索引：0=CosyVoice, 1=GPT-SoVITS（从 config 读，由顶栏 combo_tts 维护）"""
        engine = self.cfg.get("tts_engine", "gpt_sovits")
        return 0 if engine == "cosyvoice" else 1

    def _on_engine_changed(self, idx: int):
        """0=CosyVoice, 1=GPT-SoVITS — 只显示当前引擎的配置组（由顶栏 combo_tts 调用）"""
        is_gs = idx == 1
        self.gs_group.setVisible(is_gs)
        self.cv_group.setVisible(not is_gs)
        # 测试合成区：参考音频行仅 CosyVoice 引擎时显示
        if hasattr(self, '_test_ref_row_widgets'):
            for w in self._test_ref_row_widgets:
                w.setVisible(not is_gs)

    # ============================================================
    # 文件选择
    # ============================================================

    def _choose_repo(self):
        start = self.gs_repo_edit.text() or ""
        d = QFileDialog.getExistingDirectory(self, "选择 GPT-SoVITS 整合包目录", start)
        if d:
            self.gs_repo_edit.setText(d)
            # 自动探测权重
            self._auto_detect_weights(d)

    def _auto_detect_weights(self, repo: str):
        """自动扫描 GPT_weights_v2Pro / SoVITS_weights_v2Pro 等目录"""
        if not os.path.isdir(repo):
            return
        for subdir in ["GPT_weights_v2Pro", "GPT_weights_v2ProPlus", "GPT_weights_v4",
                       "GPT_weights_v3", "GPT_weights_v2", "GPT_weights"]:
            path = os.path.join(repo, subdir)
            if os.path.isdir(path):
                ckpts = [f for f in os.listdir(path) if f.endswith(".ckpt")]
                if ckpts and not self.gs_gpt_edit.text():
                    self.gs_gpt_edit.setText(os.path.join(path, ckpts[0]))
                    self._append_log(f"自动发现 GPT 权重: {ckpts[0]}", "info")

        for subdir in ["SoVITS_weights_v2Pro", "SoVITS_weights_v2ProPlus", "SoVITS_weights_v4",
                       "SoVITS_weights_v3", "SoVITS_weights_v2", "SoVITS_weights"]:
            path = os.path.join(repo, subdir)
            if os.path.isdir(path):
                pths = [f for f in os.listdir(path) if f.endswith(".pth")]
                if pths and not self.gs_sovits_edit.text():
                    self.gs_sovits_edit.setText(os.path.join(path, pths[0]))
                    self._append_log(f"自动发现 SoVITS 权重: {pths[0]}", "info")

    def _choose_file(self, edit: QLineEdit, filter_str: str, file_mode: bool):
        start = edit.text() or ""
        if file_mode:
            p, _ = QFileDialog.getOpenFileName(self, "选择文件", start, filter_str)
            if p:
                edit.setText(p)
        else:
            d = QFileDialog.getExistingDirectory(self, "选择目录", start)
            if d:
                edit.setText(d)

    # ============================================================
    # CosyVoice 音色刷新
    # ============================================================

    def _refresh_cv_voices(self):
        self.cv_voice_combo.clear()
        try:
            from core.tts_client import TTSClient
            client = TTSClient()
            if client.is_alive():
                voices = client.get_voices()
                self.cv_voice_combo.addItems(voices)
                self._append_log(f"CosyVoice 发现 {len(voices)} 种音色", "info")
            else:
                self.cv_voice_combo.addItem("（服务未启动）")
        except Exception as e:
            self._append_log(f"刷新音色失败: {e}", "error")

    # ============================================================
    # 服务控制
    # ============================================================

    def _setup_status_listener(self):
        """监听两个 TTS 服务的状态变化 + 初始状态检查"""
        gs_mgr = cv_mgr = None
        try:
            from core.gpt_sovits_server_manager import get_gpt_sovits_server_manager
            gs_mgr = get_gpt_sovits_server_manager()
            gs_mgr.status_changed.connect(self._on_gs_status)
            gs_mgr.log_received.connect(lambda msg: self._append_log(msg))
        except Exception as e:
            self._append_log(f"GPT-SoVITS 状态监听未注册: {e}", "warn")

        try:
            from core.tts_server_manager import get_tts_server_manager
            cv_mgr = get_tts_server_manager()
            cv_mgr.status_changed.connect(self._on_cv_status)
            cv_mgr.log_received.connect(lambda msg: self._append_log(msg))
        except Exception as e:
            self._append_log(f"CosyVoice 状态监听未注册: {e}", "warn")

        # 立即同步当前引擎的状态（从 config 读，顶栏 combo_tts 已维护）
        engine = self.cfg.get("tts_engine", "gpt_sovits")
        mgr = gs_mgr if engine == "gpt_sovits" else cv_mgr
        if mgr:
            self._update_status(mgr.status)

    def _on_gs_status(self, status: str):
        if self._engine_idx() == 1:  # 当前引擎是 GS
            self._update_status(status)

    def _on_cv_status(self, status: str):
        if self._engine_idx() == 0:  # 当前引擎是 CV
            self._update_status(status)

    def _update_status(self, status: str):
        label_map = {"stopped": "未启动", "starting": "启动中", "running": "运行中", "error": "错误"}
        self.status_label.setText(f"● {label_map.get(status, status)}")
        self.status_label.setStyleSheet(self._status_style(status))
        self.btn_start.setEnabled(status in ("stopped", "error"))
        self.btn_stop.setEnabled(status in ("starting", "running"))

    def _start_service(self):
        engine = "cosyvoice" if self._engine_idx() == 0 else "gpt_sovits"
        self._save_config_silent()

        if engine == "gpt_sovits":
            from core.gpt_sovits_server_manager import get_gpt_sovits_server_manager
            mgr = get_gpt_sovits_server_manager()
            if not mgr.start_service():
                QMessageBox.critical(self, "启动失败", "GPT-SoVITS 启动失败，请查看日志")
            else:
                QTimer.singleShot(120000, lambda: self._check_start_timeout("gpt_sovits"))
        else:
            from core.tts_server_manager import get_tts_server_manager
            mgr = get_tts_server_manager()
            if not mgr.start_service():
                QMessageBox.critical(self, "启动失败", "CosyVoice 启动失败，请查看日志")
            else:
                QTimer.singleShot(120000, lambda: self._check_start_timeout("cosyvoice"))

    def _check_start_timeout(self, engine: str):
        """120s 后如果还在 starting 就弹窗提示"""
        if engine == "gpt_sovits":
            from core.gpt_sovits_server_manager import get_gpt_sovits_server_manager
            mgr = get_gpt_sovits_server_manager()
            name = "GPT-SoVITS-v2pro"
        else:
            from core.tts_server_manager import get_tts_server_manager
            mgr = get_tts_server_manager()
            name = "CosyVoice"
        if mgr.status in ("starting",):
            QMessageBox.warning(
                self, "启动超时",
                f"{name} 启动超过 120 秒仍未就绪。\n\n"
                f"请检查 {name} 配置是否正确，或查看语音系统页面的日志排查问题。")

    def _stop_service(self):
        engine = "cosyvoice" if self._engine_idx() == 0 else "gpt_sovits"
        if engine == "gpt_sovits":
            from core.gpt_sovits_server_manager import get_gpt_sovits_server_manager
            get_gpt_sovits_server_manager().stop_service()
        else:
            from core.tts_server_manager import get_tts_server_manager
            get_tts_server_manager().stop_service()

    def _save_config_silent(self):
        """静默保存（启动前用，不弹窗）"""
        from core.config import get_config_manager
        cfg = get_config_manager()
        cfg.set("tts_engine", "cosyvoice" if self._engine_idx() == 0 else "gpt_sovits")
        gs = {
            "repo_dir": self.gs_repo_edit.text().strip(),
            "device": self.gs_device_combo.currentText(),
            "port": int(self.gs_port_edit.text() or 9880),
            "sovits_model": self.gs_sovits_edit.text().strip(),
            "gpt_model": self.gs_gpt_edit.text().strip(),
            "default_refer_wav": self.gs_refer_wav_edit.text().strip(),
            "default_refer_text": self.gs_refer_text_edit.text().strip(),
            "default_refer_lang": self.gs_refer_lang_combo.currentText(),
            "default_text_language": self.gs_text_lang_combo.currentText(),
            "top_k": self.gs_topk_spin.value(),
            "top_p": self.gs_topp_spin.value(),
            "temperature": self.gs_temp_spin.value(),
            "speed": self.gs_speed_spin.value(),
            "cut_punc": self.gs_cutpunc_edit.text().strip(),
            "auto_start": self.btn_autostart.isChecked(),
        }
        for k, v in gs.items():
            cfg.set(f"gpt_sovits.{k}", v)
        cfg.set("tts.model_key", self.cv_model_combo.currentData() or "CosyVoice2-0.5B")
        cfg.set("tts.voice", self.cv_voice_combo.currentText().strip() or "中文女")
        cfg.set("tts.speed", self.cv_speed_spin.value())
        cfg.set("tts.max_read_chars", self.cv_max_chars_spin.value())
        cfg.set("tts.port", self.cv_port_spin.value())

    # ============================================================
    # 测试合成
    # ============================================================

    def _pick_test_ref(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择参考音频 (wav)", "", "音频文件 (*.wav *.mp3);;所有文件 (*)")
        if p:
            self.test_ref_edit.setText(p)

    def _test_synthesize(self):
        engine = "cosyvoice" if self._engine_idx() == 0 else "gpt_sovits"
        params = {}
        if engine == "gpt_sovits":
            params = {
                "text_language": self.gs_text_lang_combo.currentText(),
                "refer_lang": self.gs_refer_lang_combo.currentText(),
                "top_k": self.gs_topk_spin.value(),
                "top_p": self.gs_topp_spin.value(),
                "temperature": self.gs_temp_spin.value(),
                "speed": self.gs_speed_spin.value(),
            }
        else:
            params = {
                "voice": self.cv_voice_combo.currentText() if self.cv_voice_combo.count() else "",
                "speed": self.cv_speed_spin.value(),
                "ref_path": self.test_ref_edit.text().strip(),
            }

        # 先停掉正在播的
        self._media_player.stop()

        self._worker = TestSynthesizeWorker(engine, self.test_edit.text(), params)
        self._worker.finished.connect(self._on_test_done)
        self._worker.error.connect(self._on_test_error)
        self._worker.start()
        self.test_status.setText("⏳ 合成中...")
        self.test_status.setStyleSheet("color: #ff9800; font-size: 12px;")
        self.btn_test.setEnabled(False)
        self.btn_play.setEnabled(False)
        self.btn_open_file.setEnabled(False)

    def _on_test_done(self, path: str):
        self._last_wav = path
        self.test_status.setText(f"✅ 合成成功！正在播放...")
        self.test_status.setStyleSheet("color: #4caf50; font-size: 12px;")
        self.btn_test.setEnabled(True)
        self.btn_play.setEnabled(True)
        self.btn_open_file.setEnabled(True)
        self.btn_play.setText("⏹ 停止")
        self._append_log(f"测试合成完成: {path}", "info")
        # 自动播放
        try:
            self._media_player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
            self._media_player.play()
        except Exception as e:
            self._append_log(f"自动播放失败: {e}（可点击播放按钮）", "warn")

    def _on_test_error(self, err: str):
        self.test_status.setText(f"❌ 合成失败: {err}")
        self.test_status.setStyleSheet("color: #f44336; font-size: 12px;")
        self.btn_test.setEnabled(True)
        self._append_log(f"测试合成失败: {err}", "error")
        engine_name = "GPT-SoVITS-v2pro" if self._engine_idx() == 1 else "CosyVoice"
        QMessageBox.critical(
            self, "合成失败",
            f"合成失败，请检查 {engine_name} 配置。\n\n错误信息: {err}")

    # ---------- 音频播放器 ----------

    def _toggle_play(self):
        """切换播放/停止"""
        if self._media_player.state() == QMediaPlayer.PlayingState:
            self._media_player.stop()
        else:
            if self._last_wav and os.path.exists(self._last_wav):
                self._media_player.setMedia(QMediaContent(QUrl.fromLocalFile(self._last_wav)))
                self._media_player.play()
            else:
                QMessageBox.information(self, "提示", "请先合成一段测试语音")

    def _on_player_state_changed(self, state: int):
        """播放器状态变化 → 更新按钮文字"""
        if state == QMediaPlayer.PlayingState:
            self.btn_play.setText("⏹ 停止")
        else:
            self.btn_play.setText("▶️ 播放")

    def _open_wav_location(self):
        """在资源管理器中打开文件所在位置"""
        wav = getattr(self, "_last_wav", "")
        if wav and os.path.exists(wav):
            try:
                # /select, 打开文件夹并选中文件
                subprocess.Popen(['explorer', '/select,', os.path.normpath(wav)])
            except Exception as e:
                QMessageBox.warning(self, "打开失败", str(e))
        else:
            QMessageBox.information(self, "提示", "请先合成一段测试语音")

    # ============================================================
    # 日志
    # ============================================================

    def _append_log(self, msg: str, level: str = "info"):
        color_map = {"info": "#c0d8e8", "error": "#f44336", "success": "#4caf50", "warn": "#ff9800"}
        color = color_map.get(level, "#c0d8e8")
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f'<span style="color:#666">[{ts}]</span> <span style="color:{color}">{msg}</span>')
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ============================================================
    # 主题/透明度
    # ============================================================

    def apply_theme(self):
        """主题刷新（由 main.py 调用）"""
        self._append_log("主题已刷新", "info")

    def set_ui_opacity(self, opacity: float):
        """界面前端透明度（0-1），这里不需要额外处理，QWidget 默认继承父级"""
        pass

    def reload_theme(self):
        self.apply_theme()
