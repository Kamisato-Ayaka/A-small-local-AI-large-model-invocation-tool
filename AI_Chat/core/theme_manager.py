"""
主题管理器 - 应用背景图片和主题颜色
"""
import os
from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtCore import Qt

from core.config import get_config_manager


def apply_editor_theme(widget, scroll_area=None):
    """应用编辑器区域主题（背景图片+颜色）"""
    cfg = get_config_manager()
    theme = cfg.get("theme", {})
    bg_image = theme.get("editor_bg_image", "")
    bg_color = theme.get("editor_bg_color", "#1e1e1e")
    opacity = theme.get("bg_opacity", 100)

    if bg_image and os.path.exists(bg_image):
        # 使用背景图片
        bg_style = f"""
            background-image: url("{bg_image.replace(os.sep, '/')}");
            background-position: center;
            background-repeat: no-repeat;
            background-clip: border;
        """
        # 通过 QSS 设置背景
        widget.setStyleSheet(f"""
            QWidget {{
                background-color: rgba{_hex_to_rgba(bg_color, opacity)};
                {bg_style}
            }}
        """)
        if scroll_area:
            scroll_area.setStyleSheet(f"""
                QScrollArea {{
                    background-color: rgba{_hex_to_rgba(bg_color, opacity)};
                    border: none;
                }}
                QScrollBar:vertical {{
                    background: transparent;
                    width: 10px;
                }}
                QScrollBar::handle:vertical {{
                    background: rgba(255,255,255,0.2);
                    border-radius: 5px;
                    min-height: 30px;
                    border: 2px solid transparent;
                    background-clip: padding-box;
                }}
            """)
    else:
        # 纯色背景
        widget.setStyleSheet(f"""
            QWidget {{
                background-color: {bg_color};
            }}
        """)


def apply_chat_theme(widget):
    """应用对话区域主题"""
    cfg = get_config_manager()
    theme = cfg.get("theme", {})
    bg_image = theme.get("chat_bg_image", "")
    bg_color = theme.get("chat_bg_color", "#252526")
    opacity = theme.get("bg_opacity", 100)

    if bg_image and os.path.exists(bg_image):
        widget.setStyleSheet(f"""
            QWidget#aiPanelRoot {{
                background-image: url("{bg_image.replace(os.sep, '/')}");
                background-position: center;
                background-repeat: no-repeat;
            }}
        """)
    else:
        widget.setStyleSheet(f"""
            QWidget#aiPanelRoot {{
                background-color: {bg_color};
            }}
        """)


def _hex_to_rgba(hex_color: str, opacity_percent: int) -> str:
    """将十六进制颜色和不透明度转为 rgba 字符串"""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    if len(hex_color) != 6:
        return "(30, 30, 30, 1.0)"
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    a = max(0.1, min(1.0, opacity_percent / 100.0))
    return f"({r}, {g}, {b}, {a})"


def get_accent_color() -> str:
    """获取强调色"""
    cfg = get_config_manager()
    return cfg.get("theme.accent_color", "#007acc")
