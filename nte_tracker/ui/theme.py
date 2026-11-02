"""Тема «стекло»: стили, тени, фон окна."""

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPixmap, QRadialGradient
from PyQt6.QtWidgets import (
    QGraphicsBlurEffect, QGraphicsDropShadowEffect, QGraphicsPixmapItem, QGraphicsScene, QGroupBox, QWidget,
)

from ..catalog import ICON_DIR_NAMES
from ..paths import search_roots


# ----------------------------------------------------------------------------
# НОВОЕ: тёмная тема в стиле «стекло» (Glassmorphism)
# ----------------------------------------------------------------------------
# Принципы:
#   * все обычные виджеты ПРОЗРАЧНЫ (QWidget { background: transparent }), поэтому
#     сквозь них виден градиентный фон окна (MainWindow.paintEvent);
#   * «стеклянные» панели (вкладки, группы, карточки, таблицы, поля) — полупрозрачная
#     белая/тёмная заливка rgba(...) + тонкая светлая рамка rgba(255,255,255,40)
#     + скругление 12–16 px;
#   * всплывающие окна (диалоги, меню, выпадающие списки, календарь, подсказки) остаются
#     НЕПРОЗРАЧНЫМИ — иначе текст стал бы нечитаемым на фоне рабочего стола.
# Размытия фона QSS не умеет, поэтому «матовость» имитируется градиентом, лёгким
# «бликом» (светлый градиент слева-сверху) и яркими пятнами света на фоне окна.
# Тени задаются в коде: add_glass_shadow() / apply_glass_shadows().
STYLE = """
QWidget { background: transparent; color: #e6e6ea; font-size: 13px; }
QMainWindow, QDialog { background-color: #0d0f1d; }
QScrollArea { border: none; background: transparent; }

/* --- непрозрачные всплывающие элементы --- */
QToolTip { background-color: #1b1e30; color: #e6e6ea; border: 1px solid rgba(255, 255, 255, 60);
           padding: 4px 6px; }
QMenu { background-color: #1b1e30; border: 1px solid rgba(255, 255, 255, 50); padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 6px; }
QMenu::item:selected { background-color: rgba(255, 215, 64, 60); }
QCalendarWidget, QCalendarWidget QWidget { background-color: #1b1e30; }
QCalendarWidget QAbstractItemView { selection-background-color: rgba(255, 215, 64, 70); }
QListView { background-color: #1b1e30; border: 1px solid rgba(255, 255, 255, 50); }  /* подсказка названий */
QStatusBar { background-color: rgba(255, 255, 255, 10); border-top: 1px solid rgba(255, 255, 255, 30); }

/* --- вкладки --- */
QTabWidget::pane { background-color: rgba(255, 255, 255, 10); border: 1px solid rgba(255, 255, 255, 40);
                   border-radius: 16px; top: -1px; }
QTabBar::tab { background: rgba(255, 255, 255, 12); padding: 9px 20px;
               border: 1px solid rgba(255, 255, 255, 30); border-bottom: none;
               border-top-left-radius: 12px; border-top-right-radius: 12px;
               margin-right: 3px; color: #a8adbb; }
QTabBar::tab:hover { background: rgba(255, 255, 255, 24); color: #e6e6ea; }
QTabBar::tab:selected { background: rgba(255, 255, 255, 32); color: #ffd740;
                        border-color: rgba(255, 255, 255, 60); }

/* --- кнопки --- */
QPushButton { background-color: rgba(255, 255, 255, 22); border: 1px solid rgba(255, 255, 255, 55);
              border-radius: 10px; padding: 8px 16px; }
QPushButton:hover { background-color: rgba(255, 255, 255, 40); border-color: #ffd740; }
QPushButton:pressed { background-color: rgba(255, 255, 255, 12); }
QPushButton:disabled { color: #6c7080; background-color: rgba(255, 255, 255, 8);
                       border-color: rgba(255, 255, 255, 25); }
QPushButton#primary { background-color: rgba(212, 160, 23, 220); color: #ffffff; font-weight: bold;
                      border: 1px solid rgba(255, 224, 130, 120); }
QPushButton#primary:hover { background-color: rgba(235, 183, 40, 240); }
QPushButton#danger { background-color: rgba(200, 50, 70, 170); border: 1px solid rgba(255, 130, 140, 90); }
QPushButton#danger:hover { background-color: rgba(225, 65, 85, 200); }
QToolButton { background-color: rgba(255, 255, 255, 22); border: 1px solid rgba(255, 255, 255, 55);
              border-radius: 10px; padding: 4px; }
QToolButton:hover { background-color: rgba(255, 255, 255, 40); border-color: #ffd740; }
QToolButton:pressed { background-color: rgba(255, 255, 255, 12); }
QToolButton:disabled { background-color: rgba(255, 255, 255, 8); border-color: rgba(255, 255, 255, 25); }

/* --- поля ввода (тёмное «стекло» — текст остаётся читаемым) --- */
QLineEdit, QComboBox, QDateTimeEdit, QSpinBox, QDoubleSpinBox { background-color: rgba(8, 10, 24, 120);
              border: 1px solid rgba(255, 255, 255, 40); border-radius: 10px;
              padding: 6px 10px; min-height: 20px; }
QLineEdit:focus, QComboBox:focus, QDateTimeEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #ffd740; }
QComboBox:disabled { color: #6c7080; }
QComboBox QAbstractItemView { background-color: #1b1e30; selection-background-color: rgba(255, 215, 64, 60);
              border: 1px solid rgba(255, 255, 255, 50); }
QPlainTextEdit { background-color: rgba(8, 10, 24, 110); border: 1px solid rgba(255, 255, 255, 40);
              border-radius: 12px; }
QListWidget { background-color: rgba(8, 10, 24, 110); border: 1px solid rgba(255, 255, 255, 40);
              border-radius: 12px; }
QListWidget::item { padding: 3px; border-radius: 6px; }
QListWidget::item:selected { background-color: rgba(255, 215, 64, 55); }
QCheckBox { background: transparent; spacing: 8px; }

/* --- таблицы --- */
QTableWidget { background-color: rgba(8, 10, 24, 100); gridline-color: rgba(255, 255, 255, 18);
               border: 1px solid rgba(255, 255, 255, 40); border-radius: 12px;
               selection-background-color: rgba(255, 215, 64, 55); }
QTableCornerButton::section { background: transparent; border: none; }
QHeaderView::section { background-color: rgba(255, 255, 255, 22); color: #d4d8e4; padding: 7px; border: none;
                       border-right: 1px solid rgba(255, 255, 255, 20); font-weight: bold; }

/* --- контейнеры и плитки --- */
QGroupBox { background-color: rgba(255, 255, 255, 15); border: 1px solid rgba(255, 255, 255, 40);
            border-radius: 16px; margin-top: 14px; padding: 12px 10px 10px 10px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; color: #ffd740; }
QFrame#card { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                  stop:0 rgba(255, 255, 255, 36), stop:1 rgba(255, 255, 255, 10));
              border: 1px solid rgba(255, 255, 255, 45); border-radius: 14px; }
/* --- СТЕКЛЯННЫЕ верхние карточки вкладки «Стафф» (make_stat_card) --- */
QFrame#statCard { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                      stop:0 rgba(255, 255, 255, 46), stop:1 rgba(255, 255, 255, 12));
                  border: 1px solid rgba(255, 255, 255, 64);
                  border-top: 1px solid rgba(255, 255, 255, 120);
                  border-radius: 12px; }
QLabel#statTitle { color: #c6cadb; font-size: 13px; font-weight: 600; }
QLabel#statValue { font-size: 34px; font-weight: bold; }
QLabel { background: transparent; }
QLabel#cardTitle { color: #b4b9c9; font-size: 12px; }
QLabel#cardValue { color: #ffd740; font-size: 24px; font-weight: bold; }
QLabel#pity4Value { color: #e2adf0; font-size: 15px; font-weight: bold; }
QLabel#rewardTitle { font-size: 14px; font-weight: bold; }
QLabel#hint { color: #9498aa; }
QLabel#musicValue { color: #b4b9c9; font-size: 12px; }

/* --- плитки персонажей и плашки кубиков (вкладка «Стафф») --- */
QFrame#tile { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                  stop:0 rgba(255, 255, 255, 30), stop:1 rgba(255, 255, 255, 8));
              border: 1px solid rgba(255, 255, 255, 26); border-radius: 14px; }
QLabel#tileName { color: #ffffff; font-size: 13px; font-weight: bold; }
QLabel#tileValue { font-size: 22px; font-weight: bold; }
QFrame#chip { background-color: rgba(255, 255, 255, 18); border: 1px solid rgba(255, 255, 255, 45);
              border-radius: 10px; }
QLabel#chipText { color: #e6e6ea; font-size: 12px; font-weight: normal; }

/* --- полосы прогресса, прокрутка, ползунки --- */
QProgressBar { background-color: rgba(255, 255, 255, 18); border: 1px solid rgba(255, 255, 255, 40);
               border-radius: 5px; }
QProgressBar::chunk { background-color: #b66cff; border-radius: 4px; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: rgba(255, 255, 255, 55); border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: rgba(255, 255, 255, 90); }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: rgba(255, 255, 255, 55); border-radius: 5px; min-width: 24px; }
QScrollBar::handle:horizontal:hover { background: rgba(255, 255, 255, 90); }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSlider::groove:horizontal { height: 4px; background: rgba(255, 255, 255, 40); border-radius: 2px; }
QSlider::sub-page:horizontal { background: #d4a017; border-radius: 2px; }
QSlider::handle:horizontal { background: #ffd740; width: 12px; height: 12px;
                             margin: -5px 0; border-radius: 6px; }
QSlider::handle:horizontal:hover { background: #ffe58a; }
QSlider::groove:horizontal:disabled { background: rgba(255, 255, 255, 20); }
QSlider::sub-page:horizontal:disabled { background: rgba(255, 255, 255, 40); }
QSlider::handle:horizontal:disabled { background: #5a5f70; }
"""



BAR_NORMAL = ""



BAR_SOFT = "QProgressBar::chunk { background-color: #ff9800; border-radius: 4px; }"



BAR_HARD = "QProgressBar::chunk { background-color: #e53935; border-radius: 4px; }"



# ----------------------------------------------------------------------------
# НОВОЕ: помощники стиля «стекло» — тени и фон окна
# ----------------------------------------------------------------------------
GLASS_SHADOWS = True  # False — отключить тени (если нужна максимальная скорость отрисовки)



def add_glass_shadow(widget: QWidget, blur: int = 32, dy: int = 8, alpha: int = 90):
    """Мягкая тень под «стеклянной» плиткой (эффект парения).
    Один QGraphicsEffect нельзя делить между виджетами — под каждый создаётся свой."""
    if not GLASS_SHADOWS:
        return
    fx = QGraphicsDropShadowEffect(widget)
    fx.setBlurRadius(blur)
    fx.setOffset(0, dy)
    fx.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(fx)



def apply_glass_shadows(root: QWidget):
    """Навешивает тени на все контейнеры QGroupBox внутри root.
    Карточки счётчиков (make_card) и плашки наград (RewardCard) получают тень сами."""
    for box in root.findChildren(QGroupBox):
        add_glass_shadow(box)



# ----------------------------------------------------------------------------
# НОВОЕ: пользовательский фон приложения (размытое «матовое стекло»)
# ----------------------------------------------------------------------------
BACKGROUND_NAME = "background"                          # assets/background.png | .jpg ...



BACKGROUND_EXTS = (".png", ".jpg", ".jpeg", ".webp")    # порядок = приоритет



BACKGROUND_BLUR_RADIUS = 28.0                           # сила размытия (пиксели рабочей копии)



BACKGROUND_WORK_SIDE = 960                              # размытие делается на копии до 960 px



BACKGROUND_OVERLAY = QColor(15, 15, 25, 191)            # rgba(15, 15, 25, 0.75)



_BG_STATE = {"loaded": False, "pm": None}               # кэш размытой картинки



_STYLE_STATE = {"bg": None}                             # какой стиль сейчас применён



# Доп. стиль, когда есть картинка: полупрозрачные «стёкла» чуть плотнее и темнее, чтобы
# текст оставался чётким и контрастным на любом фоне (правила переопределяют STYLE).
STYLE_ON_BACKGROUND = """
QFrame#statCard { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                      stop:0 rgba(60, 66, 104, 150), stop:1 rgba(22, 24, 48, 130));
                  border: 1px solid rgba(255, 255, 255, 72);
                  border-top: 1px solid rgba(255, 255, 255, 130); border-radius: 12px; }
QTabWidget::pane { background-color: rgba(10, 12, 28, 95); }
QGroupBox { background-color: rgba(12, 14, 30, 125); border: 1px solid rgba(255, 255, 255, 50); }
QFrame#card { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                  stop:0 rgba(46, 50, 82, 165), stop:1 rgba(20, 22, 44, 150)); }
QFrame#tile { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                  stop:0 rgba(44, 48, 78, 160), stop:1 rgba(18, 20, 40, 145)); }
QFrame#chip { background-color: rgba(12, 14, 30, 150); }
QTabBar::tab { background: rgba(14, 16, 34, 170); }
QTabBar::tab:selected { background: rgba(52, 56, 92, 205); }
QLineEdit, QComboBox, QDateTimeEdit, QSpinBox, QDoubleSpinBox { background-color: rgba(8, 10, 24, 175); }
QPlainTextEdit, QListWidget { background-color: rgba(8, 10, 24, 175); }
QTableWidget { background-color: rgba(8, 10, 24, 175); }
QHeaderView::section { background-color: rgba(40, 44, 74, 215); }
QProgressBar { background-color: rgba(8, 10, 24, 150); }
QStatusBar { background-color: rgba(8, 10, 24, 150); }
"""



def find_background_path():
    """Ищет assets/background.png (затем .jpg, .jpeg, .webp) рядом со скриптом и рядом с
    базой данных (также в icons/). Возвращает Path или None."""
    roots = search_roots()
    for ext in BACKGROUND_EXTS:
        for root in roots:
            for base in ICON_DIR_NAMES:
                path = root / base / f"{BACKGROUND_NAME}{ext}"
                if path.is_file():
                    return path
    return None



def _blur_pixmap(src: QPixmap, radius: float) -> QPixmap:
    """Сильное гауссово размытие картинки через QGraphicsBlurEffect (один раз, с кэшем).
    Работа идёт на уменьшенной копии (быстро — на экране размытие всё равно не видно
    деталей). Копия предварительно расширяется на поле pad, а после размытия поле
    срезается — иначе по краям появилась бы тёмная «рамка» от затухания эффекта."""
    work = src
    if max(src.width(), src.height()) > BACKGROUND_WORK_SIDE:
        work = src.scaled(BACKGROUND_WORK_SIDE, BACKGROUND_WORK_SIDE,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
    w, h = work.width(), work.height()
    pad = int(radius * 2) + 2
    pw, ph = w + 2 * pad, h + 2 * pad
    padded = work.scaled(pw, ph, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    blurred = None
    try:
        scene = QGraphicsScene()
        item = QGraphicsPixmapItem(padded)
        fx = QGraphicsBlurEffect()
        fx.setBlurRadius(radius)
        fx.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
        item.setGraphicsEffect(fx)
        scene.addItem(item)
        img = QImage(pw, ph, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing
                               | QPainter.RenderHint.SmoothPixmapTransform)
        area = QRectF(0, 0, pw, ph)
        scene.render(painter, area, area)
        painter.end()
        blurred = QPixmap.fromImage(img)
    except Exception:  # noqa: BLE001 — размытие не должно ронять приложение
        blurred = None
    if blurred is None or blurred.isNull():
        # запасной вариант: сильное уменьшение и плавное растяжение даёт похожее размытие
        tiny = padded.scaled(max(1, pw // 16), max(1, ph // 16),
                             Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        blurred = tiny.scaled(pw, ph, Qt.AspectRatioMode.IgnoreAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
    return blurred.copy(pad, pad, w, h)



def get_background_pixmap():
    """Размытый фон (QPixmap) или None, если файла нет / он не открылся. Результат
    кэшируется; сбрасывается функцией reset_background_cache() (кнопка «Перечитать иконки»)."""
    if not _BG_STATE["loaded"]:
        _BG_STATE["loaded"], _BG_STATE["pm"] = True, None
        path = find_background_path()
        if path is not None:
            try:
                src = QPixmap(str(path))
                if not src.isNull():
                    _BG_STATE["pm"] = _blur_pixmap(src, BACKGROUND_BLUR_RADIUS)
            except Exception:  # noqa: BLE001
                _BG_STATE["pm"] = None
    return _BG_STATE["pm"]



def reset_background_cache():
    _BG_STATE["loaded"], _BG_STATE["pm"] = False, None



def apply_app_style(app):
    """Применяет STYLE (+ STYLE_ON_BACKGROUND, если есть картинка фона). Таблица стилей
    переустанавливается только при смене состояния «фон есть / нет» — это дорогая операция."""
    has_bg = find_background_path() is not None
    if _STYLE_STATE["bg"] == has_bg:
        return
    _STYLE_STATE["bg"] = has_bg
    app.setStyleSheet(STYLE + (STYLE_ON_BACKGROUND if has_bg else ""))



def draw_glass_backdrop(p: QPainter, rect):
    """Фон, сквозь который «просвечивает» стекло. ИЗМЕНЕНО: если есть картинка
    assets/background.*, рисуется она — размытая, по принципу «cover» (пропорции
    сохраняются, лишнее обрезается по центру) — и поверх тёмная подложка
    rgba(15, 15, 25, 0.75). Иначе — прежний градиент с цветными пятнами.
    Рисуется в paintEvent главного окна и при съёмке скриншота (чтобы снимок не получился
    прозрачным)."""
    bg = get_background_pixmap()
    if bg is not None:
        p.setRenderHints(QPainter.RenderHint.Antialiasing
                         | QPainter.RenderHint.SmoothPixmapTransform
                         | QPainter.RenderHint.LosslessImageRendering)
        w, h = rect.width(), rect.height()
        if w > 0 and h > 0:
            scale = max(w / bg.width(), h / bg.height())      # «cover»
            sw, sh = w / scale, h / scale                      # видимая часть картинки
            source = QRectF((bg.width() - sw) / 2, (bg.height() - sh) / 2, sw, sh)
            p.drawPixmap(QRectF(rect), bg, source)
        p.fillRect(rect, BACKGROUND_OVERLAY)                   # матовая тёмная подложка
        return
    # --- запасной фон: тёмный диагональный градиент и три размытых цветных пятна
    # (фиолетовое, золотое, бирюзовое)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    w, h = rect.width(), rect.height()
    base = QLinearGradient(0, 0, w, h)
    base.setColorAt(0.0, QColor(13, 15, 33))
    base.setColorAt(0.55, QColor(22, 16, 48))
    base.setColorAt(1.0, QColor(8, 26, 42))
    p.fillRect(rect, QBrush(base))
    # (x, y — доли ширины/высоты, радиус — доля большей стороны, цвет пятна)
    for fx, fy, fr, color in ((0.10, 0.12, 0.55, QColor(120, 80, 255, 95)),
                              (0.92, 0.30, 0.45, QColor(255, 190, 60, 55)),
                              (0.45, 1.00, 0.60, QColor(0, 170, 200, 70))):
        radius = max(w, h) * fr
        glow = QRadialGradient(w * fx, h * fy, radius)
        c0, c1 = QColor(color), QColor(color)
        c1.setAlpha(0)
        glow.setColorAt(0.0, c0)
        glow.setColorAt(1.0, c1)
        p.fillRect(rect, QBrush(glow))
