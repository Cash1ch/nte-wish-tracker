"""Виджет колеса и подсветка."""

import math
import random

from PyQt6.QtCore import (
    pyqtSignal, QEasingCurve, QElapsedTimer, QObject, QPointF, QRectF, Qt, QTimer, QVariantAnimation,
)
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPen, QPolygonF, QRadialGradient
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QSizePolicy, QWidget

from .themes import FORTUNE_MIN_OPTIONS, FORTUNE_THEMES


def _fortune_draw_paw(p, x, y, size, color, angle=0.0):
    """Отпечаток кошачьей лапки: большая подушечка и четыре «пальчика» (для темы «Белые лапки»)."""
    p.save()
    p.translate(x, y)
    p.rotate(angle)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(QPointF(0, size * 0.28), size * 0.50, size * 0.40)
    for dx, dy, rx, ry in ((-0.62, -0.18, 0.20, 0.26), (-0.22, -0.52, 0.21, 0.28),
                           (0.22, -0.52, 0.21, 0.28), (0.62, -0.18, 0.20, 0.26)):
        p.drawEllipse(QPointF(size * dx, size * dy), size * rx, size * ry)
    p.restore()



# (x, y, размер в долях меньшей стороны, угол) — разбросанные отпечатки лапок для фона
FORTUNE_PAW_SPOTS = ((0.07, 0.10, 0.045, -20), (0.93, 0.07, 0.04, 25), (0.16, 0.40, 0.035, 15),
                     (0.88, 0.36, 0.045, -15), (0.05, 0.66, 0.04, 20), (0.94, 0.62, 0.035, -25),
                     (0.13, 0.92, 0.045, -10), (0.50, 0.97, 0.035, 12), (0.87, 0.93, 0.045, 18),
                     (0.30, 0.04, 0.03, 10), (0.70, 0.03, 0.03, -12), (0.30, 0.66, 0.03, -18))



# ---------- колесо ----------
class FortuneWheel(QWidget):
    """Рисованное колесо: сектора с подписями, штифты, указатель сверху и физика вращения.

    Угол rot — по часовой стрелке (градусы), сектор i занимает [i·S, (i+1)·S) от «верха»
    колеса, указатель смотрит на точку (-rot) mod 360 в системе колеса."""

    spinStarted = pyqtSignal()
    spinFinished = pyqtSignal(int)
    resized = pyqtSignal()                       # изменился размер колеса (двигают разделитель / окно)
    pegCrossed = pyqtSignal(float)               # скорость в момент щелчка штифта
    speedChanged = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(180, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.options = []
        self.wt = FORTUNE_THEMES["classic"]["wheel"]          # палитра колеса (см. set_theme)
        petal_rnd = random.Random(11)                         # лепестки сакуры, парящие вокруг колеса
        self._petals = [(petal_rnd.uniform(0.0, 1.0), petal_rnd.uniform(0.0, 1.2), petal_rnd.uniform(0.035, 0.075),
                         petal_rnd.uniform(0.01, 0.04), petal_rnd.uniform(0.6, 1.6), petal_rnd.uniform(0, math.tau),
                         petal_rnd.uniform(0.7, 1.4), petal_rnd.uniform(-1.5, 1.5), petal_rnd.randint(120, 210))
                        for _ in range(18)]
        self.rot = random.uniform(0.0, 360.0)    # случайный стартовый угол: исход не зависит от начального положения
        self.omega = 0.0                         # угловая скорость, град/с (>0 — по часовой)
        self.spinning = False
        self.winner = -1
        self._flap = 0.0                         # отклонение стрелки от щелчка штифта
        self._t = 0.0
        self._spin_time = 0.0
        self._profile = None
        self._rolling_back = False
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)              # ~60 кадров/с
        self._timer.timeout.connect(self._tick)
        self._clock = QElapsedTimer()
        self._idle = QTimer(self)                # плавное «дыхание» подсветки победителя в покое
        self._idle.setInterval(40)
        self._idle.timeout.connect(self._idle_tick)

    # ---------- данные ----------
    def set_options(self, options):
        if self.spinning:
            return
        self.options = list(options)
        self.winner = -1
        if not self.wt["petals"]:
            self._idle.stop()                                 # без победителя и без лепестков перерисовка в покое не нужна
        self.update()

    def highlight(self, index: int):
        """Подсвечивает сектор (например, единственный оставшийся вариант в режиме «На выбывание»)."""
        if 0 <= index < len(self.options):
            self.winner = index
            self._idle.start()
            self.update()

    @property
    def sector(self) -> float:
        return 360.0 / max(1, len(self.options))

    def pointer_index(self) -> int:
        n = max(1, len(self.options))
        p = (-self.rot) % 360.0
        return min(n - 1, int(p // self.sector))

    # ---------- вращение ----------
    def spin(self) -> bool:
        if self.spinning or len(self.options) < FORTUNE_MIN_OPTIONS:
            return False
        kind = random.choices(("quick", "gradual", "suspense"), weights=(3, 3, 4))[0]
        if kind == "quick":                      # быстро раскрутили и быстро остановили
            self.omega = random.uniform(650, 980)
            self._profile = {"c1": random.uniform(30, 55), "c2": random.uniform(1.5, 2.3),
                             "vc": 70.0, "k": random.uniform(1300, 2200), "kind": kind}
        elif kind == "gradual":                  # долгий плавный накат
            self.omega = random.uniform(950, 1400)
            self._profile = {"c1": random.uniform(8, 16), "c2": random.uniform(0.30, 0.50),
                             "vc": 70.0, "k": random.uniform(1200, 2000), "kind": kind}
        else:                                    # «интрига»: ползёт у штифтов, может откатиться
            self.omega = random.uniform(800, 1150)
            self._profile = {"c1": random.uniform(9, 16), "c2": random.uniform(0.55, 0.85),
                             "vc": 95.0, "k": random.uniform(2200, 3600), "kind": kind}
        self.spinning = True
        self.winner = -1
        self._rolling_back = False
        self._spin_time = 0.0
        self._idle.stop()
        self._clock.start()
        self._timer.start()
        self.spinStarted.emit()
        return True

    def stop_now(self):
        """Останавливает таймеры (закрытие окна)."""
        self._timer.stop()
        self._idle.stop()

    def _tick(self):
        dt = min(self._clock.restart() / 1000.0, 0.05)
        self._t += dt
        self._spin_time += dt
        steps = max(1, math.ceil(dt / 0.005))     # подшаги 5 мс: не пропустить штифт на большой скорости
        for _ in range(steps):
            if not self.spinning:
                break
            self._step(dt / steps)
        self._flap = max(0.0, self._flap - dt * 5.0)
        self.speedChanged.emit(abs(self.omega) if self.spinning else 0.0)
        self.update()

    def _step(self, h):
        prof = self._profile
        c1, c2 = prof["c1"], prof["c2"]
        if self._spin_time > 22.0:               # страховка: слишком долгий накат принудительно гасим
            c1 += 40.0
        s = self.sector
        if not self._rolling_back:
            self.omega = max(0.0, self.omega - (c1 + c2 * self.omega) * h)
            old = math.floor((-self.rot) / s)
            new_rot = self.rot + self.omega * h
            new = math.floor((-new_rot) / s)
            if new < old:                         # пересекли штифт на границе сектора
                if self.omega < prof["vc"]:       # на малой скорости штифт отнимает энергию
                    v2 = self.omega ** 2 - prof["k"]
                    if v2 <= 0:                   # не хватило сил: упёрлись и откатываемся назад
                        self.rot = -old * s + 0.001
                        self.omega = -random.uniform(7.0, 14.0)
                        self._rolling_back = True
                        self._flap = 0.6
                        self.pegCrossed.emit(20.0)
                        return
                    self.omega = math.sqrt(v2)
                self._flap = 1.0
                self.pegCrossed.emit(self.omega)
            self.rot = new_rot
        else:                                     # откат: трение гасит скорость, назад через штифт не идём
            self.omega = min(0.0, self.omega + (c1 + 1.2 * abs(self.omega)) * h)
            s_old = math.floor((-self.rot) / s)
            new_rot = self.rot + self.omega * h
            if math.floor((-new_rot) / s) > s_old:
                self.omega = 0.0
            else:
                self.rot = new_rot
        if abs(self.omega) < 0.8:
            self._finish()

    def _finish(self):
        self.omega = 0.0
        self.spinning = False
        self._rolling_back = False
        self._timer.stop()
        s = self.sector
        frac = ((-self.rot) % 360.0) % s             # не оставляем колесо точно на границе сектора
        if frac < 0.4:
            self.rot -= (0.6 - frac)
        elif frac > s - 0.4:
            self.rot += (0.6 - (s - frac))
        self.winner = self.pointer_index()
        self._idle.start()
        self.speedChanged.emit(0.0)
        self.update()
        self.spinFinished.emit(self.winner)

    # ---------- рисование ----------
    def set_theme(self, theme: str):
        """Переключает палитру колеса: классическая, «Стиль NTE» (неон), «Сакура» (лепестки и цветы) или «Белые лапки» (уютные лапки)."""
        self.wt = FORTUNE_THEMES.get(theme, FORTUNE_THEMES["classic"])["wheel"]
        if not self.spinning:                                 # у «Сакуры» лепестки парят и в покое — нужен таймер перерисовки
            if self.wt["petals"]:
                self._idle.start()
            elif self.winner < 0:
                self._idle.stop()
        self.update()

    def _idle_tick(self):
        self._t += 0.04                                       # время для анимации лепестков и пульса подсветки
        self.update()

    def _draw_blossom(self, p, x, y, r, petal, edge, center):
        """Цветок сакуры: пять лепестков и золотая сердцевина."""
        p.save()
        p.translate(x, y)
        p.setPen(QPen(QColor(edge), max(0.8, r * 0.08)))
        p.setBrush(QColor(petal))
        for k in range(5):
            p.save()
            p.rotate(k * 72)
            p.drawEllipse(QRectF(-r * 0.32, -r * 1.05, r * 0.64, r * 0.95))
            p.restore()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(center))
        p.drawEllipse(QPointF(0, 0), r * 0.28, r * 0.28)
        p.restore()

    def _draw_petals(self, p, w, h, side):
        """Парящие лепестки сакуры (медленно опускаются, покачиваясь и вращаясь)."""
        unit = max(3.0, side * 0.016)
        p.setPen(Qt.PenStyle.NoPen)
        for x0, y0, speed, amp, freq, phase, size, spin, alpha in self._petals:
            y = ((y0 + speed * self._t) % 1.25) - 0.12
            x = x0 + amp * math.sin(self._t * freq + phase)
            ps = unit * size
            p.save()
            p.translate(x * w, y * h)
            p.rotate(self._t * spin * 40.0 + phase * 57.0)
            p.setBrush(QColor(255, 183, 197, alpha))
            p.drawEllipse(QRectF(-ps, -ps * 0.55, ps * 2.0, ps * 1.1))
            p.setBrush(QColor(255, 235, 240, min(255, alpha + 30)))
            p.drawEllipse(QRectF(-ps * 0.55, -ps * 0.3, ps * 1.0, ps * 0.5))
            p.restore()

    def _sector_color(self, i, n):
        colors = self.wt["colors"]
        idx = i % len(colors)
        if n % len(colors) == 1 and i == n - 1:              # последний сектор не должен совпасть цветом с первым
            idx = (idx + 2) % len(colors)
        return QColor(colors[idx])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        wt = self.wt
        w, h = self.width(), self.height()
        side = float(min(w, h))
        # Адаптивный размер: радиус считается от свободного места (min(w, h) / 2 минус запас под ауру и
        # указатель). Запас тоже пропорционален, поэтому аура и стрелка не обрезаются ни в маленьком,
        # ни в большом окне. Все остальные размеры ниже — в долях радиуса (u = R / 220).
        margin = max(14.0, side * 0.085)
        R = max(40.0, side / 2 - margin)
        u = R / 220.0
        cx, cy = w / 2, h / 2
        n = len(self.options)
        # свечение (аура) за колесом: радиус не выходит за границы виджета
        glow_r = max(R + 1.0, min(R + margin - 2.0, side / 2 - 1.0))
        ar, ag, ab = wt["aura"]
        glow = QRadialGradient(cx, cy, glow_r)
        glow.setColorAt(min(0.99, R * 0.90 / glow_r), QColor(ar, ag, ab, 85))
        glow.setColorAt(min(0.995, (R + 8.0 * u) / glow_r), QColor(ar, ag, ab, 60))
        glow.setColorAt(1.0, QColor(ar, ag, ab, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), glow_r, glow_r)
        if wt.get("paws"):                                    # «Белые лапки»: отпечатки лапок вокруг колеса
            paw_col = QColor(217, 195, 169, 90)
            for fx, fy, fs, fa in FORTUNE_PAW_SPOTS:
                _fortune_draw_paw(p, fx * w, fy * h, fs * side, paw_col, fa)
        if wt["petals"]:                                      # «Сакура»: парящие лепестки (за колесом)
            self._draw_petals(p, w, h, side)
        if wt["rim_glow"]:                                    # свечение обода (неон NTE / розовое сияние Сакуры)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for width_k, alpha in ((0.13, 26), (0.08, 52), (0.045, 110)):
                gc = QColor(wt["rim_glow"])
                gc.setAlpha(alpha)
                p.setPen(QPen(gc, R * width_k))
                p.drawEllipse(QPointF(cx, cy), R * 1.01, R * 1.01)
        p.save()
        p.translate(cx, cy)
        p.rotate(self.rot)
        rect = QRectF(-R, -R, 2 * R, 2 * R)
        s = self.sector
        if n == 0:                                            # пустое колесо — бледный диск
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 22))
            p.drawEllipse(QPointF(0, 0), R, R)
        er, eg, eb, ea = wt["edge"]
        for i in range(n):                                    # сектора
            col = self._sector_color(i, n)
            grad = QRadialGradient(0, 0, R)
            grad.setColorAt(0.0, col.lighter(125))
            grad.setColorAt(1.0, col.darker(115))
            p.setBrush(QBrush(grad))
            p.setPen(QPen(QColor(er, eg, eb, ea), max(1.0, 2.0 * u)))   # разделители секторов
            p.drawPie(rect, int((90 - i * s - s) * 16), int(s * 16))
        arc = R * 2 * math.pi / max(n, 1)
        font_px = max(7.0, min(arc * 0.30, R * 0.115))        # размер подписи: по дуге сектора, но не больше доли радиуса
        fm_font = QFont("Georgia")
        fm_font.setPixelSize(max(6, int(round(font_px))))
        fm_font.setBold(True)
        p.setFont(fm_font)
        fm = QFontMetricsF(fm_font)
        for i, text in enumerate(self.options):               # подписи вдоль радиуса
            col = self._sector_color(i, n)
            lum = 0.299 * col.red() + 0.587 * col.green() + 0.114 * col.blue()
            p.setPen(QColor(wt["text_dark"]) if lum > 150 else QColor(wt["text_light"]))
            p.save()
            p.rotate(i * s + s / 2 - 90)
            avail = R * 0.60
            shown = fm.elidedText(text, Qt.TextElideMode.ElideRight, avail)
            p.drawText(QRectF(R * 0.20, -font_px, avail, font_px * 2),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, shown)
            p.restore()
        p.setPen(QPen(QColor(wt["rim"]), max(2.5, R * wt["rim_w"])))   # обод
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), R, R)
        if wt["rim2"]:                                        # NTE: тонкое розовое кольцо внутри обода
            p.setPen(QPen(QColor(wt["rim2"]), max(1.2, R * 0.012)))
            p.drawEllipse(QPointF(0, 0), R * 0.955, R * 0.955)
        p.setPen(Qt.PenStyle.NoPen)
        peg_r = max(2.0, R * 0.03)
        for i in range(n):                                    # штифты на границах секторов
            ang = math.radians(i * s)
            px, py = math.sin(ang) * R, -math.cos(ang) * R
            if wt["blossom"]:                                 # «Сакура»: вместо штифтов — цветки сакуры
                self._draw_blossom(p, px, py, peg_r * 2.0, "#ffb7c5", "#d63a5c", "#e6ca65")
                continue
            peg = QRadialGradient(px - peg_r * 0.3, py - peg_r * 0.3, peg_r * 1.6)
            peg.setColorAt(0.0, QColor(wt["peg"][0]))
            peg.setColorAt(1.0, QColor(wt["peg"][1]))
            p.setBrush(QBrush(peg))
            p.drawEllipse(QPointF(px, py), peg_r, peg_r)
        p.restore()
        if self.winner >= 0 and not self.spinning:            # подсветка выигравшего сектора
            self._draw_winner(p, cx, cy, R, n, s, u)
        hub = QRadialGradient(cx - R * 0.03, cy - R * 0.03, R * 0.18)    # центральная «втулка»
        hub.setColorAt(0.0, QColor(wt["hub"][0]))
        hub.setColorAt(1.0, QColor(wt["hub"][1]))
        p.setPen(QPen(QColor(wt["hub"][2]), max(1.0, 2.0 * u) * wt["hub_pen"]))
        p.setBrush(QBrush(hub))
        p.drawEllipse(QPointF(cx, cy), R * 0.15, R * 0.15)
        if wt["blossom"]:                                     # «Сакура»: в центре — цветок
            self._draw_blossom(p, cx, cy, R * 0.115, "#ffb7c5", wt["star"], "#e6ca65")
        elif wt.get("paws"):                                  # «Белые лапки»: в центре — лапка
            _fortune_draw_paw(p, cx, cy - R * 0.006, R * 0.105, QColor(wt["star"]))
        else:
            star = []
            for k in range(10):
                a = -math.pi / 2 + k * math.pi / 5
                rad = R * (0.085 if k % 2 == 0 else 0.037)
                star.append(QPointF(cx + math.cos(a) * rad, cy + math.sin(a) * rad))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(wt["star"]))
            p.drawPolygon(QPolygonF(star))
        # указатель сверху: размеры в долях радиуса, качается от щелчков штифтов
        p.save()
        p.translate(cx, cy - R - R * 0.01)
        p.rotate(-self._flap * 18.0)
        half, up, down = R * (0.045 if wt["ptr_sharp"] else 0.055), R * 0.045, R * (0.11 if wt["ptr_sharp"] else 0.09)
        if wt["ptr_glow"]:                                    # свечение вокруг острого указателя
            glow_ptr = QColor(wt["ptr_glow"])
            glow_ptr.setAlpha(70)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow_ptr)
            p.drawPolygon(QPolygonF([QPointF(0, down * 1.35), QPointF(-half * 1.9, -up * 1.6), QPointF(half * 1.9, -up * 1.6)]))
        ptr = QPolygonF([QPointF(0, down), QPointF(-half, -up), QPointF(half, -up)])
        p.setPen(QPen(QColor(wt["ptr"][1]), max(1.0, 2.0 * u)))
        p.setBrush(QColor(wt["ptr"][0]))
        p.drawPolygon(ptr)
        p.setBrush(QColor(wt["ptr"][2]))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(0, -R * 0.018), R * 0.016, R * 0.016)
        p.restore()
        p.end()

    def _draw_winner(self, p, cx, cy, R, n, s, u=1.0):
        wt = self.wt
        pulse = 0.5 + 0.5 * math.sin(self._t * 3.0)
        p.save()
        p.translate(cx, cy)
        p.rotate(self.rot)
        rect = QRectF(-R, -R, 2 * R, 2 * R)
        for i in range(n):
            if i != self.winner:                              # остальные сектора приглушаем
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(*wt.get("dim", (10, 6, 25, 140))))
                p.drawPie(rect, int((90 - i * s - s) * 16), int(s * 16))
        i = self.winner
        wr, wg, wb = wt["win"]
        er, eg, eb = wt["win_edge"]
        p.setBrush(QColor(wr, wg, wb, int(50 + 60 * pulse)))
        p.setPen(QPen(QColor(er, eg, eb, int(180 + 75 * pulse)), max(2.0, 4.0 * u)))
        p.drawPie(rect, int((90 - i * s - s) * 16), int(s * 16))
        p.restore()



# ---------- мягкое мерцание свечения кнопки ----------
class PulsingGlow(QObject):
    """Мягкое мерцание свечения кнопки: меняется только прозрачность тени (0.4 -> 1.0 -> 0.4).
    Радиус и размер свечения не пульсируют. Цикл медленный (≈3,4 с) и без резких вспышек."""

    def __init__(self, widget: QWidget, color: str = "#ffd166", parent=None):
        super().__init__(parent or widget)
        self.widget = widget
        self.color = QColor(color)
        self.effect = QGraphicsDropShadowEffect(widget)
        self.effect.setOffset(0, 0)
        self.effect.setBlurRadius(22)                      # радиус свечения постоянный — «пульсации» нет
        c = QColor(self.color)
        c.setAlphaF(0.4)
        self.effect.setColor(c)
        widget.setGraphicsEffect(self.effect)
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(math.tau)
        self.anim.setDuration(3400)
        self.anim.setLoopCount(-1)
        self.anim.setEasingCurve(QEasingCurve.Type.Linear)
        self.anim.valueChanged.connect(self._on_value)
        self.anim.start()

    def _on_value(self, value):
        if not self.widget.isVisible():
            return                                        # скрытая вкладка не перерисовывается
        k = 0.5 - 0.5 * math.cos(float(value))             # плавная волна 0..1 (синусоида)
        c = QColor(self.color)
        c.setAlphaF(0.4 + 0.6 * k)
        self.effect.setColor(c)

    def stop(self):
        self.anim.stop()
