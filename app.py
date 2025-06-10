import sys
import os
import tempfile
import mss
import keyboard
import ollama
import easyocr
from ctypes import windll
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QPushButton, QTextEdit, QSystemTrayIcon, QMenu,
    QSlider, QLabel, QFrame, QPlainTextEdit, QSplitter
)
from PyQt6.QtCore import Qt, QPoint, QRect, QRegularExpression
from PyQt6.QtCore import Qt, QPoint, QRect
from PyQt6.QtGui import (
    QIcon, QAction, QPalette, QColor, 
    QTextCharFormat, QSyntaxHighlighter, 
    QTextCursor, QFontMetrics, QFont
)

WDA_NONE = 0
WDA_MONITOR = 1
WDA_EXCLUDEFROMCAPTURE = 0x11  # Новый флаг для Windows 10+

class CodeHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules = []

        # Форматы для разных элементов кода
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

        # Строки
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#CE9178"))
        self.highlighting_rules.append(
            (r'"[^"\\]*(\\.[^"\\]*)*"', string_format)
        )
        self.highlighting_rules.append(
            (r"'[^'\\]*(\\.[^'\\]*)*'", string_format)
        )

        # Комментарии
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#6A9955"))
        self.highlighting_rules.append(
            (r"#[^\n]*", comment_format)
        )

        # Числа
        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#B5CEA8"))
        self.highlighting_rules.append(
            (r"\b\d+\b", number_format)
        )

        # Функции
        function_format = QTextCharFormat()
        function_format.setForeground(QColor("#DCDCAA"))
        self.highlighting_rules.append(
            (r"\b[A-Za-z0-9_]+(?=\()", function_format)
        )

    def highlightBlock(self, text):
        for pattern, format in self.highlighting_rules:
            regex = QRegularExpression(pattern)
            iterator = regex.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), format)

class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_editor()
        
    def setup_editor(self):
        # Настройка шрифта
        font = QFont("Consolas", 12)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        
        # Настройка отступов
        metrics = QFontMetrics(font)
        self.setTabStopDistance(4 * metrics.horizontalAdvance(' '))
        
        # Подсветка текущей строки
        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1E1E1E;
                color: #D4D4D4;
                border: none;
                selection-background-color: #264F78;
                selection-color: #FFFFFF;
            }
        """)
        
        # Добавляем подсветку синтаксиса
        self.highlighter = CodeHighlighter(self.document())

class ModernFrame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            ModernFrame {
                background-color: rgba(30, 30, 30, 0.97);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 10px;
            }
        """)

class ModernButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet("""
            QPushButton {
                background-color: rgba(60, 60, 60, 0.8);
                color: white;
                border: none;
                padding: 10px;
                border-radius: 5px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: rgba(80, 80, 80, 0.9);
            }
            QPushButton:pressed {
                background-color: rgba(40, 40, 40, 0.9);
            }
        """)

class ScreenshotApp(QMainWindow):
    def __init__(self):
        super().__init__()
        # Скрываем окно из панели задач
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.chat_history = []
        self.reader = easyocr.Reader(['en', 'ru'])
        self.initUI()
        self.exclude_from_capture()

    def initUI(self):
        central_widget = ModernFrame()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # Настройка прозрачности
        opacity_label = QLabel("Прозрачность")
        opacity_label.setStyleSheet("color: white; font-size: 13px;")
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid rgba(255, 255, 255, 0.1);
                height: 4px;
                background: rgba(60, 60, 60, 0.8);
                margin: 0px;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: white;
                border: none;
                width: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }
        """)
        self.opacity_slider.setRange(20, 100)
        self.opacity_slider.setValue(90)
        self.opacity_slider.valueChanged.connect(self.change_opacity)

        # Создаем сплиттер для разделения задачи и решения
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background: rgba(255, 255, 255, 0.1);
                height: 2px;
            }
        """)

        # Редактор для задачи
        self.task_edit = CodeEditor()
        self.task_edit.setPlaceholderText("Условие задачи")
        self.task_edit.setMinimumHeight(100)

        # Редактор для решения
        self.solution_edit = CodeEditor()
        self.solution_edit.setPlaceholderText("Решение")
        self.solution_edit.setMinimumHeight(200)

        # Добавляем редакторы в сплиттер
        splitter.addWidget(self.task_edit)
        splitter.addWidget(self.solution_edit)

        # Кнопки
        screenshot_btn = ModernButton("📷 Сделать скриншот")
        solve_btn = ModernButton("🔍 Решить задачу")
        clear_btn = ModernButton("🗑️ Очистить контекст")

        screenshot_btn.clicked.connect(self.take_screenshot)
        solve_btn.clicked.connect(self.solve_task)
        clear_btn.clicked.connect(self.clear_context)

        # Добавляем виджеты в layout
        layout.addWidget(opacity_label)
        layout.addWidget(self.opacity_slider)
        layout.addWidget(splitter)
        layout.addWidget(screenshot_btn)
        layout.addWidget(solve_btn)
        layout.addWidget(clear_btn)

        # Системный трей
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("icon.png"))
        tray_menu = QMenu()
        tray_menu.setStyleSheet("""
            QMenu {
                background-color: rgba(30, 30, 30, 0.97);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 5px;
                padding: 5px;
            }
            QMenu::item:selected {
                background-color: rgba(60, 60, 60, 0.8);
            }
        """)
        
        show_action = QAction("Показать", self)
        quit_action = QAction("Выход", self)
        show_action.triggered.connect(self.show)
        quit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(show_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

        keyboard.add_hotkey('ctrl+shift+s', self.take_screenshot)

        self.setGeometry(100, 100, 600, 800)
        self.setWindowTitle('Screenshot Assistant')

    def exclude_from_capture(self):
        """Исключаем окно из захвата экрана"""
        hwnd = int(self.winId())
        
        # Пробуем использовать современный метод для Windows 10+
        try:
            windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        except Exception as e:
            print(f"WDA_EXCLUDEFROMCAPTURE не поддерживается: {e}")
            # Используем старый метод как запасной вариант
            windll.user32.SetWindowDisplayAffinity(hwnd, WDA_MONITOR)

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
                    self.solution_edit.setPlainText("ℹ️ В скриншоте не обнаружено кодовой задачи")
            except Exception as e:
                self.solution_edit.setPlainText(f"⚠️ Ошибка при распознавании текста: {e}")
            finally:
                if was_visible:
                    self.show()
                try:
                    os.remove(path)
                except OSError:
                    pass

    def solve_task(self):
        task = self.task_edit.toPlainText().strip()
        if not task:
            self.solution_edit.setPlainText("⚠️ Введите условие задачи")
            return
        try:
            response = ollama.chat(
                model='qwen2.5-coder:14b',
                messages=[{
                    'role': 'user',
                    'content': f"""Реши следующую задачу по программированию.
Дай только код решения с минимальными комментариями:
{task}"""
                }]
            )
            solution = response['message']['content']
            self.solution_edit.setPlainText(solution)
            self.chat_history.append({"task": task, "solution": solution})
        except Exception as e:
            self.solution_edit.setPlainText(f"⚠️ Ошибка: {e}")

    def clear_context(self):
        self.task_edit.clear()
        self.solution_edit.clear()
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
    sys.exit(app.exec())