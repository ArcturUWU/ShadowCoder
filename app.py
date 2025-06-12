import sys
import os
import tempfile
import mss
import keyboard
import ollama
import easyocr
import re
import latex2mathml.converter
from ctypes import windll

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QPushButton, QPlainTextEdit, QSystemTrayIcon, QMenu,
    QSlider, QLabel, QFrame, QSplitter, QHBoxLayout
)
from PyQt6.QtCore import Qt, QPoint, QRegularExpression
from PyQt6.QtGui import (
    QIcon, QAction, QPalette, QColor,
    QTextCharFormat, QSyntaxHighlighter, QTextCursor,
    QFontMetrics, QFont
)
from PyQt6.QtWebEngineWidgets import QWebEngineView

WDA_NONE = 0
WDA_MONITOR = 1
WDA_EXCLUDEFROMCAPTURE = 0x11  # Новый флаг для Windows 10+

class CodeHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules = []

        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#569CD6"))
        keyword_format.setFontWeight(QFont.Weight.Bold)
        keywords = [
            "def", "class", "for", "while", "if", "else", "elif",
            "try", "except", "finally", "with", "as", "import",
            "from", "return", "yield", "break", "continue", "pass",
            "raise", "True", "False", "None", "and", "or", "not", "is"
        ]
        for word in keywords:
            self.highlighting_rules.append(
                (f"\\b{word}\\b", keyword_format)
            )

        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#CE9178"))
        self.highlighting_rules.append(
            (r'"[^"\\]*(\\.[^"\\]*)*"', string_format)
        )
        self.highlighting_rules.append(
            (r"'[^'\\]*(\\.[^'\\]*)*'", string_format)
        )

        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#6A9955"))
        self.highlighting_rules.append(
            (r"#[^\n]*", comment_format)
        )

        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#B5CEA8"))
        self.highlighting_rules.append(
            (r"\\b\\d+\\b", number_format)
        )

        function_format = QTextCharFormat()
        function_format.setForeground(QColor("#DCDCAA"))
        self.highlighting_rules.append(
            (r"[A-Za-z_][A-Za-z0-9_]*\s*(?=\()", function_format)
        )

    def highlightBlock(self, text):
        for pattern, fmt in self.highlighting_rules:
            regex = QRegularExpression(pattern)
            iterator = regex.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)

class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_editor()

    def setup_editor(self):
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        metrics = QFontMetrics(font)
        self.setTabStopDistance(4 * metrics.horizontalAdvance(' '))
        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: rgba(35, 35, 35, 0.95);
                color: #E0E0E0;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                padding: 8px;
                selection-background-color: #264F78;
                selection-color: #FFFFFF;
            }
        """)
        self.highlighter = CodeHighlighter(self.document())

class ModernFrame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            ModernFrame {
                background-color: rgba(25, 25, 25, 0.95);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
            }
        """)

class ModernButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet("""
            QPushButton {
                background-color: rgba(45, 45, 45, 0.9);
                color: #E0E0E0;
                border: none;
                padding: 8px 12px;
                border-radius: 6px;
                font-size: 12px;
                font-weight: 500;
                transition: background-color 0.2s;
            }
            QPushButton:hover {
                background-color: rgba(60, 60, 60, 0.95);
            }
            QPushButton:pressed {
                background-color: rgba(35, 35, 35, 0.95);
            }
        """)

class ModernTextBrowser(QWebEngineView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setStyleSheet("""
            QWebEngineView {
                background-color: rgba(35, 35, 35, 0.95);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
        """)

    def set_content(self, html_content: str):
        full_html = f"""
        <html>
        <head>
            <meta charset=\"utf-8\">
            <script src=\"https://polyfill.io/v3/polyfill.min.js?features=es6\"></script>
            <script>
            window.MathJax = {{
                tex: {{
                inlineMath: [['$', '$'], ['\\(', '\\)']],
                displayMath: [['$$','$$'], ['\\[','\\]']]
                }}
            }};
            </script>
            <script id=\"MathJax-script\" async src=\"https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js\"></script>
            <style>
                body {{
                    background-color: rgba(35, 35, 35, 0.95);
                    color: #E0E0E0;
                    font-family: 'Segoe UI', sans-serif;
                    padding: 12px;
                    margin: 0;
                    line-height: 1.5;
                    font-size: 13px;
                }}
                .math-display {{
                    text-align: center;
                    margin: 12px 0;
                    padding: 8px;
                    background: rgba(45, 45, 45, 0.5);
                    border-radius: 6px;
                    color: #E0E0E0;
                }}
                .math-inline {{
                    padding: 0 2px;
                    color: #E0E0E0;
                }}
                pre {{
                    background: rgba(45, 45, 45, 0.5);
                    padding: 12px;
                    border-radius: 6px;
                    margin: 8px 0;
                    overflow-x: auto;
                    border: 1px solid rgba(255, 255, 255, 0.08);
                }}
                code {{
                    font-family: 'Consolas', monospace;
                    font-size: 12px;
                    color: #E0E0E0;
                }}
                .keyword {{ color: #569CD6; font-weight: bold; }}
                .string {{ color: #CE9178; }}
                .comment {{ color: #6A9955; }}
                .number {{ color: #B5CEA8; }}
                .decorator {{ color: #DCDCAA; }}
                .class {{ color: #4EC9B0; }}
                .function {{ color: #DCDCAA; }}
                .operator {{ color: #D4D4D4; }}
                p {{
                    margin: 8px 0;
                    color: #E0E0E0;
                }}
                ul, ol {{
                    margin: 8px 0;
                    padding-left: 24px;
                    color: #E0E0E0;
                }}
                li {{
                    margin: 4px 0;
                    color: #E0E0E0;
                }}
                blockquote {{
                    border-left: 3px solid rgba(255, 255, 255, 0.1);
                    margin: 8px 0;
                    padding: 4px 12px;
                    background: rgba(45, 45, 45, 0.3);
                    border-radius: 0 6px 6px 0;
                    color: #E0E0E0;
                }}
                a {{
                    color: #569CD6;
                    text-decoration: none;
                }}
                a:hover {{
                    text-decoration: underline;
                }}
                h1, h2, h3, h4, h5, h6 {{
                    color: #E0E0E0;
                    margin: 12px 0 8px 0;
                }}
                table {{
                    border-collapse: collapse;
                    width: 100%;
                    margin: 8px 0;
                    background: rgba(45, 45, 45, 0.3);
                    border-radius: 6px;
                }}
                th, td {{
                    padding: 8px;
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    color: #E0E0E0;
                }}
                th {{
                    background: rgba(45, 45, 45, 0.5);
                }}
                strong {{
                    font-weight: bold;
                    color: #FFFFFF;
                }}
                ::-webkit-scrollbar {{
                    width: 8px;
                    height: 8px;
                }}
                ::-webkit-scrollbar-track {{
                    background: rgba(45, 45, 45, 0.3);
                    border-radius: 4px;
                }}
                ::-webkit-scrollbar-thumb {{
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 4px;
                }}
                ::-webkit-scrollbar-thumb:hover {{
                    background: rgba(255, 255, 255, 0.2);
                }}
            </style>
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """
        self.setHtml(full_html)

class ScreenshotApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.chat_history = []
        self.reader = easyocr.Reader(['en', 'ru'])
        self.exclude_from_capture()
        self.initUI()
        self.exclude_from_capture()

    def showEvent(self, event):
        super().showEvent(event)
        self.exclude_from_capture()
        
    def process_math_formulas(self, text):
        # Сначала обработаем переносы строк
        text = text.replace('---', '<hr style="border: none; border-top: 1px solid rgba(255, 255, 255, 0.1); margin: 12px 0;">')
        text = text.replace('👉', '<br>👉')
        
        # Обработаем жирный текст
        text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
        
        # Обработаем блочные формулы
        result = re.sub(
            r'\$\$(.*?)\$\$',
            r'<div class="math-display">$$\1$$</div>',
            text,
            flags=re.DOTALL
        )
        
        # Обработаем строчные формулы
        result = re.sub(
            r'(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)',
            r'<span class="math-inline">$\1$</span>',
            result
        )
        
        def format_code_block(match):
            lang = match.group(1).lower()
            code = match.group(2).strip()
            if lang in ['python', 'py', '']:
                return self._format_code('python', code)
            return f'<pre><code class="{lang}">{code}</code></pre>'
            
        result = re.sub(
            r'```(\w*)\n(.*?)```',
            format_code_block,
            result,
            flags=re.DOTALL
        )
        return result

    def _format_code(self, language, code):
        code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        patterns = [
            (r'\b(def|class|if|else|elif|for|while|try|except|finally|with|as|import|from|return|yield|break|continue|pass|raise|True|False|None|and|or|not|is|in)\b', 'keyword'),
            (r'"""[\s\S]*?"""|\'\'\'[\\s\\S]*?\'\'\'|"[^"\\\\]*(?:\\\\.[^"\\\\]*)*"|\'[^\'\\\\]*(?:\\\\.[^\'\\\\]*)*\'', 'string'),
            (r'#[^\n]*', 'comment'),
            (r'\b\d+\.?\d*\b', 'number'),
            (r'@\w+', 'decorator'),
            (r'\b[A-Z][A-Za-z0-9_]*\b', 'class'),
            (r'\b[a-z_][a-z0-9_]*(?=\s*\()', 'function'),
            (r'[+\-*/%=<>!&|^~]+', 'operator')
        ]
        tokens = []
        for pattern, token_type in patterns:
            for match in re.finditer(pattern, code):
                tokens.append((match.start(), match.end(), token_type, match.group(0)))
        tokens.sort()
        filtered_tokens = []
        last_end = 0
        for start, end, token_type, text in tokens:
            if start >= last_end:
                filtered_tokens.append((start, end, token_type, text))
                last_end = end
        result = []
        last_pos = 0
        for start, end, token_type, text in filtered_tokens:
            if start > last_pos:
                result.append(code[last_pos:start])
            result.append(f'<span class=\"{token_type}\">{text}</span>')
            last_pos = end
        if last_pos < len(code): result.append(code[last_pos:])
        highlighted_code = ''.join(result).replace('\n', '<br/>')
        return f'<pre><code class=\"python\">{highlighted_code}</code></pre>'

    def initUI(self):
        central_widget = ModernFrame()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Компактная панель управления
        control_panel = QWidget()
        control_layout = QHBoxLayout(control_panel)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(8)

        # Кнопки управления
        screenshot_btn = ModernButton("📷")
        solve_btn = ModernButton("🔍")
        clear_btn = ModernButton("🗑️")
        screenshot_btn.setToolTip("Сделать скриншот (Ctrl+Shift+S)")
        solve_btn.setToolTip("Решить задачу")
        clear_btn.setToolTip("Очистить")
        screenshot_btn.clicked.connect(self.take_screenshot)
        solve_btn.clicked.connect(self.solve_task)
        clear_btn.clicked.connect(self.clear_context)
        
        # Слайдер прозрачности
        opacity_label = QLabel("⚪")
        opacity_label.setStyleSheet("color: #E0E0E0; font-size: 12px;")
        opacity_label.setFixedWidth(20)
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(20, 100)
        self.opacity_slider.setValue(90)
        self.opacity_slider.setFixedWidth(80)
        self.opacity_slider.valueChanged.connect(self.change_opacity)
        self.opacity_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid rgba(255, 255, 255, 0.1);
                height: 4px;
                background: rgba(60, 60, 60, 0.8);
                margin: 2px 0;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #E0E0E0;
                border: none;
                width: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
        """)

        control_layout.addWidget(screenshot_btn)
        control_layout.addWidget(solve_btn)
        control_layout.addWidget(clear_btn)
        control_layout.addStretch()
        control_layout.addWidget(opacity_label)
        control_layout.addWidget(self.opacity_slider)

        # Основной контент
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        # Поле ввода задачи
        self.task_edit = CodeEditor()
        self.task_edit.setPlaceholderText("Введите условие задачи или сделайте скриншот...")
        self.task_edit.setMinimumHeight(60)
        self.task_edit.setMaximumHeight(100)

        # Поле решения
        self.solution_edit = ModernTextBrowser()
        self.solution_edit.setMinimumHeight(300)

        content_layout.addWidget(self.task_edit)
        content_layout.addWidget(self.solution_edit)

        # Добавляем все в основной layout
        layout.addWidget(control_panel)
        layout.addWidget(content_widget)

        # Устанавливаем размер окна
        self.setGeometry(100, 100, 600, 500)

        # Настройка системного трея
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("icon.png"))
        tray_menu = QMenu()
        show_action = QAction("Показать", self)
        quit_action = QAction("Выход", self)
        show_action.triggered.connect(self.show)
        quit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(show_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        
        keyboard.add_hotkey('ctrl+shift+s', self.take_screenshot)
        self.setWindowTitle('Interview Assistant')

    def exclude_from_capture(self):
        hwnd = int(self.winId())
        windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)


    def change_opacity(self, value):
        self.setWindowOpacity(value / 100.0)

    def take_screenshot(self):
        was_visible = self.isVisible()
        self.hide()
        QApplication.processEvents()
        with mss.mss() as sct:
            path = os.path.join(tempfile.gettempdir(), "temp_screenshot.png")
            sct.shot(output=path)
            try:
                results = self.reader.readtext(path)
                text = "\n".join(r[1] for r in results)
                if any(kw in text.lower() for kw in ('python','массив', 'массивы','код','class','def','for','while')):
                    self.task_edit.setPlainText(text)
                else:
                    self.solution_edit.set_content("ℹ️ В скриншоте не обнаружено кодовой задачи")
            except Exception:
                self.solution_edit.set_content("⚠️ Ошибка при распознавании текста")
            finally:
                if was_visible: self.show()
                try: os.remove(path)
                except OSError: pass

    def solve_task(self):
        task = self.task_edit.toPlainText().strip()
        if not task:
            self.solution_edit.set_content("⚠️ Введите условие задачи")
            return
        try:
            response = ollama.chat(
                model='qwen3:30b',
                messages=[
                    {'role': 'system', 'content': 
                     '''Ты - скрытый помощник соискателям на техническом собеседовании на русском языке. Все твои ответы на поставленные задачи сопровождай комментариями как это передать интервьюверу. Ты должен действовать по следующим правилам:
                    1) Если ты видишь задание - ты должен предложить кандидату решение и чёткий ответ и объяснение для интервьювера
                    2) Если ты видишь код без задания, значит ты должен step-by-step внести оптимизацию в алгоритм и выдать соискателю последовательный ответ, который он дает интервьюверу.
                    3) Если ты видишь теоретический вопрос - сделай развёрнутый ответ с комментариями о том, что должен сказать соискатель с формулами, объяснениями
                    4) Для формул используй:
                       - Для блочных формул: $$формула$$
                       - Для строчных формул внутри текста: $формула$
                    5) Если требуется написать код, чётко комментируй что и для чего ты пишешь
                    6) Чётко пиши соискателю что и в какой последовательности он должен говорить, используя 👉 для каждого шага
                    7) Используя какую-либо формулу, теорему или метод, всегда приводи соискателю краткое объяснение с формулами и как это преподнести интервьюверу.
                    8) При написании любого алгоритма - необходимо алгоритмическим языком простыми словами сначала описать, что он делает и его сложность
                    9) Важные заметки и предупреждения обрамляй в ❗️текст❗️
                    10) Код всегда оформляй в блоках ```python код ```
                    Твой итоговый ответ - это всегда руководство, где ты приводишь реплики для соискателя, последовательность озвучивания и код. Всё это то, что соискатель должен сказать интервьюверу'''},
                    {'role': 'user', 'content': task}
                ]
            )
            solution = response['message']['content'].split('</think>')[1]
            formatted = self.process_math_formulas(solution)
            self.solution_edit.set_content(formatted)
            self.chat_history.append({"task": task, "solution": solution})
        except Exception as e:
            self.solution_edit.set_content(f"⚠️ Ошибка: {e}")

    def clear_context(self):
        self.task_edit.clear()
        self.solution_edit.set_content("")
        self.chat_history.clear()

    def mousePressEvent(self, event):
        self.oldPos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        delta = QPoint(event.globalPosition().toPoint() - self.oldPos)
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.oldPos = event.globalPosition().toPoint()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    app.setPalette(palette)

    window = ScreenshotApp()
    window.show()
    window.exclude_from_capture()
    sys.exit(app.exec())
