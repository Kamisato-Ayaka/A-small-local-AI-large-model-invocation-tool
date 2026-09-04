"""
代码编辑器 - 带语法高亮和行号
"""
import sys
from PyQt5.QtWidgets import QTextEdit, QWidget, QHBoxLayout, QTextBrowser
from PyQt5.QtGui import (
    QFont, QFontMetrics, QPainter, QColor, QTextFormat,
    QSyntaxHighlighter, QTextCharFormat, QTextCursor
)
from PyQt5.QtCore import Qt, QRect, QRegExp, QSize


# 深色主题颜色
THEME = {
    "bg": "#1e1e1e",
    "fg": "#d4d4d4",
    "line_number_bg": "#1e1e1e",
    "line_number_fg": "#858585",
    "line_number_border": "#333333",
    "current_line": "#2a2d2e",
    "selection": "#264f78",
    "keyword": "#569cd6",
    "string": "#ce9178",
    "comment": "#6a9955",
    "number": "#b5cea8",
    "function": "#dcdcaa",
    "class": "#4ec9b0",
    "decorator": "#dcdcaa",
    "operator": "#d4d4d4",
    "builtin": "#4fc1ff",
}


class PythonHighlighter(QSyntaxHighlighter):
    """Python 语法高亮"""

    def __init__(self, document):
        super().__init__(document)
        self.highlighting_rules = []

        # 关键字
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor(THEME["keyword"]))
        keyword_format.setFontWeight(QFont.Bold)
        keywords = [
            "def", "class", "return", "if", "elif", "else", "for", "while",
            "break", "continue", "pass", "import", "from", "as", "try", "except",
            "finally", "raise", "with", "lambda", "yield", "global", "nonlocal",
            "in", "is", "not", "and", "or", "True", "False", "None", "self",
            "async", "await", "del", "assert", "print", "exec",
        ]
        for word in keywords:
            pattern = QRegExp(f"\\b{word}\\b")
            self.highlighting_rules.append((pattern, keyword_format))

        # 字符串
        string_format = QTextCharFormat()
        string_format.setForeground(QColor(THEME["string"]))
        string_patterns = [
            QRegExp(r'"[^"\\]*(\\.[^"\\]*)*"'),
            QRegExp(r"'[^'\\]*(\\.[^'\\]*)*'"),
            QRegExp(r'"""[\s\S]*?"""'),
            QRegExp(r"'''[\s\S]*?'''"),
        ]
        for pattern in string_patterns:
            self.highlighting_rules.append((pattern, string_format))

        # 注释
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor(THEME["comment"]))
        comment_format.setFontItalic(True)
        self.highlighting_rules.append((QRegExp(r"#[^\n]*"), comment_format))

        # 数字
        number_format = QTextCharFormat()
        number_format.setForeground(QColor(THEME["number"]))
        self.highlighting_rules.append((QRegExp(r"\b\d+\.?\d*\b"), number_format))

        # 函数定义
        function_format = QTextCharFormat()
        function_format.setForeground(QColor(THEME["function"]))
        function_format.setFontWeight(QFont.Bold)
        self.highlighting_rules.append((QRegExp(r"\bdef\s+(\w+)"), function_format))

        # 类定义
        class_format = QTextCharFormat()
        class_format.setForeground(QColor(THEME["class"]))
        class_format.setFontWeight(QFont.Bold)
        self.highlighting_rules.append((QRegExp(r"\bclass\s+(\w+)"), class_format))

        # 装饰器
        decorator_format = QTextCharFormat()
        decorator_format.setForeground(QColor(THEME["decorator"]))
        self.highlighting_rules.append((QRegExp(r"@\w+"), decorator_format))

        # 内置函数
        builtin_format = QTextCharFormat()
        builtin_format.setForeground(QColor(THEME["builtin"]))
        builtins = [
            "print", "len", "range", "str", "int", "float", "list", "dict",
            "set", "tuple", "bool", "type", "isinstance", "enumerate", "zip",
            "map", "filter", "sorted", "reversed", "sum", "min", "max",
            "abs", "round", "open", "input", "format",
        ]
        for word in builtins:
            pattern = QRegExp(f"\\b{word}(?=\\()")
            self.highlighting_rules.append((pattern, builtin_format))

    def highlightBlock(self, text):
        for pattern, char_format in self.highlighting_rules:
            expression = QRegExp(pattern)
            index = expression.indexIn(text)
            while index >= 0:
                length = expression.matchedLength()
                self.setFormat(index, length, char_format)
                index = expression.indexIn(text, index + length)


class LineNumberArea(QWidget):
    """行号区域"""

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)


class CodeEditor(QTextEdit):
    """代码编辑器"""

    def __init__(self, parent=None):
        super().__init__(parent)

        # 设置字体
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.Monospace)
        self.setFont(font)
        self.setTabStopWidth(4 * QFontMetrics(font).width(' '))

        # 设置样式
        self.setStyleSheet(f"""
            QTextEdit {{
                background-color: {THEME['bg']};
                color: {THEME['fg']};
                border: none;
                padding: 0;
                selection-background-color: {THEME['selection']};
            }}
        """)

        # 行号区域
        self.line_number_area = LineNumberArea(self)

        # 布局
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.line_number_area)

        # 语法高亮
        self.highlighter = PythonHighlighter(self.document())

        # 信号连接
        self.document().blockCountChanged.connect(self.update_line_number_area_width)
        self.cursorPositionChanged.connect(self.highlight_current_line)

        # 初始化
        self.update_line_number_area_width(0)
        self.highlight_current_line()

        # 换行模式
        self.setLineWrapMode(QTextEdit.NoWrap)

    def line_number_area_width(self):
        """计算行号区域宽度"""
        digits = 1
        max_value = max(1, self.document().blockCount())
        while max_value >= 10:
            max_value /= 10
            digits += 1
        space = 10 + digits * QFontMetrics(self.font()).width('9')
        return space

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)
        self.line_number_area.setFixedWidth(self.line_number_area_width())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )

    def line_number_area_paint_event(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor(THEME["line_number_bg"]))

        # 右边框
        painter.setPen(QColor(THEME["line_number_border"]))
        painter.drawLine(event.rect().right(), 0, event.rect().right(), event.rect().bottom())

        # QTextEdit 的行号绘制：通过滚动条位置计算
        font_metrics = QFontMetrics(self.font())
        line_height = font_metrics.height()

        # 获取视口的滚动偏移
        scrollbar = self.verticalScrollBar()
        scroll_val = scrollbar.value() if scrollbar else 0

        # 计算可见区域的顶部和底部对应的行
        # 使用 cursorForPosition 获取可见的起始行
        viewport = self.viewport()

        # 遍历可见行
        # 用文档块的方式，但通过 translate 来处理滚动
        block = self.document().begin()
        block_number = 0

        # 获取文档布局
        doc_layout = self.document().documentLayout()

        while block.isValid():
            block_number += 1
            # 获取块的边界矩形（相对于文档）
            rect = doc_layout.blockBoundingRect(block)
            # 转换为视口坐标：减去滚动偏移
            y = rect.top() - scroll_val

            if y + rect.height() >= 0 and y <= event.rect().bottom():
                number = str(block_number)
                painter.setPen(QColor(THEME["line_number_fg"]))
                painter.drawText(
                    0, int(y), self.line_number_area.width() - 5,
                    line_height,
                    Qt.AlignRight | Qt.AlignVCenter, number
                )

            block = block.next()

            # 优化：超出视口底部后停止
            if rect.top() - scroll_val > event.rect().bottom():
                break

    def highlight_current_line(self):
        """高亮当前行"""
        extra_selections = []

        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            line_color = QColor(THEME["current_line"])
            selection.format.setBackground(line_color)
            selection.format.setProperty(QTextFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra_selections.append(selection)

        self.setExtraSelections(extra_selections)

    def keyPressEvent(self, event):
        # Tab 键插入空格
        if event.key() == Qt.Key_Tab:
            cursor = self.textCursor()
            cursor.insertText("    ")
            return

        # 括号自动补全
        if event.text() in ['(', '[', '{', '"', "'"]:
            pairs = {'(': ')', '[': ']', '{': '}', '"': '"', "'": "'"}
            cursor = self.textCursor()
            cursor.insertText(event.text() + pairs[event.text()])
            cursor.movePosition(QTextCursor.Left)
            self.setTextCursor(cursor)
            return

        # Ctrl+S 保存（由父窗口处理）
        super().keyPressEvent(event)

    def set_language(self, language):
        """设置语言（切换高亮）"""
        if language == "python":
            self.highlighter = PythonHighlighter(self.document())
        # 可扩展其他语言
