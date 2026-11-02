"""Мини-игра «Арканоид»."""

import math
import random

from PyQt6.QtCore import pyqtSignal, QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from .audio import GameSfxMixin


# =====================================================================================
# НОВОЕ: встроенная мини-игра «Арканоид» (кнопка «Поиграй 🎮» на вкладке «Скриншоты разом»).
# Логика (ArkanoidEngine) не зависит от Qt и считает движение по времени кадра (dt) с
# подшагами, поэтому мяч не «пролетает» сквозь блоки, а скорость не зависит от частоты
# таймера. Виджет рисует кадр в paintEvent; игровой цикл — QTimer ~60 кадров/с в основном
# потоке: игра очень лёгкая и не мешает фоновым потокам OCR.
# =====================================================================================
MINIGAME_ARKANOID_KEY = "minigame_arkanoid_highscore"



MINIGAME_PLATFORMER_KEY = "minigame_platformer_highscore"



# цвета рядов блоков сверху вниз: верхний ряд — «бронированный» (2 попадания)
ARKANOID_ROW_COLORS = ("#c0c8d8", "#ff4d4d", "#ff9a3c", "#ffd84a", "#4cff6a", "#5ce1ff")



class ArkanoidEngine(GameSfxMixin):
    """Чистая логика «Арканоида» (без Qt). Координаты — логические пиксели поля W×H;
    виджет сам масштабирует поле под размер окна."""

    W, H = 480, 600
    TOP, WALL = 48, 8                      # высота строки со счётом и толщина боковых стен
    COLS, ROWS = 10, 6
    PITCH_X, PITCH_Y = 44, 22              # шаг сетки блоков
    BRICK_W, BRICK_H = 42, 20
    BRICK_Y0 = 92
    PADDLE_W, PADDLE_H, PADDLE_Y = 84, 12, 556
    BALL_R = 6
    ROW_POINTS = (70, 60, 50, 40, 30, 20)  # очки за блок: верхние ряды дороже
    LIVES = 3

    def __init__(self, high_score: int = 0):
        self.high = max(0, int(high_score))
        self.state = "ready"               # ready / playing / paused / over / won
        self.new_game()

    # ---------- подготовка ----------
    def new_game(self):
        self.score = 0
        self.lives = self.LIVES
        self.broken = 0
        self.record_beaten = False
        self.paddle_x = self.W / 2
        self.particles = []
        self.build_bricks()
        self.reset_ball()

    def build_bricks(self):
        x0 = (self.W - self.COLS * self.PITCH_X) / 2 + (self.PITCH_X - self.BRICK_W) / 2
        self.bricks = [
            {"c": c, "r": r, "hp": 2 if r == 0 else 1, "flash": 0.0,
             "x": x0 + c * self.PITCH_X, "y": self.BRICK_Y0 + r * self.PITCH_Y}
            for r in range(self.ROWS) for c in range(self.COLS)
        ]

    def reset_ball(self):
        """Мяч «приклеен» к платформе до запуска (пробел / ↑ / щелчок мыши)."""
        self.stuck = True
        self.vx = self.vy = 0.0
        self.bx = self.paddle_x
        self.by = self.PADDLE_Y - self.BALL_R - 1

    @property
    def speed(self) -> float:
        return 330.0 + min(170.0, self.broken * 2.5)    # мяч разгоняется по ходу игры

    # ---------- управление ----------
    def start(self):
        if self.state in ("ready", "over", "won"):
            if self.state != "ready":
                self.new_game()
            self.state = "playing"

    def pause(self):
        if self.state == "playing":
            self.state = "paused"

    def resume(self):
        if self.state == "paused":
            self.state = "playing"

    def launch(self):
        """Запуск мяча с платформы под небольшим случайным углом."""
        if self.state == "playing" and self.stuck:
            self.stuck = False
            self._set_velocity(math.sin(math.radians(random.uniform(-22, 22))),
                               -math.cos(math.radians(random.uniform(0, 22))))

    def set_paddle_x(self, x: float):
        """Платформа под курсором мыши (центр платформы в логических координатах)."""
        if self.state in ("ready", "playing"):
            self._place_paddle(x)

    def _place_paddle(self, x: float):
        half = self.PADDLE_W / 2
        self.paddle_x = min(self.W - self.WALL - half, max(self.WALL + half, x))
        if self.stuck:
            self.bx = self.paddle_x

    # ---------- вспомогательное ----------
    def _set_velocity(self, dx: float, dy: float):
        """Задаёт направление и приводит скорость к текущей; не даёт мячу идти почти
        горизонтально (иначе он может бесконечно кататься между стенами)."""
        length = math.hypot(dx, dy) or 1.0
        dx, dy = dx / length, dy / length
        if abs(dy) < 0.28:
            dy = math.copysign(0.28, dy or -1)
            dx = math.copysign(math.sqrt(1 - dy * dy), dx or 1)
        self.vx, self.vy = dx * self.speed, dy * self.speed

    def _add_score(self, pts: int):
        self.score += pts
        if self.score > self.high:
            self.high = self.score
            self.record_beaten = True

    def _burst(self, brick: dict):
        for _ in range(7):
            ang = random.uniform(0, math.tau)
            sp = random.uniform(40, 160)
            self.particles.append({"x": brick["x"] + self.BRICK_W / 2, "y": brick["y"] + self.BRICK_H / 2,
                                   "vx": math.cos(ang) * sp, "vy": math.sin(ang) * sp - 30,
                                   "t": 0.0, "r": brick["r"]})

    # ---------- один шаг игры ----------
    def update(self, dt: float, left: bool, right: bool):
        if self.state != "playing":
            return
        dt = min(max(dt, 0.0), 0.05)
        for p in self.particles:
            p["t"] += dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vy"] += 400 * dt
        self.particles = [p for p in self.particles if p["t"] < 0.5]
        for b in self.bricks:
            b["flash"] = max(0.0, b["flash"] - dt)
        if left and not right:
            self._place_paddle(self.paddle_x - 520.0 * dt)
        elif right and not left:
            self._place_paddle(self.paddle_x + 520.0 * dt)
        if self.stuck:
            return
        steps = max(1, math.ceil(self.speed * dt / 3.0))    # подшаги: не больше ~3 px за шаг
        for _ in range(steps):
            self._advance(dt / steps)
            if self.state != "playing" or self.stuck:
                break

    def _advance(self, h: float):
        r = self.BALL_R
        self.bx += self.vx * h
        self.by += self.vy * h
        # стены и потолок
        if self.bx - r < self.WALL:
            self.bx, self.vx = self.WALL + r, abs(self.vx)
            self._snd("wall")
        elif self.bx + r > self.W - self.WALL:
            self.bx, self.vx = self.W - self.WALL - r, -abs(self.vx)
            self._snd("wall")
        if self.by - r < self.TOP:
            self.by, self.vy = self.TOP + r, abs(self.vy)
            self._snd("wall")
        # платформа: угол отскока зависит от места попадания
        top = self.PADDLE_Y
        half = self.PADDLE_W / 2
        if (self.vy > 0 and top <= self.by + r <= top + 12
                and self.paddle_x - half - r * 0.6 <= self.bx <= self.paddle_x + half + r * 0.6):
            rel = max(-1.0, min(1.0, (self.bx - self.paddle_x) / half))
            ang = math.radians(rel * 62)
            self.by = top - r
            self._set_velocity(math.sin(ang), -math.cos(ang))
            self._snd("paddle")
            return
        # блоки
        for b in self.bricks:
            cx = min(max(self.bx, b["x"]), b["x"] + self.BRICK_W)
            cy = min(max(self.by, b["y"]), b["y"] + self.BRICK_H)
            dx, dy = self.bx - cx, self.by - cy
            if dx * dx + dy * dy > r * r:
                continue
            if dx == 0 and dy == 0:                       # центр мяча внутри блока
                self.vy = -self.vy
            elif abs(dx) > abs(dy):                       # удар сбоку
                self.vx = abs(self.vx) * (1 if dx > 0 else -1)
                self.bx = cx + (r + 0.01) * (1 if dx > 0 else -1)
            else:                                         # удар сверху / снизу
                self.vy = abs(self.vy) * (1 if dy > 0 else -1)
                self.by = cy + (r + 0.01) * (1 if dy > 0 else -1)
            b["hp"] -= 1
            b["flash"] = 0.12
            self._snd("brick" if b["hp"] <= 0 else "wall")
            if b["hp"] <= 0:
                self.bricks.remove(b)
                self.broken += 1
                self._add_score(self.ROW_POINTS[b["r"]])
                self._burst(b)
            self._set_velocity(self.vx, self.vy)
            break
        if not self.bricks:                               # стенка разрушена — победа
            self._add_score(50 * self.lives)              # бонус за оставшиеся жизни
            self.state = "won"
            self._snd("win")
            self.stuck = True
            self.vx = self.vy = 0.0
            return
        # мяч упал под платформу
        if self.by - r > self.H:
            self.lives -= 1
            if self.lives <= 0:
                self.lives = 0
                self.state = "over"
                self._snd("gameover")
            else:
                self._snd("death")
            self.reset_ball()



class ArkanoidWidget(QWidget):
    """Поле игры: рисует кадр, обрабатывает клавиши и мышь. Цикл — QTimer ~60 кадров/с."""

    closeRequested = pyqtSignal()
    highScoreChanged = pyqtSignal(int)

    # коды клавиш как обычные числа (event.key() возвращает int) — не зависит от типа enum
    K_LEFT, K_RIGHT = int(Qt.Key.Key_Left.value), int(Qt.Key.Key_Right.value)
    K_UP, K_SPACE = int(Qt.Key.Key_Up.value), int(Qt.Key.Key_Space.value)
    K_P, K_ESC = int(Qt.Key.Key_P.value), int(Qt.Key.Key_Escape.value)

    def __init__(self, high_score: int = 0, parent=None):
        super().__init__(parent)
        self.engine = ArkanoidEngine(high_score)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)              # платформа следует за мышью без нажатия кнопки
        self.setMinimumSize(240, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._keys = set()
        self._t = 0.0
        self._ticks = 0
        self._end_since = None
        self._reported_high = self.engine.high
        stars = random.Random(11)
        self._stars = [(stars.uniform(0, ArkanoidEngine.W), stars.uniform(ArkanoidEngine.TOP, ArkanoidEngine.H),
                        stars.choice((1, 1, 2))) for _ in range(50)]
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)   # ровные ~60 кадров в секунду
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    # ---------- цикл ----------
    def start_loop(self):
        self._clock.start()
        self._timer.start()

    def stop_loop(self):
        self._timer.stop()
        self._keys.clear()

    def shutdown(self):
        """Останавливает таймер и отключает его — после этого виджет безопасно удалять."""
        self._timer.stop()
        try:
            self._timer.timeout.disconnect(self._tick)
        except (TypeError, RuntimeError):
            pass
        self._keys.clear()
        self._report_high()

    def pause(self):
        self._keys.clear()
        if self.engine.state == "playing":
            self.engine.pause()
            self.update()

    def _report_high(self):
        if self.engine.high > self._reported_high:
            self._reported_high = self.engine.high
            self.highScoreChanged.emit(self.engine.high)

    def _tick(self):
        dt = min(self._clock.restart() / 1000.0, 0.05)
        self._t += dt
        self._ticks += 1
        eng = self.engine
        if eng.state == "playing":
            eng.update(dt, self.K_LEFT in self._keys, self.K_RIGHT in self._keys)
            if eng.state in ("over", "won"):
                self._end_since = self._t
                self._keys.clear()
                self._report_high()
            self.update()
        elif self._ticks % 15 == 0:              # мигающие подсказки на экранах паузы / конца
            self.update()

    # ---------- ввод ----------
    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            event.accept()
            return
        key = int(event.key())
        if key in (self.K_LEFT, self.K_RIGHT):
            self._keys.add(key)
        elif key in (self.K_UP, self.K_SPACE):
            self._action()
        elif key == self.K_P:
            if self.engine.state == "playing":
                self.engine.pause()
            elif self.engine.state == "paused":
                self.engine.resume()
            self.update()
        elif key == self.K_ESC:
            if self.engine.state == "playing":
                self.engine.pause()
                self.update()
            else:
                self.closeRequested.emit()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def keyReleaseEvent(self, event):
        if not event.isAutoRepeat():
            self._keys.discard(int(event.key()))
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.pause()                             # потеряли фокус — автопауза
        super().focusOutEvent(event)

    def _view(self):
        eng = self.engine
        scale = min(self.width() / eng.W, self.height() / eng.H)
        return scale, (self.width() - eng.W * scale) / 2, (self.height() - eng.H * scale) / 2

    def mouseMoveEvent(self, event):
        scale, ox, _oy = self._view()
        if scale > 0:
            self.engine.set_paddle_x((event.position().x() - ox) / scale)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self._action()
        super().mousePressEvent(event)

    def _action(self):
        """Пробел / ↑ / щелчок: начать игру, запустить мяч, продолжить или сыграть заново."""
        eng = self.engine
        if eng.state == "ready":
            eng.start()
        elif eng.state in ("over", "won"):
            if self._end_since is None or self._t - self._end_since >= 0.6:
                eng.start()
        elif eng.state == "paused":
            eng.resume()
        elif eng.state == "playing":
            eng.launch()
        self.update()

    # ---------- рисование ----------
    def _font(self, size):
        f = QFont("Consolas")
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPixelSize(size)
        f.setBold(True)
        return f

    def paintEvent(self, event):
        eng = self.engine
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#05060d"))
        scale, ox, oy = self._view()
        p.translate(ox, oy)
        p.scale(scale, scale)
        p.setClipRect(QRectF(0, 0, eng.W, eng.H))
        p.fillRect(QRectF(0, 0, eng.W, eng.H), QColor("#070a18"))
        for sx, sy, sz in self._stars:           # мерцающие звёзды
            tw = 90 + int(70 * math.sin(self._t * 2 + sx))
            p.fillRect(QRectF(sx, sy, sz, sz), QColor(tw + 60, tw + 60, 255))
        self._draw_world(p)
        self._draw_hud(p)
        self._draw_overlay(p)
        p.setPen(QPen(QColor(0, 0, 0, 46), 1))   # «строки» старого монитора
        for y in range(0, eng.H, 3):
            p.drawLine(0, y, eng.W, y)
        p.setClipping(False)
        p.setPen(QPen(QColor("#3a4a8a"), 2 / max(scale, 0.1)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(0, 0, eng.W, eng.H))
        p.end()

    def _draw_world(self, p):
        eng = self.engine
        wall = QColor("#3a4a8a")                 # боковые стены и потолок
        p.fillRect(QRectF(0, eng.TOP, eng.WALL, eng.H - eng.TOP), wall)
        p.fillRect(QRectF(eng.W - eng.WALL, eng.TOP, eng.WALL, eng.H - eng.TOP), wall)
        p.fillRect(QRectF(0, eng.TOP - 4, eng.W, 4), wall)
        p.setPen(Qt.PenStyle.NoPen)
        for b in eng.bricks:                     # блоки с «объёмом»: светлая верхняя грань, тёмная нижняя
            base = QColor(ARKANOID_ROW_COLORS[b["r"]])
            if b["hp"] == 1 and b["r"] == 0:
                base = QColor("#7d8496")         # повреждённый бронированный блок темнее
            if b["flash"] > 0:
                base = QColor("#ffffff")
            rect = QRectF(b["x"], b["y"], eng.BRICK_W, eng.BRICK_H)
            p.fillRect(rect, base)
            p.fillRect(QRectF(rect.x(), rect.y(), rect.width(), 3), base.lighter(150))
            p.fillRect(QRectF(rect.x(), rect.bottom() - 3, rect.width(), 3), base.darker(160))
            p.fillRect(QRectF(rect.x(), rect.y(), 3, rect.height()), base.lighter(125))
            if b["hp"] == 1 and b["r"] == 0:     # трещина
                p.fillRect(QRectF(rect.x() + 10, rect.y() + 6, 22, 2), QColor("#2b2f3b"))
        for part in eng.particles:               # осколки разбитых блоков
            col = QColor(ARKANOID_ROW_COLORS[part["r"]])
            col.setAlpha(int(255 * (1 - part["t"] / 0.5)))
            p.fillRect(QRectF(part["x"], part["y"], 4, 4), col)
        # платформа
        px = eng.paddle_x - eng.PADDLE_W / 2
        body = QRectF(px, eng.PADDLE_Y, eng.PADDLE_W, eng.PADDLE_H)
        path = QPainterPath()
        path.addRoundedRect(body, 6, 6)
        grad = QLinearGradient(0, body.top(), 0, body.bottom())
        grad.setColorAt(0.0, QColor("#e8f0ff"))
        grad.setColorAt(0.5, QColor("#7da2ff"))
        grad.setColorAt(1.0, QColor("#3a4a8a"))
        p.fillPath(path, QBrush(grad))
        p.fillRect(QRectF(px + 6, eng.PADDLE_Y + 2, 18, 2), QColor(255, 255, 255, 160))
        p.fillRect(QRectF(px + 4, eng.PADDLE_Y + 3, 5, 6), QColor("#ff4d4d"))
        p.fillRect(QRectF(px + eng.PADDLE_W - 9, eng.PADDLE_Y + 3, 5, 6), QColor("#ff4d4d"))
        # мяч со свечением
        glow = QColor(255, 255, 255, 50)
        p.setBrush(glow)
        p.drawEllipse(QPointF(eng.bx, eng.by), eng.BALL_R + 4, eng.BALL_R + 4)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(eng.bx, eng.by), eng.BALL_R, eng.BALL_R)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_hud(self, p):
        eng = self.engine
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        p.setFont(self._font(16))
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(12, 6, 220, 22), left, f"Счет: {eng.score}")
        p.setPen(QColor("#ffd84a"))
        p.drawText(QRectF(eng.W - 232, 6, 220, 22), right, f"Рекорд: {eng.high}")
        p.setFont(self._font(14))
        p.setPen(QColor("#ff6b6b"))
        p.drawText(QRectF(12, 26, 220, 18), left, f"Жизни: {eng.lives}")
        p.setPen(QColor("#9fb4ff"))
        p.drawText(QRectF(eng.W - 232, 26, 220, 18), right, f"Блоков: {len(eng.bricks)}")
        p.setPen(QPen(QColor("#3a4a8a"), 1))
        p.drawLine(0, eng.TOP - 5, eng.W, eng.TOP - 5)

    def _draw_overlay(self, p):
        eng = self.engine
        blink = int(self._t * 2) % 2 == 0
        center = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter

        def text(y, s, size, color, h=30):
            p.setFont(self._font(size))
            p.setPen(QColor(color))
            p.drawText(QRectF(0, y, eng.W, h), center, s)

        if eng.state == "playing":
            if eng.stuck and blink:
                text(eng.PADDLE_Y - 70, "Пробел / ↑ / щелчок мыши — запуск мяча", 14, "#ffd84a", 24)
            return
        p.fillRect(QRectF(0, 0, eng.W, eng.H), QColor(0, 0, 0, 165))
        if eng.state == "ready":
            text(150, "АРКАНОИД", 44, "#7da2ff", 56)
            text(240, "← →  или мышь  —  платформа", 16, "#ffffff")
            text(266, "Пробел / ↑ / щелчок  —  запуск мяча", 16, "#ffffff")
            text(292, "P  —  пауза     Esc  —  пауза / выход в меню", 16, "#ffffff")
            if blink:
                text(370, "Нажмите Пробел, чтобы начать", 17, "#ffd84a")
        elif eng.state == "paused":
            text(220, "ПАУЗА", 38, "#ffd84a", 50)
            text(290, "P или Пробел  —  продолжить", 16, "#ffffff")
            text(316, "Esc  —  к выбору игры", 16, "#ffffff")
        else:
            won = eng.state == "won"
            text(170, "Победа!" if won else "Игра окончена", 36, "#4cff6a" if won else "#ff4a4a", 48)
            text(240, f"Счет: {eng.score}", 22, "#ffffff", 32)
            text(274, f"Рекорд: {eng.high}", 18, "#ffd84a")
            if eng.record_beaten:
                text(304, "Новый рекорд!", 18, "#4cff6a")
            if blink:
                text(370, "Пробел  —  играть заново", 16, "#ffffff")
            text(398, "Esc  —  назад к выбору игры", 16, "#9fb4ff")
