"""Вспомогательные функции верстки и карточки наград."""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QHeaderView, QLabel,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QStyle, QTableWidget, QVBoxLayout, QWidget,
)

from ..catalog import rank_letter, RARITIES, RARITY_COLORS
from ..icons import make_pixmap
from .theme import add_glass_shadow, BAR_HARD, BAR_NORMAL, BAR_SOFT, GLASS_SHADOWS


# ----------------------------------------------------------------------------
# Вспомогательные функции верстки
# ----------------------------------------------------------------------------
class SmoothIconLabel(QLabel):
    """НОВОЕ: QLabel для иконок и картинок с высоким качеством отрисовки.
    Обычный QLabel рисует pixmap без сглаживания: если размер картинки не совпал с
    размером виджета (смена монитора, дробный масштаб экрана), получается пикселизация.
    Здесь pixmap рисуется с Antialiasing + SmoothPixmapTransform, с учётом devicePixelRatio
    и выравнивания (alignment) метки. Если pixmap нет — работает как обычный QLabel."""

    def paintEvent(self, event):
        pm = self.pixmap()
        if pm is None or pm.isNull():
            super().paintEvent(event)
            return
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing
                         | QPainter.RenderHint.SmoothPixmapTransform)
        size = pm.deviceIndependentSize().toSize()      # логический размер картинки
        rect = QStyle.alignedRect(self.layoutDirection(), self.alignment(),
                                  size, self.contentsRect())
        p.drawPixmap(rect, pm)
        p.end()



def make_label(text: str = "", name: str = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl



def make_button(text: str, slot, name: str = None) -> QPushButton:
    btn = QPushButton(text)
    if name:
        btn.setObjectName(name)
    btn.clicked.connect(slot)
    return btn



def make_combo(items) -> QComboBox:
    """items — список пар (текст, данные)."""
    combo = QComboBox()
    for label, data in items:
        combo.addItem(label, data)
    return combo



def make_rank_combo(any_label: str = None) -> QComboBox:
    """Список рангов S / A / B (буквы окрашены в цвет ранга: S золотой, A фиолетовый,
    B синий). any_label — добавляет первым пунктом «любой» (для фильтров);
    без него по умолчанию выбран B."""
    combo = QComboBox()
    if any_label:
        combo.addItem(any_label, None)
    for r in sorted(RARITIES, reverse=True):
        combo.addItem(rank_letter(r), r)
        combo.setItemData(combo.count() - 1, QBrush(QColor(RARITY_COLORS[r])),
                          Qt.ItemDataRole.ForegroundRole)
    if not any_label:
        combo.setCurrentIndex(combo.findData(3))
    return combo



def scroll_page():
    """Страница с вертикальной прокруткой. Возвращает (виджет страницы, её layout)."""
    outer = QWidget()
    outer_l = QVBoxLayout(outer)
    outer_l.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # НОВОЕ: только вертикальная прокрутка
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.verticalScrollBar().setSingleStep(32)                               # плавнее шаг колеса мыши
    outer_l.addWidget(scroll)
    inner = QWidget()
    scroll.setWidget(inner)
    return outer, QVBoxLayout(inner)



def make_table(headers: list, stretch_col: int) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setIconSize(QSize(40, 40))
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    t.setShowGrid(False)
    t.verticalHeader().setVisible(False)
    hdr = t.horizontalHeader()
    hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    hdr.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
    t.setColumnWidth(0, 56)
    return t



def make_card(title: str):
    frame = QFrame()
    frame.setObjectName("card")
    add_glass_shadow(frame, blur=24, dy=6, alpha=80)  # НОВОЕ: тень стеклянной карточки
    lay = QVBoxLayout(frame)
    value = make_label("—", "cardValue")
    lay.addWidget(make_label(title, "cardTitle"))
    lay.addWidget(value)
    return frame, value



def make_stat_card(title: str, accent: str = "#ffd740"):
    """ОБНОВЛЕНО: верхняя карточка статистики в стиле «матовое стекло» (glassmorphism):
    полупрозрачный градиентный фон, скругление 12 px, светлая рамка и мягкое цветное
    свечение под цвет акцента. Заголовок — мелкий, значение — крупное и чёткое.
    Возвращает (рамка, подпись значения). Рамка растягивается по ширине (Expanding)."""
    frame = QFrame()
    frame.setObjectName("statCard")
    frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    frame.setMinimumHeight(92)
    if GLASS_SHADOWS:                                   # цветное свечение рамки
        glow = QGraphicsDropShadowEffect(frame)
        glow.setBlurRadius(30)
        glow.setOffset(0, 0)
        color = QColor(accent)
        color.setAlpha(95)
        glow.setColor(color)
        frame.setGraphicsEffect(glow)
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(4)
    title_lbl = make_label(title, "statTitle")
    value = make_label("—", "statValue")
    value.setStyleSheet(f"color: {accent};")            # цвет значения — акцент карточки
    for lbl in (title_lbl, value):
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(title_lbl)
    lay.addWidget(value)
    return frame, value



def make_last_row():
    """Строка «иконка + название». Возвращает (виджет, иконка, текст)."""
    wdg = QWidget()
    h = QHBoxLayout(wdg)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    icon, text = SmoothIconLabel(), QLabel("—")   # ИЗМЕНЕНО: иконка со сглаживанием
    icon.setFixedSize(30, 30)
    h.addWidget(icon)
    h.addWidget(text, 1)
    return wdg, icon, text



def make_pity_widget():
    """Текст + полоса прогресса. Возвращает (виджет, подпись, полоса)."""
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(4)
    lbl = make_label("0", "pity4Value")
    bar = QProgressBar()
    bar.setTextVisible(False)
    bar.setFixedHeight(10)
    v.addWidget(lbl)
    v.addWidget(bar)
    return box, lbl, bar



def set_bar(bar: QProgressBar, value: int, maximum: int, soft=None, hard=None):
    """Заполняет полосу гаранта; цвет: фиолетовый → оранжевый (мягкий) → красный (жёсткий)."""
    bar.setRange(0, maximum)
    bar.setValue(min(max(value, 0), maximum))
    if hard is not None and value >= hard:
        bar.setStyleSheet(BAR_HARD)
    elif soft is not None and value >= soft:
        bar.setStyleSheet(BAR_SOFT)
    else:
        bar.setStyleSheet(BAR_NORMAL)



def set_last(icon_lbl: QLabel, text_lbl: QLabel, row):
    if row is None:
        icon_lbl.clear()
        text_lbl.setText("—")
    else:
        icon_lbl.setPixmap(make_pixmap(row["name"], row["rarity"], 30))
        text_lbl.setText(row["name"])
