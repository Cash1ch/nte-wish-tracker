"""Фоновая анимация вкладки «Стафф» (снежинки / листочки)."""

import math
import random

from PyQt6.QtCore import QElapsedTimer, QEvent, QPointF, QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QStackedWidget, QTabWidget, QWidget

from ..compat import QAudio
from ..config import ANIM_DEFAULT_EFFECT, ANIM_EFFECTS, ANIM_FRAME_MS


# ----------------------------------------------------------------------------
# НОВОЕ: фоновая музыка
# ----------------------------------------------------------------------------
def volume_to_linear(percent: int) -> float:
    """Положение ползунка (0..100) -> линейная громкость 0.0..1.0 для QAudioOutput.
    Человеческое ухо воспринимает громкость логарифмически, поэтому ползунок
    переводится через QAudio.convertVolume: так «половина ползунка» звучит именно как
    половина громкости, а не слишком громко. Если функции нет в этой сборке Qt —
    используется простое линейное соответствие."""
    value = max(0, min(100, int(percent))) / 100.0
    if QAudio is not None:
        try:
            return float(QAudio.convertVolume(
                value, QAudio.VolumeScale.LogarithmicVolumeScale,
                QAudio.VolumeScale.LinearVolumeScale))
        except (AttributeError, TypeError):
            pass
    return value



# ----------------------------------------------------------------------------
# НОВОЕ: фоновая анимация вкладки «Стафф» (снежинки / листочки / звёздочки)
# ----------------------------------------------------------------------------
class _Particle:
    __slots__ = ("x", "y", "x0", "size", "vx", "vy", "angle", "spin", "phase", "omega",
                 "amp", "swing", "alpha", "color")



_SPRITE_PATHS = {}



def _sprite_path(kind: str) -> QPainterPath:
    """Единичные контуры (радиус ~1), создаются один раз."""
    path = _SPRITE_PATHS.get(kind)
    if path is not None:
        return path
    path = QPainterPath()
    if kind == "snow":
        for k in range(6):
            a = math.radians(k * 60)
            ca, sa = math.cos(a), math.sin(a)
            path.moveTo(0, 0)
            path.lineTo(ca, sa)
            bx, by = ca * 0.58, sa * 0.58
            for da in (-45, 45):
                b = math.radians(k * 60 + da)
                path.moveTo(bx, by)
                path.lineTo(bx + math.cos(b) * 0.30, by + math.sin(b) * 0.30)
    elif kind == "leaves":
        path.moveTo(0, 0)
        path.cubicTo(0.95, 0.5, 0.85, 1.45, 0, 2.0)
        path.cubicTo(-0.85, 1.45, -0.95, 0.5, 0, 0)
    elif kind == "leaf_vein":
        path.moveTo(0, 0)
        path.lineTo(0, 1.8)
    else:  # stars
        for i in range(10):
            a = math.radians(-90 + i * 36)
            r = 1.0 if i % 2 == 0 else 0.45
            pt = QPointF(math.cos(a) * r, math.sin(a) * r)
            if i == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        path.closeSubpath()
    _SPRITE_PATHS[kind] = path
    return path



class FallingBackground(QWidget):
    """Лёгкий прозрачный слой с падающими частицами. Лежит под страницами QTabWidget
    (stackUnder), занимает область ниже строки подвкладок, не принимает мышь и
    перерисовывает только небольшие участки вокруг частиц."""

    LEAF_COLORS = ("#e8833a", "#d9a441", "#c0562f", "#8fae4a", "#b8722c")

    def __init__(self, tabs: QTabWidget, enabled: bool = True, effect: str = ANIM_DEFAULT_EFFECT):
        super().__init__(tabs)
        self._tabs = tabs
        self._stack = tabs.findChild(QStackedWidget, "", Qt.FindChildOption.FindDirectChildrenOnly)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._enabled = bool(enabled)
        self._effect = effect if effect in dict(ANIM_EFFECTS) else ANIM_DEFAULT_EFFECT
        self._particles = []
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(ANIM_FRAME_MS)
        self._timer.timeout.connect(self._tick)
        tabs.installEventFilter(self)
        if self._stack is not None:
            self._stack.installEventFilter(self)
            self.stackUnder(self._stack)     # самый нижний слой: под карточками и текстом
        self._sync_geometry()
        self.setVisible(self._enabled)

    # ---- публичный интерфейс ----
    def configure(self, enabled: bool, effect: str):
        effect = effect if effect in dict(ANIM_EFFECTS) else ANIM_DEFAULT_EFFECT
        changed = effect != self._effect
        self._enabled = bool(enabled)
        self._effect = effect
        if changed:
            self._particles = []
        if self._stack is not None:
            self.stackUnder(self._stack)
        self.setVisible(self._enabled)
        if not self._enabled:
            self._timer.stop()
            self._particles = []
        self.update()

    # ---- геометрия ----
    def _sync_geometry(self):
        if self._stack is not None:
            self.setGeometry(self._stack.geometry())
        else:
            self.setGeometry(self._tabs.rect())

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.LayoutRequest,
                            QEvent.Type.Show):
            self._sync_geometry()
        return False

    def showEvent(self, event):
        super().showEvent(event)
        if self._enabled:
            self._clock.start()
            self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    # ---- частицы ----
    def _target_count(self) -> int:
        return max(12, min(40, (self.width() * self.height()) // 24000))

    def _spawn(self, initial: bool) -> _Particle:
        w, h = max(self.width(), 1), max(self.height(), 1)
        q = _Particle()
        q.phase = random.uniform(0, math.tau)
        q.omega = q.amp = q.swing = q.vx = 0.0
        q.angle = random.uniform(0, 360)
        q.spin = 0.0
        q.alpha = random.uniform(0.35, 0.8)
        eff = self._effect
        if eff == "snow":
            q.size = random.uniform(5, 13)
            q.vy = random.uniform(22, 48)
            q.spin = random.uniform(10, 28)                    # по часовой стрелке
            q.x = q.x0 = random.uniform(0, w)
            q.y = random.uniform(-h * 0.1, h) if initial else -q.size * 2
            q.color = QColor(235, 244, 255)
        elif eff == "leaves":
            q.size = random.uniform(7, 13)
            q.vy = random.uniform(38, 72)
            q.omega = random.uniform(0.8, 1.5)                 # маятник: качание из стороны в сторону
            q.amp = random.uniform(16, 38)
            q.swing = random.uniform(22, 38)
            q.x0 = random.uniform(0, w)
            q.x = q.x0
            q.y = random.uniform(-h * 0.1, h) if initial else -q.size * 3
            q.color = QColor(random.choice(self.LEAF_COLORS))
        else:
            q.size = random.uniform(5, 11)
            q.vx = random.uniform(55, 95)                      # по диагонали, слева направо вниз
            q.vy = random.uniform(40, 70)
            q.spin = random.uniform(14, 34)                    # по часовой стрелке
            if initial:
                q.x = random.uniform(-q.size, w)
                q.y = random.uniform(-h * 0.4, h)
            else:
                q.x = -q.size * 2                              # рождаются у левого края
                q.y = random.uniform(-h * 0.5, h * 0.9)
            q.x0 = q.x
            q.color = QColor(255, 215, 64)
        return q

    def _radius(self, q: _Particle) -> float:
        if self._effect == "leaves":
            return q.size * 2.2
        return q.size * 1.5

    def _dirty_rect(self, q: _Particle) -> QRect:
        r = self._radius(q) + 3
        return QRect(int(q.x - r), int(q.y - r), int(r * 2) + 1, int(r * 2) + 1)

    def _tick(self):
        if not self._enabled or not self.isVisible() or self.width() < 20 or self.height() < 20:
            return
        dt = min(self._clock.restart() / 1000.0, 0.1)
        w, h = self.width(), self.height()
        want = self._target_count()
        while len(self._particles) < want:
            self._particles.append(self._spawn(initial=True))
        del self._particles[want:]
        eff = self._effect
        for i, q in enumerate(self._particles):
            self.update(self._dirty_rect(q))
            q.y += q.vy * dt
            if eff == "leaves":
                q.phase += q.omega * dt
                q.x = q.x0 + q.amp * math.sin(q.phase)
                q.angle = q.swing * math.sin(q.phase)
                pad = q.size * 3
            else:
                q.x += q.vx * dt
                q.angle = (q.angle + q.spin * dt) % 360
                pad = q.size * 2
            if q.y > h + pad or q.x > w + pad + q.amp:
                self._particles[i] = q = self._spawn(initial=False)
            self.update(self._dirty_rect(q))

    # ---- рисование ----
    def paintEvent(self, event):
        if not self._enabled or not self._particles:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        clip = event.rect()
        eff = self._effect
        for q in self._particles:
            if not clip.intersects(self._dirty_rect(q)):
                continue
            painter.save()
            painter.setOpacity(q.alpha)
            painter.translate(q.x, q.y)
            painter.rotate(q.angle)
            painter.scale(q.size, q.size)
            if eff == "snow":
                pen = QPen(q.color, 0.14)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(_sprite_path("snow"))
            elif eff == "leaves":
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(q.color)
                painter.drawPath(_sprite_path("leaves"))
                vein = QPen(q.color.darker(150), 0.08)
                vein.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(vein)
                painter.drawPath(_sprite_path("leaf_vein"))
            else:
                painter.setPen(QPen(QColor(255, 244, 190), 0.07))
                painter.setBrush(q.color)
                painter.drawPath(_sprite_path("stars"))
            painter.restore()
        painter.end()
