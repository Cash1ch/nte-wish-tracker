"""Виджеты вкладки «Стафф»: плитки персонажей, кубики, цвета гаранта."""

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPixmap
from PyQt6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

from ..catalog import (
    ARC_BANNER, DUGA_PREFIX, EVENT_BANNER, FIXED_RARITY, PITY_CHAR_HARD, RARITY_COLORS, REWARD_KINDS,
    STANDARD_BANNER,
)
from ..icons import make_pixmap
from .theme import add_glass_shadow, GLASS_SHADOWS
from .widgets import make_label, SmoothIconLabel


class RewardCard(QFrame):
    """Плашка награды: иконка + название + бейдж; цветная рамка по рангу
    (золотая для S, фиолетовая для A, синяя для B)."""

    def __init__(self, icon_size: int = 56):
        super().__init__()
        self.setObjectName("reward")
        self.icon_size = icon_size
        add_glass_shadow(self, blur=24, dy=6, alpha=80)  # НОВОЕ: тень стеклянной плашки

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)
        self.icon = SmoothIconLabel()   # ИЗМЕНЕНО: иконка со сглаживанием
        self.icon.setFixedSize(icon_size, icon_size)
        lay.addWidget(self.icon)

        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = make_label("—", "rewardTitle", wrap=True)
        self.badge = make_label(wrap=True)
        self.sub = make_label(name="hint", wrap=True)
        col.addStretch(1)
        for w in (self.title, self.badge, self.sub):
            col.addWidget(w)
        col.addStretch(1)
        lay.addLayout(col, 1)
        self.set_data(None, 3)

    def set_data(self, name, rarity: int, badge: str = "", sub: str = "", aliases=()):
        """ИЗМЕНЕНО: добавлен параметр aliases — синонимы для поиска иконки."""
        color_hex = RARITY_COLORS.get(rarity, RARITY_COLORS[3])
        c = QColor(color_hex)
        self.icon.setPixmap(make_pixmap(name or "?", rarity, self.icon_size, aliases))
        self.title.setText(name or "—")
        self.badge.setText(badge)
        self.badge.setStyleSheet(f"color: {color_hex}; font-weight: bold;")
        self.sub.setText(sub)
        # ИЗМЕНЕНО: стеклянная плашка — тонкая полупрозрачная рамка цвета ранга и
        # градиент «цвет ранга -> почти прозрачное стекло» вместо сплошной заливки
        self.setStyleSheet(
            "QFrame#reward { "
            f"border: 1px solid rgba({c.red()},{c.green()},{c.blue()},190); border-radius: 14px; "
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
            f"stop:0 rgba({c.red()},{c.green()},{c.blue()},70), stop:1 rgba(255,255,255,12)); }}"
        )



# ----------------------------------------------------------------------------
# НОВОЕ: помощники раздела «Стафф» — цвет гаранта, плитки персонажей, плашки кубиков
# ----------------------------------------------------------------------------
# ИЗМЕНЕНО: какие кубики показываются на подвкладке каждого пула (механика гачи):
# на ивентовом баннере выпадают только Твердые кубики, на стандартном — только Шулерские,
# с баннера «Дуги» кубики не падают вовсе. Старый общий «cube» виден, только если такие
# записи уже есть (чтобы не прятать старые данные).
CUBE_TITLES = {"solid_cube": "Твердые кубики", "trick_cube": "Шулерские кубики",
               "cube": "Кубики (старые записи)"}



POOL_CUBES = {
    EVENT_BANNER: ("solid_cube", "cube"),
    STANDARD_BANNER: ("trick_cube", "cube"),
    ARC_BANNER: (),
}



def roster_key(name) -> str:
    """Ключ сравнения имён персонажей: без регистра, «ё» = «е» (Блэкбёрд = блэкберд)."""
    return str(name or "").strip().lower().replace("ё", "е")



def pity_color(pulls: int, hard: int = PITY_CHAR_HARD) -> str:
    """Цвет числа круток на персонажа — плавный градиент по оттенку HSV:
    1 крутка — зелёный, середина гаранта — жёлтый/оранжевый, жёсткий гарант (hard,
    по умолчанию 90) — красный. Значения вне диапазона обрезаются."""
    t = 0.0 if hard <= 1 else (pulls - 1) / (hard - 1)
    t = min(max(t, 0.0), 1.0)
    return QColor.fromHsvF((1.0 - t) / 3.0, 0.80, 0.95).name()  # оттенок 120° -> 0°



def dim_pixmap(pm: QPixmap, opacity: float = 0.3) -> QPixmap:
    """Приглушённая копия иконки (для персонажей, которые ещё не выпадали)."""
    out = QPixmap(pm.size())
    out.setDevicePixelRatio(pm.devicePixelRatio())   # ИЗМЕНЕНО: сохраняем плотность пикселей
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing
                           | QPainter.RenderHint.SmoothPixmapTransform)
    painter.setOpacity(opacity)
    painter.drawPixmap(0, 0, pm)
    painter.end()
    return out



def clear_grid(grid):
    """Удаляет все виджеты из сетки (перед перестроением)."""
    while grid.count():
        wdg = grid.takeAt(0).widget()
        if wdg is not None:
            wdg.deleteLater()



def roster_counts(history: list, key: str) -> dict:
    """{(ранг, roster_key(имя)): [имя, сколько раз выпал]} — персонажи S и A ранга пула
    key из круток и бонусов. Заглушки («Персонаж», «Дуга»), дуги, предметы и кешбэк
    не учитываются."""
    counts = {}
    for e in history:
        if e["banner"] != key or e["kind"] not in ("main", "bonus") or e["rarity"] not in (4, 5):
            continue
        name = e["name"] or ""
        if name in ("Персонаж", "Дуга") or name.startswith(DUGA_PREFIX):
            continue
        slot = counts.setdefault((e["rarity"], roster_key(name)), [name, 0])
        slot[1] += 1
    return counts



def arc_roster_counts(history: list) -> dict:
    counts = {}
    for e in history:
        if e["banner"] != ARC_BANNER or e["kind"] not in ("main", "bonus") \
                or e["rarity"] not in (4, 5):
            continue
        name = e["name"] or ""
        if not name.startswith(DUGA_PREFIX):
            continue
        slot = counts.setdefault((e["rarity"], roster_key(name)), [name, 0])
        slot[1] += 1
    return counts



def add_text_outline(lbl: QLabel, blur: int = 7, alpha: int = 245):
    """НОВОЕ: тёмный ореол вокруг текста (нулевое смещение, высокая непрозрачность) —
    контраст на тёмном и светлом фоне плитки."""
    fx = QGraphicsDropShadowEffect(lbl)
    fx.setBlurRadius(blur)
    fx.setOffset(0, 0)
    fx.setColor(QColor(0, 0, 0, alpha))
    lbl.setGraphicsEffect(fx)



class CharTile(QFrame):
    """Плитка персонажа: иконка, имя и крупное число под ней (цвет задаётся снаружи).
    ИЗМЕНЕНО: иконка крупнее (ICON_SIZE), рамка тонкая (1 px), вместо толстой обводки —
    мягкое неоновое свечение (QGraphicsDropShadowEffect) цвета ранга вокруг иконки."""
    WIDTH = 108
    ICON_SIZE = 76          # было 56
    GLOW_PAD = 10           # поле вокруг иконки под свечение (чтобы не обрезалось и не лезло на текст)
    GLOW_BLUR = 22

    def __init__(self, name, rarity, value, color, tooltip="", aliases=(), dim=False,
                 label=None, event=False):
        super().__init__()
        self.setObjectName("tile")
        self.setFixedWidth(self.WIDTH)
        self.setToolTip(tooltip)
        if event:
            self.setStyleSheet(
                "QFrame#tile { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                "stop:0 rgba(255, 193, 7, 62), stop:0.55 rgba(120, 90, 30, 70), "
                "stop:1 rgba(255, 160, 0, 34)); "
                "border: 2px solid rgba(255, 213, 79, 215); border-radius: 14px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 8, 6, 10)
        lay.setSpacing(4)

        box = self.ICON_SIZE + 2 * self.GLOW_PAD
        icon = SmoothIconLabel()   # иконка со сглаживанием
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(box, box)
        pm = make_pixmap(name, rarity, self.ICON_SIZE, aliases, thin=True)
        icon.setPixmap(dim_pixmap(pm) if dim else pm)
        if GLASS_SHADOWS:
            glow = QGraphicsDropShadowEffect(icon)
            glow.setBlurRadius(self.GLOW_BLUR)
            glow.setOffset(0, 0)
            gc_ = QColor(RARITY_COLORS.get(rarity, RARITY_COLORS[3]))
            gc_.setAlpha(45 if dim else 170)
            glow.setColor(gc_)
            icon.setGraphicsEffect(glow)

        title = make_label(label or name, "tileName")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # длинное имя не должно раздвигать фиксированную плитку
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        avail = self.WIDTH - 14
        text = label or name
        if label:
            title.setWordWrap(True)
        size = 13                                   # ИЗМЕНЕНО: крупнее и жирнее (было 11 px)
        while size > 9:
            font = QFont(title.font())
            font.setPixelSize(size)
            font.setBold(True)
            metrics = QFontMetricsF(font)
            if label:
                rect = metrics.boundingRect(QRectF(0, 0, avail, 1000),
                                            int(Qt.TextFlag.TextWordWrap), text)
                words_ok = all(metrics.horizontalAdvance(w) <= avail for w in text.split())
                if words_ok and rect.height() <= metrics.lineSpacing() * 2.05:
                    break
            elif metrics.horizontalAdvance(text) <= avail:
                break
            size -= 1
        font = QFont(title.font())
        font.setPixelSize(size)
        font.setBold(True)
        metrics = QFontMetricsF(font)
        if not label:                               # одна строка: длинное имя — с многоточием
            title.setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight, avail))
        name_color = "#c9cde0" if dim else "#ffffff"
        title.setStyleSheet(f"font-size: {size}px; font-weight: bold; color: {name_color};")
        lines = 2 if label else 1
        title.setFixedHeight(int(metrics.lineSpacing() * lines * 1.1) + 6)
        add_text_outline(title)

        number = make_label(value, "tileValue")
        number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        number.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: bold;")
        number.setFixedHeight(30)
        add_text_outline(number, blur=8)

        lay.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(2)
        lay.addWidget(title)
        lay.addSpacing(2)
        lay.addWidget(number)



class DiceChip(QFrame):
    """Компактная плашка кубиков: маленькая иконка + «Название: N шт.»."""

    def __init__(self, kind: str, title: str):
        super().__init__()
        self.kind, self.title = kind, title
        self.setObjectName("chip")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 12, 4)
        lay.setSpacing(6)
        self.icon = SmoothIconLabel()   # ИЗМЕНЕНО: иконка со сглаживанием
        self.icon.setFixedSize(22, 22)
        self.text = make_label("", "chipText")
        lay.addWidget(self.icon)
        lay.addWidget(self.text)

    def set_count(self, qty: int):
        # иконка берётся при каждом обновлении — «Перечитать иконки» подхватывается сразу
        label = REWARD_KINDS[self.kind]
        self.icon.setPixmap(make_pixmap(label, FIXED_RARITY[self.kind], 22, (self.kind, label)))
        self.text.setText(f"{self.title}: {qty} шт.")
        if self.kind == "cube":  # старые записи: плашка нужна, только если они есть
            self.setVisible(qty > 0)
