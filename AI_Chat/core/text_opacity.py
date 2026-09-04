"""文字透明度：把所有控件样式表里的前景色统一改写为带 alpha 的 rgba。

原理：QSS 无法被全局规则覆盖局部样式，因此遍历所有 widget，
用 QColor 解析每条 `color:` 声明并按目标 alpha 重写（不动 background-color 等）。
"""
import re

from PyQt5.QtGui import QColor

# 只匹配前景色声明（避免误伤 background-color / border-color / -webkit 等）
_COLOR_DECL_RE = re.compile(r"(?<![\w-])color\s*:\s*([^;\"']+)", re.IGNORECASE)
_FUNC_COLOR_RE = re.compile(r"^(rgba?)\s*\(([^)]*)\)$", re.IGNORECASE)


def _parse_color(color_str: str):
    """解析颜色 → (r, g, b, a 0-1)；失败返回 None。兼容 #hex / 英文名 / rgb() / rgba()"""
    s = color_str.strip()
    c = QColor(s)
    if c.isValid():
        r, g, b, a = c.getRgb()
        return r, g, b, a / 255.0
    m = _FUNC_COLOR_RE.match(s)
    if m:
        parts = [p.strip() for p in m.group(2).split(",")]
        if len(parts) >= 3:
            try:
                rgb = []
                for p in parts[:3]:
                    rgb.append(int(float(p)) if not p.endswith("%")
                               else round(float(p[:-1]) / 100 * 255))
                a = float(parts[3]) if len(parts) > 3 else 1.0
                return rgb[0], rgb[1], rgb[2], max(0.0, min(1.0, a))
            except (ValueError, IndexError):
                return None
    return None


def with_alpha(color_str: str, alpha: float) -> str:
    """把任意 Qt 颜色字符串（#hex / rgb() / rgba() / 英文名）转为带 alpha 的 rgba 文本"""
    alpha = max(0.0, min(1.0, float(alpha)))
    parsed = _parse_color(color_str)
    if parsed is None:
        return color_str
    r, g, b, a = parsed
    return f"rgba({r},{g},{b},{alpha * a:.3f})"


def effective_text_alpha() -> float:
    """补偿界面前端透明度后的文字 css alpha。

    前端层（QGraphicsOpacityEffect）会把整层内容乘以 ui_opacity，
    这里把「文字透明度」滑条视为最终效果：css_alpha = t / ui_opacity（可 >1，渲染时封顶 1）。
    例：前端 50%（ui_opacity=0.5）时滑条 10% → css 0.2 → 最终 0.1，与滑条一致；
        滑条 100% → css 2.0 → 封顶 1 → 最终 0.5（前端层允许的最大值，即 1/n）。
    """
    from core.config import get_config_manager
    theme = get_config_manager().get("theme", {})
    t = max(0, min(100, theme.get("text_opacity", 100))) / 100.0
    n = max(0, min(100, theme.get("ui_transparency", 50))) / 100.0
    ui_opacity = 1.0 - n
    if ui_opacity <= 0.0:
        return 1.0  # 前端完全隐藏时文字不可见，css alpha 无意义，取 1 防除零
    return t / ui_opacity


def apply_text_opacity(alpha: float) -> int:
    """把 alpha 应用到现有全部控件样式的文字色，返回改动的控件数。
    以控件缓存的原样式为基线改写，重复调用不会连乘 alpha；
    若样式在其他地方被更新（与上次改写结果不同），自动以新样式为新基线。"""
    alpha = float(alpha)  # 可 >1（前端透明度补偿），with_alpha 内部会封顶到 1
    from PyQt5.QtWidgets import QApplication

    changed = 0
    for w in QApplication.allWidgets():
        ss = w.styleSheet()
        if not ss:
            continue
        base = w.property("_to_base")
        applied = w.property("_to_applied")
        if not isinstance(base, str) or (isinstance(applied, str) and ss != applied):
            base = ss  # 首次处理，或样式已被外部更新
        if not _COLOR_DECL_RE.search(base):
            continue

        def _sub(m):
            return f"color: {with_alpha(m.group(1), alpha)}"

        new_ss = _COLOR_DECL_RE.sub(_sub, base)
        w.setProperty("_to_base", base)
        w.setProperty("_to_applied", new_ss)
        if new_ss != ss:
            w.setStyleSheet(new_ss)
            changed += 1
    return changed
