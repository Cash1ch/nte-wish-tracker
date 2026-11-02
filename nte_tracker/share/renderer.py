"""Рендерер карточки «Поделиться» (QImage + QPainter)."""

import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF,
    QRadialGradient,
)

from ..catalog import ARC_BANNER, EVENT_BANNER, PITY_CHAR_HARD, RARITY_COLORS, STANDARD_BANNER
from ..icons import _initials, find_icon_path
from ..ui.staff_widgets import pity_color


# ----------------------------------------------------------------------------
# НОВОЕ: внутренний рендерер карточки «Поделиться» (ShareCardRenderer)
# ----------------------------------------------------------------------------
# Карточка рисуется целиком в памяти (QImage + QPainter) на холсте фиксированного размера
# по проектной сетке 3840x2160. Размеры окна, экрана, масштаб Windows и состояние окна
# (свёрнуто / обычное / во весь экран) на результат НЕ влияют: рендерер получает только
# данные (словарь), собранные функцией collect_share_data(), и ничего не снимает с экрана.
SHARE_CANVAS_4K = (3840, 2160)



SHARE_CANVAS_2K = (2560, 1440)



SHARE_CANVAS_SIZE = SHARE_CANVAS_4K          # 3840x2160 или SHARE_CANVAS_2K



SHARE_RECENT_LIMIT = 10                      # сколько последних S показывать внизу карточки



SHARE_DIR_NAME = "screenshots"               # папка для PNG-копий рядом с базой данных



SHARE_FONT_FAMILIES = ["Segoe UI", "Segoe UI Emoji", "Noto Sans", "Arial", "DejaVu Sans"]



SHARE_TOAST_TEXT = "Скриншот высокого качества скопирован в буфер обмена!"



SHARE_WATERMARK = "NTE Wish Tracker — Neverness to Everness"



SHARE_POOL_SHORT = {EVENT_BANNER: "Ивентовый", STANDARD_BANNER: "Стандартный", ARC_BANNER: "Дуга"}



SHARE_POOL_ACCENTS = {EVENT_BANNER: "#b66cff", STANDARD_BANNER: "#8ab4ff", ARC_BANNER: "#7be0a8"}



class ShareCardRenderer:
    """Автономный рендерер карточки статистики. Принимает словарь данных (см.
    collect_share_data) и рисует карточку на QImage Format_ARGB32 размера size.
    Все координаты заданы в проектной сетке DW x DH (3840x2160) и масштабируются
    одним коэффициентом painter.scale(), поэтому раскладка одинакова в 2K и 4K."""

    DW, DH = 3840, 2160                       # проектная сетка
    M = 110                                   # внешнее поле
    A_L = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    A_C = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
    A_R = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    MUTED = QColor(255, 255, 255, 185)
    GOLD = "#ffd740"

    def __init__(self, data: dict, size=SHARE_CANVAS_SIZE):
        self.data = data or {}
        self._pools_bottom = self.PANEL_TOP + self.PANEL_H
        self.width = max(640, int(size[0]))
        self.scale = self.width / self.DW
        self.height = round(self.DH * self.scale)
        self._img_cache = {}

    # ---------- главный метод ----------
    def render(self) -> QImage:
        image = QImage(self.width, self.height, QImage.Format.Format_ARGB32)
        image.fill(QColor(8, 10, 22))                 # непрозрачная основа
        p = QPainter(image)
        try:
            for hint in (QPainter.RenderHint.Antialiasing, QPainter.RenderHint.TextAntialiasing,
                         QPainter.RenderHint.SmoothPixmapTransform,
                         QPainter.RenderHint.LosslessImageRendering):
                p.setRenderHint(hint, True)
            p.scale(self.scale, self.scale)
            self._draw_background(p)
            self._draw_header(p)
            self._draw_pools(p)
            self._draw_recent(p)
            self._draw_footer(p)
        finally:
            p.end()
        dpm = round(96 * self.width / 1920 / 0.0254)  # метаданные плотности для PNG
        image.setDotsPerMeterX(dpm)
        image.setDotsPerMeterY(dpm)
        return image

    # ---------- примитивы ----------
    @staticmethod
    def _font(px, bold=False) -> QFont:
        f = QFont()
        f.setFamilies(SHARE_FONT_FAMILIES)
        f.setPixelSize(max(1, int(px)))
        f.setBold(bool(bold))
        f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        return f

    def _text(self, p, rect, text, px, color, bold=False, align=None, shadow=True, elide=True):
        rect = QRectF(rect)
        align = self.A_L if align is None else align
        font = self._font(px, bold)
        text = str(text)
        p.setFont(font)
        if elide:
            text = QFontMetricsF(font).elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
        if shadow:
            p.setPen(QColor(0, 0, 0, 170))
            p.drawText(rect.translated(px * 0.04, px * 0.05), int(align), text)
        p.setPen(QColor(color))
        p.drawText(rect, int(align), text)

    def _text_width(self, text, px, bold=False) -> float:
        return QFontMetricsF(self._font(px, bold)).horizontalAdvance(str(text))

    def _glass(self, p, rect, radius=44, depth=1.0, glow=None):
        """Стеклянная панель: мягкая тень, тёмная основа, белая заливка, блик, рамка."""
        rect = QRectF(rect)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(10, 0, -1):
            g = i * 5 * depth
            p.setBrush(QColor(0, 0, 0, 7))
            p.drawRoundedRect(rect.adjusted(-g, -g + 14 * depth, g, g + 14 * depth),
                              radius + g, radius + g)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.fillPath(path, QColor(10, 13, 28, 150))
        p.fillPath(path, QColor(255, 255, 255, 26))
        sheen = QLinearGradient(rect.topLeft(), rect.bottomRight())
        sheen.setColorAt(0.0, QColor(255, 255, 255, 56))
        sheen.setColorAt(0.4, QColor(255, 255, 255, 10))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(path, QBrush(sheen))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if glow is not None:
            c = QColor(glow)
            for i in range(5, 0, -1):
                c.setAlpha(14 + (5 - i) * 5)
                p.setPen(QPen(c, 2.5 + i * 4))
                p.drawRoundedRect(rect, radius, radius)
        p.setPen(QPen(QColor(255, 255, 255, 80), 2.5))
        p.drawRoundedRect(rect, radius, radius)
        p.restore()

    def _glow_border(self, p, rect, radius, color, width):
        """Свечение вокруг рамки: несколько полупрозрачных обводок убывающей ширины."""
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        c = QColor(color)
        for i in range(8, 0, -1):
            c.setAlpha(12 + (8 - i) * 5)
            pen = QPen(c, width + i * width * 1.1)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawRoundedRect(rect, radius, radius)
        p.restore()

    def _load_icon_image(self, name, aliases):
        key = (name, tuple(aliases))
        if key in self._img_cache:
            return self._img_cache[key]
        img = None
        try:
            path = find_icon_path(name, tuple(aliases)) if (name or aliases) else None
            if path is not None:
                loaded = QImage(str(path))
                if not loaded.isNull():
                    img = loaded
        except Exception:
            img = None
        self._img_cache[key] = img
        return img

    def _draw_cover(self, p, img: QImage, rect):
        """Картинка по принципу «cover»: пропорции сохраняются, лишнее обрезается по центру.
        Предварительное масштабирование до физического размера даёт резкий результат."""
        rect = QRectF(rect)
        tw = max(1, round(rect.width() * self.scale))
        th = max(1, round(rect.height() * self.scale))
        scaled = img.scaled(tw, th, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
        src = QRectF((scaled.width() - tw) / 2, (scaled.height() - th) / 2, tw, th)
        p.drawImage(rect, scaled, src)

    def _icon(self, p, rect, name, rarity, aliases=(), dim=False, glow=True):
        """Миниатюра персонажа / дуги / предмета: скругление, блик и светящаяся рамка цвета ранга."""
        rect = QRectF(rect)
        size = rect.width()
        radius = size * 0.22
        color = QColor(RARITY_COLORS.get(rarity, RARITY_COLORS[3]))
        border_w = max(3.0, size * 0.03)
        if glow and not dim:
            self._glow_border(p, rect.adjusted(border_w / 2, border_w / 2, -border_w / 2, -border_w / 2),
                              radius, color, border_w)
        p.save()
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.setClipPath(path)
        p.fillRect(rect, QColor(20, 23, 38, 235))
        if dim:
            p.setOpacity(0.32)
        img = self._load_icon_image(name, aliases)
        if img is not None:
            self._draw_cover(p, img, rect)
        else:
            tint = QColor(color)
            tint.setAlpha(70)
            p.fillRect(rect, tint)
            p.setFont(self._font(size * 0.38, True))
            p.setPen(color)
            p.drawText(rect, int(self.A_C), _initials(name or next(iter(aliases), "")))
        p.setOpacity(1.0)
        sheen = QLinearGradient(rect.topLeft(), rect.bottomRight())
        sheen.setColorAt(0.0, QColor(255, 255, 255, 70))
        sheen.setColorAt(0.45, QColor(255, 255, 255, 18))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(rect, QBrush(sheen))
        p.restore()
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        edge = QColor(color)
        edge.setAlpha(110 if dim else 235)
        p.setPen(QPen(edge, border_w))
        p.drawRoundedRect(rect.adjusted(border_w / 2, border_w / 2, -border_w / 2, -border_w / 2),
                          radius - border_w / 2, radius - border_w / 2)
        p.restore()

    # ---------- фон: тёмный город ----------
    def _draw_background(self, p):
        W, H = self.DW, self.DH
        full = QRectF(0, 0, W, H)
        base = QLinearGradient(0, 0, 0, H)
        base.setColorAt(0.0, QColor(9, 11, 30))
        base.setColorAt(0.45, QColor(26, 17, 60))
        base.setColorAt(0.80, QColor(18, 24, 66))
        base.setColorAt(1.0, QColor(6, 20, 36))
        p.fillRect(full, QBrush(base))
        for fx, fy, fr, color in ((0.10, 0.10, 0.50, QColor(120, 80, 255, 100)),
                                  (0.92, 0.28, 0.42, QColor(255, 190, 60, 60)),
                                  (0.50, 1.00, 0.55, QColor(0, 170, 200, 80))):
            glow = QRadialGradient(W * fx, H * fy, max(W, H) * fr)
            c0, c1 = QColor(color), QColor(color)
            c1.setAlpha(0)
            glow.setColorAt(0.0, c0)
            glow.setColorAt(1.0, c1)
            p.fillRect(full, QBrush(glow))
        rnd = random.Random(20261022)                 # фиксированное зерно: фон всегда одинаковый
        p.setPen(Qt.PenStyle.NoPen)
        for _ in range(260):                          # далёкие огни / звёзды в верхней части
            p.setBrush(QColor(255, 255, 255, rnd.randint(30, 120)))
            r = rnd.uniform(1.2, 3.4)
            p.drawEllipse(QPointF(rnd.uniform(0, W), rnd.uniform(0, H * 0.55)), r, r)
        # три слоя силуэтов зданий: (мин. высота, макс. высота, цвет, мин./макс. ширина, окна)
        layers = ((300, 820, QColor(30, 28, 70, 255), 90, 220, 0),
                  (240, 700, QColor(20, 20, 52, 255), 80, 200, 70),
                  (160, 520, QColor(12, 13, 34, 255), 70, 180, 110))
        for hmin, hmax, color, wmin, wmax, win_alpha in layers:
            x = -40
            while x < W:
                bw, bh = rnd.randint(wmin, wmax), rnd.randint(hmin, hmax)
                p.fillRect(QRectF(x, H - bh, bw, bh), color)
                if rnd.random() < 0.25:               # антенна на крыше
                    p.fillRect(QRectF(x + bw / 2 - 3, H - bh - 70, 6, 70), color)
                if win_alpha:
                    for row in range(int(bh // 46)):
                        for col in range(int(bw // 34)):
                            if rnd.random() < 0.18:
                                warm = rnd.random() < 0.6
                                wc = QColor(255, 200, 110, win_alpha) if warm \
                                    else QColor(110, 220, 255, win_alpha)
                                p.fillRect(QRectF(x + 14 + col * 34, H - bh + 20 + row * 46, 14, 20), wc)
                x += bw + rnd.randint(0, 14)
        vignette = QRadialGradient(W / 2, H / 2, W * 0.72)
        vignette.setColorAt(0.55, QColor(0, 0, 0, 0))
        vignette.setColorAt(1.0, QColor(0, 0, 0, 150))
        p.fillRect(full, QBrush(vignette))
        p.fillRect(full, QColor(6, 8, 20, 70))        # лёгкое затемнение под текст

    # ---------- логотип и шапка ----------
    def _draw_logo(self, p, rect):
        rect = QRectF(rect)
        c, r = rect.center(), rect.width() / 2
        poly = QPolygonF([QPointF(c.x() + r * math.cos(math.radians(-90 + 60 * k)),
                                  c.y() + r * math.sin(math.radians(-90 + 60 * k)))
                          for k in range(6)])
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(8, 0, -1):
            p.setPen(QPen(QColor(150, 110, 255, 10 + (8 - i) * 4), i * 6))
            p.drawPolygon(poly)
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, QColor(130, 90, 255))
        grad.setColorAt(1.0, QColor(0, 200, 230))
        p.setPen(QPen(QColor(255, 255, 255, 210), 5))
        p.setBrush(QBrush(grad))
        p.drawPolygon(poly)
        inner = QPolygonF([QPointF(c.x() + r * 0.78 * math.cos(math.radians(-90 + 60 * k)),
                                   c.y() + r * 0.78 * math.sin(math.radians(-90 + 60 * k)))
                           for k in range(6)])
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 90), 2.5))
        p.drawPolygon(inner)
        p.restore()
        self._text(p, rect, "NTE", r * 0.62, "#ffffff", True, self.A_C)

    def _draw_header(self, p):
        M, W = self.M, self.DW
        self._draw_logo(p, QRectF(M, 70, 190, 190))
        tx = M + 190 + 50
        self._text(p, QRectF(tx, 62, 2000, 124), "Статистика круток", 108, "#ffffff", True)
        self._text(p, QRectF(tx, 188, 2200, 64), "Neverness to Everness", 42, self.MUTED)
        right = W - M
        profile = self.data.get("profile") or ""
        if profile:
            text = f"Профиль: {profile}"
            w = min(1500.0, self._text_width(text, 60, True) + 100)
            pill = QRectF(right - w, 74, w, 108)
            self._glass(p, pill, radius=54, depth=0.5, glow=self.GOLD)
            self._text(p, pill, text, 60, self.GOLD, True, self.A_C)

    # ---------- панели пулов ----------
    PANEL_TOP, PANEL_H, PANEL_GAP, PANEL_PAD = 320, 1120, 50, 50

    def _draw_pools(self, p):
        pools = self.data.get("pools") or []
        if not pools:
            return
        n = len(pools)
        pw = (self.DW - 2 * self.M - self.PANEL_GAP * (n - 1)) / n
        ph = self.PANEL_H if (n > 1 or any(pl.get("roster") for pl in pools)) else 640
        self._pools_bottom = self.PANEL_TOP + ph
        for i, pool in enumerate(pools):
            rect = QRectF(self.M + i * (pw + self.PANEL_GAP), self.PANEL_TOP, pw, ph)
            self._draw_pool(p, rect, pool)

    def _draw_pool(self, p, r, pool):
        accent = QColor(pool.get("accent", "#8ab4ff"))
        self._glass(p, r, glow=accent)
        pad = self.PANEL_PAD
        x0, w = r.left() + pad, r.width() - 2 * pad
        top = r.top()
        # заголовок с цветной планкой
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawRoundedRect(QRectF(x0, top + 44, 14, 78), 7, 7)
        p.restore()
        self._text(p, QRectF(x0 + 38, top + 34, w - 38, 98), pool.get("title", ""), 66, "#ffffff", True)
        # три счётчика
        gap = 24
        bw = (w - 2 * gap) / 3
        for j, (label, value, color) in enumerate(pool.get("stats", [])[:3]):
            br = QRectF(x0 + j * (bw + gap), top + 160, bw, 220)
            p.save()
            p.setBrush(QColor(255, 255, 255, 16))
            p.setPen(QPen(QColor(255, 255, 255, 44), 2))
            p.drawRoundedRect(br, 28, 28)
            p.restore()
            self._text(p, QRectF(br.left() + 20, br.top() + 18, br.width() - 40, 50),
                       label, 28, self.MUTED, False, shadow=False)
            self._text(p, QRectF(br.left() + 20, br.top() + 72, br.width() - 40, 130),
                       value, 96, color, True)
        # полосы гаранта
        y = top + 430
        for bar in pool.get("bars", []):
            self._draw_pity_bar(p, x0, y, w, bar)
            y += 130
        if pool.get("soft_active"):
            self._text(p, QRectF(x0, y - 34, w, 44), "🔥 Мягкий гарант активен", 30, "#ffa94d", True)
        # плашки кубиков
        cx = x0
        for chip in pool.get("chips", []):
            used = self._draw_chip(p, cx, top + 620, chip)
            cx += used + 20
            if cx > x0 + w:
                break
        # нижний блок: баннеры или составы
        section = top + 730
        if pool.get("banners"):
            cur_h, rer_h = 200, 126
            banners = pool["banners"]
            if r.width() > 2000:                     # одна страница на всю ширину карточки
                if len(banners) > 1:
                    half = (w - 30) / 2
                    self._draw_banner_card(p, QRectF(x0, section, half, cur_h), banners[0], compact=False)
                    self._draw_banner_card(p, QRectF(x0 + half + 30, section, half, cur_h),
                                           banners[1], compact=False)
                else:
                    self._draw_banner_card(p, QRectF(x0, section, w, cur_h), banners[0], compact=False)
                return
            self._draw_banner_card(p, QRectF(x0, section, w, cur_h), banners[0], compact=False)
            if len(banners) > 1:
                self._draw_banner_card(p, QRectF(x0, section + cur_h + 14, w, rer_h),
                                       banners[1], compact=True)
        elif pool.get("roster"):
            self._draw_roster(p, x0, section, w, pool["roster"], wide=r.width() > 2000)

    def _draw_pity_bar(self, p, x, y, w, bar):
        cur, mx = int(bar.get("cur", 0)), max(1, int(bar.get("max", 1)))
        self._text(p, QRectF(x, y, w * 0.62, 50), bar.get("label", ""), 34, "#ffffff", True)
        self._text(p, QRectF(x + w * 0.55, y, w * 0.45, 50), bar.get("right", ""), 30,
                   self.MUTED, False, self.A_R, shadow=False)
        track = QRectF(x, y + 60, w, 34)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 32))
        p.drawRoundedRect(track, 17, 17)
        if cur > 0:
            fill_w = max(track.height(), track.width() * min(1.0, cur / mx))
            fill = QRectF(track.left(), track.top(), fill_w, track.height())
            grad = QLinearGradient(fill.left(), 0, fill.right(), 0)
            grad.setColorAt(0.0, QColor(pity_color(1, mx)))
            grad.setColorAt(1.0, QColor(pity_color(cur, mx)))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(fill, 17, 17)
        soft = bar.get("soft")
        if soft:                                     # отметка мягкого гаранта
            sx = track.left() + track.width() * soft / mx
            p.setPen(QPen(QColor(255, 255, 255, 170), 3))
            p.drawLine(QPointF(sx, track.top() - 8), QPointF(sx, track.bottom() + 8))
        p.setPen(QPen(QColor(255, 255, 255, 70), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(track, 17, 17)
        p.restore()

    def _draw_chip(self, p, x, y, chip) -> float:
        px = 32
        tw = self._text_width(chip["text"], px, True)
        h, w = 84.0, 22 + 60 + 16 + tw + 30
        rect = QRectF(x, y, w, h)
        p.save()
        p.setBrush(QColor(255, 255, 255, 22))
        p.setPen(QPen(QColor(255, 255, 255, 70), 2))
        p.drawRoundedRect(rect, 28, 28)
        p.restore()
        self._icon(p, QRectF(x + 22, y + 12, 60, 60), chip["icon"], chip["rarity"],
                   chip["aliases"], glow=False)
        self._text(p, QRectF(x + 98, y, tw + 24, h), chip["text"], px, "#ffffff", True, elide=False)
        return w

    def _draw_banner_card(self, p, rect, b, compact):
        rect = QRectF(rect)
        radius = 30
        p.save()
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.setClipPath(path)
        art = b.get("art")
        if art is not None and not art.isNull():
            self._draw_cover(p, art.toImage(), rect)
            shade = QLinearGradient(rect.left(), 0, rect.right(), 0)
            shade.setColorAt(0.0, QColor(8, 10, 24, 225))
            shade.setColorAt(0.6, QColor(8, 10, 24, 150))
            shade.setColorAt(1.0, QColor(8, 10, 24, 60))
            p.fillRect(rect, QBrush(shade))
        else:
            p.fillRect(rect, QColor(255, 255, 255, 24))
            sheen = QLinearGradient(rect.topLeft(), rect.bottomRight())
            sheen.setColorAt(0.0, QColor(255, 255, 255, 50))
            sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillRect(rect, QBrush(sheen))
        p.restore()
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 85), 2.5))
        p.drawRoundedRect(rect, radius, radius)
        p.restore()
        x, w = rect.left() + 30, rect.width() - 60
        live = b.get("kind") == "live"
        period_color = self.GOLD if live else QColor(255, 255, 255, 170)
        if compact:
            self._text(p, QRectF(x, rect.top() + 8, w, 30), b.get("caption", ""), 24, self.MUTED,
                       True, shadow=False)
            self._text(p, QRectF(x, rect.top() + 38, w, 50), b.get("name", ""), 40, "#ffffff", True)
            self._text(p, QRectF(x, rect.top() + 86, w, 34), b.get("period", ""), 28, period_color, live)
            return
        self._text(p, QRectF(x, rect.top() + 10, w, 34), b.get("caption", ""), 26, self.MUTED,
                   True, shadow=False)
        self._text(p, QRectF(x, rect.top() + 44, w, 60), b.get("name", ""), 46, "#ffffff", True)
        self._text(p, QRectF(x, rect.top() + 104, w, 40), b.get("period", ""), 32, period_color, True)
        self._text(p, QRectF(x, rect.top() + 146, w, 38), b.get("line", ""), 28, self.MUTED,
                   False, shadow=False)

    def _draw_roster(self, p, x, y, w, roster, wide=False):
        self._text(p, QRectF(x, y, w, 50), roster.get("s_title", ""), 34, "#ffffff", True)
        tiles = roster.get("s", [])
        size, per_row = 150.0, 6
        gap = min(40.0, (w - per_row * size) / (per_row - 1)) if per_row > 1 else 0
        for i, (name, count) in enumerate(tiles[:per_row]):
            tx = x + i * (size + gap)
            ty = y + 62
            self._icon(p, QRectF(tx, ty, size, size), name, 5, (), dim=not count, glow=bool(count))
            label = f"×{count}" if count else "—"
            color = RARITY_COLORS[5] if count else "#b4b9cc"
            self._text(p, QRectF(tx - 10, ty + size + 4, size + 20, 42), label, 32, color, True, self.A_C)
        if wide:                                     # на всю ширину: состав A ранга справа
            ax = x + w / 2
            self._text(p, QRectF(ax, y, w / 2, 50), roster.get("a_text", ""), 34, "#ffffff", True)
            for i, (name, count) in enumerate(roster.get("a", [])[:per_row]):
                tx, ty = ax + i * (size + gap), y + 62
                self._icon(p, QRectF(tx, ty, size, size), name, 4, (), dim=not count, glow=bool(count))
                self._text(p, QRectF(tx - 10, ty + size + 4, size + 20, 42),
                           f"×{count}" if count else "—", 32,
                           RARITY_COLORS[4] if count else "#b4b9cc", True, self.A_C)
            return
        self._text(p, QRectF(x, y + 282, w, 44), roster.get("a_text", ""), 30, self.MUTED,
                   False, shadow=False)

    # ---------- все выпадения S ----------
    def _draw_recent(self, p):
        M, W = self.M, self.DW
        top = self._pools_bottom + 40
        rect = QRectF(M, top, W - 2 * M, 2010 - top)
        self._glass(p, rect, glow=self.GOLD)
        self._text(p, QRectF(rect.left() + 60, rect.top() + 28, 1700, 84),
                   "Все выпадения S", 58, self.GOLD, True)
        self._text(p, QRectF(rect.right() - 1060, rect.top() + 28, 1000, 84),
                   f"Всего S: {self.data.get('total_s', 0)}", 40, self.MUTED, False, self.A_R)
        items = self.data.get("recent") or []
        if not items:
            self._text(p, QRectF(rect.left(), rect.top() + 150, rect.width(), 200),
                       "Пока нет выпадений S ранга", 52, self.MUTED, False, self.A_C)
            return
        # подбор числа колонок и масштаба плитки так, чтобы поместились ВСЕ выпадения
        avail_w, avail_h = rect.width() - 120, rect.height() - 130 - 30
        tile_w, tile_h = 350.0, 370.0
        best = None
        for cols in range(5, 41):
            k = min(1.0, avail_w / cols / tile_w)
            rows = -(-len(items) // cols)
            if rows * tile_h * k <= avail_h and (best is None or k > best[0]):
                best = (k, cols)
        if best is None:
            best = (min(1.0, avail_w / 40 / tile_w), 40)
        k, cols = best
        slot, th = avail_w / cols, tile_h * k
        rows = -(-len(items) // cols)
        y0 = rect.top() + 120 + max(0.0, (avail_h - rows * th) / 2)
        for i, it in enumerate(items):
            row, col = divmod(i, cols)
            n_in_row = min(cols, len(items) - row * cols)
            start = rect.left() + (rect.width() - slot * n_in_row) / 2
            cx = start + slot * (col + 0.5)
            ty = y0 + row * th
            col_l, col_w = cx - slot / 2 + 4, slot - 8
            if it.get("event"):
                plate = QRectF(col_l + 2, ty - 12 * k, col_w - 4, 364 * k)
                pr = 34 * k
                p.save()
                pp = QPainterPath()
                pp.addRoundedRect(plate, pr, pr)
                fill = QLinearGradient(plate.topLeft(), plate.bottomRight())
                fill.setColorAt(0.0, QColor(255, 193, 7, 80))
                fill.setColorAt(0.55, QColor(140, 100, 30, 70))
                fill.setColorAt(1.0, QColor(255, 160, 0, 40))
                p.fillPath(pp, QBrush(fill))
                p.setBrush(Qt.BrushStyle.NoBrush)
                for gi in range(4, 0, -1):
                    gc = QColor(255, 213, 79, 14 * (5 - gi))
                    p.setPen(QPen(gc, max(1.0, 3.0 * k) + gi * 3 * k))
                    p.drawRoundedRect(plate, pr, pr)
                p.setPen(QPen(QColor(255, 213, 79, 235), max(2.0, 5 * k)))
                p.drawRoundedRect(plate, pr, pr)
                p.restore()
            self._icon(p, QRectF(cx - 100 * k, ty, 200 * k, 200 * k), it["name"],
                       it.get("rarity", 5), it.get("aliases", ()))
            self._text(p, QRectF(col_l, ty + 212 * k, col_w, 46 * k),
                       it.get("label") or it["name"], 36 * k, "#ffffff", True, self.A_C)
            pity = int(it.get("pity", 0))
            self._text(p, QRectF(col_l, ty + 258 * k, col_w, 54 * k), f"{pity}", 42 * k,
                       pity_color(pity, it.get("hard", PITY_CHAR_HARD)), True, self.A_C)
            self._text(p, QRectF(col_l, ty + 314 * k, col_w, 34 * k), it.get("date", ""), 26 * k,
                       self.MUTED, False, self.A_C, shadow=False)

    # ---------- подвал и водяной знак ----------
    def _draw_footer(self, p):
        M, W, H = self.M, self.DW, self.DH
        p.save()
        p.setPen(QPen(QColor(255, 255, 255, 55), 2))
        p.drawLine(QPointF(M, 2042), QPointF(W - M, 2042))
        p.restore()
        self._draw_logo(p, QRectF(M, 2056, 70, 70))
        self._text(p, QRectF(M + 92, 2054, 1800, 74), self.data.get("watermark") or SHARE_WATERMARK,
                   38, QColor(255, 255, 255, 215), True)
