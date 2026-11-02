"""Мини-игра «Астероиды»."""

import math
import random

from PyQt6.QtCore import pyqtSignal, QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QSizePolicy, QWidget

from .audio import GameSfxMixin


# =====================================================================================
# НОВОЕ: мини-игра «Астероиды» (классическая аркада с векторной графикой). Логика
# (AsteroidsEngine) не зависит от Qt и считает физику по времени кадра (dt): корабль с
# инерцией, зацикленный экран, лазер, дробление астероидов, волны, жизни. Виджет рисует
# кадр в paintEvent; цикл — QTimer ~60 кадров/с в основном потоке (игра очень лёгкая и не
# мешает фоновым потокам OCR).
# =====================================================================================
MINIGAME_ASTEROIDS_KEY = "minigame_asteroids_highscore"



class AsteroidsEngine(GameSfxMixin):
    """Чистая логика «Астероидов» (без Qt). Поле W×H замкнуто: всё, что вылетает за край,
    появляется с противоположной стороны. Угол корабля 0 — «вверх», растёт по часовой."""

    W, H = 520, 560
    SHIP_R = 10
    ROT_SPEED = 4.4                          # рад/с
    THRUST, MAX_SPEED, DRAG = 280.0, 340.0, 0.25
    BULLET_SPEED, BULLET_LIFE, MAX_BULLETS, FIRE_CD = 520.0, 1.0, 5, 0.2
    SIZES = {3: (40.0, 20), 2: (22.0, 50), 1: (11.0, 100)}   # размер: (радиус, очки)
    LIVES, MAX_LIVES, BONUS_EVERY = 3, 5, 5000

    def __init__(self, high_score: int = 0):
        self.high = max(0, int(high_score))
        self.state = "ready"                 # ready / playing / paused / over
        self.new_game()

    # ---------- подготовка ----------
    def new_game(self):
        self.score = 0
        self.lives = self.LIVES
        self.level = 1
        self.record_beaten = False
        self.next_bonus = self.BONUS_EVERY
        self.t = 0.0
        self.bullets, self.asteroids, self.particles = [], [], []
        self.cooldown = 0.0
        self.banner = 2.0
        self.wave_t = 0.0                    # пауза перед следующей волной (0 — волна идёт)
        self.thrusting = False
        self.respawn_ship(invuln=0.0)
        self.spawn_wave()

    def respawn_ship(self, invuln=2.5):
        """Корабль в центре поля, неподвижный, носом вверх; короткая неуязвимость."""
        self.sx, self.sy = self.W / 2, self.H / 2
        self.sa = 0.0
        self.svx = self.svy = 0.0
        self.ship_alive = True
        self.dead_t = 0.0
        self.invuln = invuln

    def spawn_wave(self):
        count = min(3 + self.level, 10)
        for _ in range(count):
            while True:                      # рождаем астероиды подальше от корабля
                x, y = random.uniform(0, self.W), random.uniform(0, self.H)
                if math.hypot(x - self.sx, y - self.sy) > 170:
                    break
            self.asteroids.append(self._make_asteroid(3, x, y))

    def _make_asteroid(self, size, x, y):
        radius = self.SIZES[size][0]
        base = {3: (40, 70), 2: (70, 110), 1: (100, 150)}[size]
        speed = random.uniform(*base) * (1 + 0.07 * (self.level - 1))
        ang = random.uniform(0, math.tau)
        return {"x": x, "y": y, "vx": math.cos(ang) * speed, "vy": math.sin(ang) * speed,
                "size": size, "r": radius, "ang": random.uniform(0, math.tau),
                "spin": random.uniform(-1.2, 1.2),
                "shape": [random.uniform(0.72, 1.12) for _ in range(11)]}

    # ---------- управление ----------
    def start(self):
        if self.state in ("ready", "over"):
            if self.state == "over":
                self.new_game()
            self.state = "playing"

    def pause(self):
        if self.state == "playing":
            self.state = "paused"

    def resume(self):
        if self.state == "paused":
            self.state = "playing"

    # ---------- вспомогательное ----------
    def _add_score(self, pts: int):
        self.score += pts
        if self.score > self.high:
            self.high = self.score
            self.record_beaten = True
        while self.score >= self.next_bonus:             # дополнительная жизнь каждые 5000 очков
            self.next_bonus += self.BONUS_EVERY
            self.lives = min(self.MAX_LIVES, self.lives + 1)

    def _wrap(self, x, y):
        return x % self.W, y % self.H

    def _burst(self, x, y, count, speed, life=0.8, lines=False):
        for _ in range(count):
            ang = random.uniform(0, math.tau)
            sp = random.uniform(0.3, 1.0) * speed
            self.particles.append({"x": x, "y": y, "vx": math.cos(ang) * sp, "vy": math.sin(ang) * sp,
                                   "t": 0.0, "life": life * random.uniform(0.6, 1.0),
                                   "line": lines, "a": random.uniform(0, math.tau)})

    def _ship_destroyed(self):
        self.lives = max(0, self.lives - 1)
        self._snd("hit")
        self.ship_alive = False
        self.dead_t = 1.2
        self.thrusting = False
        self._burst(self.sx, self.sy, 22, 170, 1.0, lines=True)

    def _safe_to_respawn(self) -> bool:
        cx, cy = self.W / 2, self.H / 2
        return all(math.hypot(a["x"] - cx, a["y"] - cy) > a["r"] + 90 for a in self.asteroids)

    # ---------- один шаг игры ----------
    def update(self, dt: float, left: bool, right: bool, thrust: bool, fire: bool):
        if self.state != "playing":
            return
        dt = min(max(dt, 0.0), 0.05)
        self.t += dt
        self.banner = max(0.0, self.banner - dt)
        for p in self.particles:
            p["t"] += dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
        self.particles = [p for p in self.particles if p["t"] < p["life"]]
        self._step_ship(dt, left, right, thrust, fire)
        if self.state != "playing":
            return
        self._step_bullets(dt)
        for a in self.asteroids:
            a["x"], a["y"] = self._wrap(a["x"] + a["vx"] * dt, a["y"] + a["vy"] * dt)
            a["ang"] += a["spin"] * dt
        self._collide_bullets()
        self._collide_ship()
        self._step_waves(dt)

    def _step_ship(self, dt, left, right, thrust, fire):
        if not self.ship_alive:
            self.dead_t -= dt
            if self.dead_t <= 0:
                if self.lives <= 0:
                    self.state = "over"
                    self._snd("gameover")
                elif self._safe_to_respawn() or self.dead_t < -3.0:
                    self.respawn_ship()
            return
        self.invuln = max(0.0, self.invuln - dt)
        self.sa += (int(right) - int(left)) * self.ROT_SPEED * dt
        self.thrusting = thrust
        if thrust:                                        # тяга: ускорение вдоль носа корабля
            self._snd("thrust")
            self.svx += math.sin(self.sa) * self.THRUST * dt
            self.svy -= math.cos(self.sa) * self.THRUST * dt
            if random.random() < 0.7:                     # искры двигателя
                self.particles.append({"x": self.sx - math.sin(self.sa) * 11, "y": self.sy + math.cos(self.sa) * 11,
                                       "vx": self.svx - math.sin(self.sa) * 90 + random.uniform(-25, 25),
                                       "vy": self.svy + math.cos(self.sa) * 90 + random.uniform(-25, 25),
                                       "t": 0.0, "life": 0.25, "line": False, "a": 0.0})
        drag = max(0.0, 1.0 - self.DRAG * dt)             # лёгкое затухание: инерция остаётся заметной
        self.svx *= drag
        self.svy *= drag
        speed = math.hypot(self.svx, self.svy)
        if speed > self.MAX_SPEED:
            self.svx *= self.MAX_SPEED / speed
            self.svy *= self.MAX_SPEED / speed
        self.sx, self.sy = self._wrap(self.sx + self.svx * dt, self.sy + self.svy * dt)
        self.cooldown = max(0.0, self.cooldown - dt)
        if fire and self.cooldown <= 0 and len(self.bullets) < self.MAX_BULLETS:
            dx, dy = math.sin(self.sa), -math.cos(self.sa)
            self.bullets.append({"x": self.sx + dx * 12, "y": self.sy + dy * 12,
                                 "vx": dx * self.BULLET_SPEED + self.svx * 0.5,
                                 "vy": dy * self.BULLET_SPEED + self.svy * 0.5, "t": 0.0})
            self.cooldown = self.FIRE_CD
            self._snd("shoot")

    def _step_bullets(self, dt):
        keep = []
        for b in self.bullets:
            b["t"] += dt
            b["x"], b["y"] = self._wrap(b["x"] + b["vx"] * dt, b["y"] + b["vy"] * dt)
            if b["t"] < self.BULLET_LIFE:
                keep.append(b)
        self.bullets = keep

    def _collide_bullets(self):
        for b in list(self.bullets):
            for a in self.asteroids:
                if math.hypot(b["x"] - a["x"], b["y"] - a["y"]) < a["r"] * 0.92 + 2:
                    self.bullets.remove(b)
                    self._split(a)
                    break

    def _split(self, a):
        """Попадание: большой астероид -> два средних, средний -> два малых, малый исчезает."""
        self.asteroids.remove(a)
        self._add_score(self.SIZES[a["size"]][1])
        self._snd("explode" if a["size"] >= 3 else "explode_small")
        self._burst(a["x"], a["y"], 6 + 3 * a["size"], 90 + 30 * a["size"], 0.7)
        if a["size"] > 1:
            for _ in range(2):
                child = self._make_asteroid(a["size"] - 1, a["x"], a["y"])
                self.asteroids.append(child)

    def _collide_ship(self):
        if not self.ship_alive or self.invuln > 0:
            return
        for a in self.asteroids:
            if math.hypot(self.sx - a["x"], self.sy - a["y"]) < a["r"] * 0.9 + self.SHIP_R * 0.8:
                self._ship_destroyed()
                return

    def _step_waves(self, dt):
        if self.asteroids:
            return
        if self.wave_t <= 0:
            self.wave_t = 1.6                             # волна уничтожена — короткая пауза
            return
        self.wave_t -= dt
        if self.wave_t <= 0:
            self.level += 1
            self.banner = 2.0
            self._snd("win")
            self.spawn_wave()



class AsteroidsWidget(QWidget):
    """Поле «Астероидов»: рисует кадр и обрабатывает клавиши. Цикл — QTimer ~60 кадров/с."""

    closeRequested = pyqtSignal()
    highScoreChanged = pyqtSignal(int)

    # коды клавиш как обычные числа (event.key() возвращает int) — не зависит от типа enum
    K_LEFT, K_RIGHT = int(Qt.Key.Key_Left.value), int(Qt.Key.Key_Right.value)
    K_UP, K_SPACE = int(Qt.Key.Key_Up.value), int(Qt.Key.Key_Space.value)
    K_P, K_ESC = int(Qt.Key.Key_P.value), int(Qt.Key.Key_Escape.value)
    K_A, K_D, K_W = int(Qt.Key.Key_A.value), int(Qt.Key.Key_D.value), int(Qt.Key.Key_W.value)
    # буквы русской раскладки на тех же клавишах: Ф = A, В = D, Ц = W, З = P
    RU_LETTERS = {"ф": "L", "в": "R", "ц": "T", "з": "P"}

    def __init__(self, high_score: int = 0, parent=None):
        super().__init__(parent)
        self.engine = AsteroidsEngine(high_score)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(240, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._held = {}                          # код клавиши -> действие ("L", "R", "T", "F")
        self._t = 0.0
        self._ticks = 0
        self._end_since = None
        self._reported_high = self.engine.high
        stars = random.Random(5)
        self._stars = [(stars.uniform(0, AsteroidsEngine.W), stars.uniform(0, AsteroidsEngine.H),
                        stars.choice((1, 1, 2))) for _ in range(70)]
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
        self._held.clear()

    def shutdown(self):
        """Останавливает таймер и отключает его — после этого виджет безопасно удалять."""
        self._timer.stop()
        try:
            self._timer.timeout.disconnect(self._tick)
        except (TypeError, RuntimeError):
            pass
        self._held.clear()
        self._report_high()

    def pause(self):
        self._held.clear()
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
            acts = set(self._held.values())
            eng.update(dt, "L" in acts, "R" in acts, "T" in acts, "F" in acts)
            if eng.state == "over":
                self._end_since = self._t
                self._held.clear()
                self._report_high()
            self.update()
        elif self._ticks % 15 == 0:              # мигающие подсказки на экранах паузы / конца
            self.update()

    # ---------- ввод ----------
    def _action_for(self, event):
        key = int(event.key())
        if key in (self.K_LEFT, self.K_A):
            return "L"
        if key in (self.K_RIGHT, self.K_D):
            return "R"
        if key in (self.K_UP, self.K_W):
            return "T"
        if key == self.K_SPACE:
            return "F"
        if key == self.K_P:
            return "P"
        return self.RU_LETTERS.get((event.text() or "").lower())

    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            event.accept()
            return
        key = int(event.key())
        act = self._action_for(event)
        if act in ("L", "R", "T"):
            self._held[key] = act
        elif act == "F":
            self._held[key] = act
            self._space()
        elif act == "P":
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
            self._held.pop(int(event.key()), None)
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.pause()                             # потеряли фокус — автопауза
        super().focusOutEvent(event)

    def mousePressEvent(self, event):
        self.setFocus()
        super().mousePressEvent(event)

    def _space(self):
        """Пробел: начать игру, продолжить после паузы или сыграть заново (в игре — огонь)."""
        eng = self.engine
        if eng.state == "ready":
            eng.start()
        elif eng.state == "over":
            if self._end_since is None or self._t - self._end_since >= 0.6:
                eng.start()
        elif eng.state == "paused":
            eng.resume()
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
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#05060d"))
        scale = min(self.width() / eng.W, self.height() / eng.H)
        p.translate((self.width() - eng.W * scale) / 2, (self.height() - eng.H * scale) / 2)
        p.scale(scale, scale)
        p.setClipRect(QRectF(0, 0, eng.W, eng.H))
        p.fillRect(QRectF(0, 0, eng.W, eng.H), QColor("#03040a"))
        p.setPen(Qt.PenStyle.NoPen)
        for sx, sy, sz in self._stars:           # мерцающие звёзды
            tw = 90 + int(70 * math.sin(self._t * 2 + sx))
            p.fillRect(QRectF(sx, sy, sz, sz), QColor(tw + 60, tw + 60, 255))
        self._draw_world(p)
        self._draw_hud(p)
        self._draw_overlay(p)
        p.setClipping(False)
        p.setPen(QPen(QColor("#3a4a8a"), 2 / max(scale, 0.1)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(0, 0, eng.W, eng.H))
        p.end()

    def _wrapped(self, x, y, r):
        """Позиции для рисования с учётом зацикленного экрана: у края фигура видна с обеих сторон."""
        eng = self.engine
        for dx in (-eng.W, 0, eng.W):
            for dy in (-eng.H, 0, eng.H):
                if -r <= x + dx <= eng.W + r and -r <= y + dy <= eng.H + r:
                    yield x + dx, y + dy

    def _ship_polygon(self, x, y, ang, size=1.0):
        pts = ((0, -13), (-9, 10), (0, 5), (9, 10))
        ca, sa = math.cos(ang), math.sin(ang)
        return QPolygonF([QPointF(x + (px * ca - py * sa) * size, y + (px * sa + py * ca) * size) for px, py in pts])

    def _draw_world(self, p):
        eng = self.engine
        p.setBrush(Qt.BrushStyle.NoBrush)
        for a in eng.asteroids:                  # астероиды — неровные контуры
            for x, y in self._wrapped(a["x"], a["y"], a["r"]):
                n = len(a["shape"])
                poly = QPolygonF([QPointF(x + math.cos(a["ang"] + i * math.tau / n) * a["r"] * a["shape"][i],
                                          y + math.sin(a["ang"] + i * math.tau / n) * a["r"] * a["shape"][i])
                                  for i in range(n)])
                p.setPen(QPen(QColor("#c8d4ff" if a["size"] == 3 else "#9fb4ff" if a["size"] == 2 else "#7da2ff"), 2))
                p.drawPolygon(poly)
        for b in eng.bullets:                    # лазерные выстрелы
            p.setPen(QPen(QColor("#ff6b6b"), 3))
            for x, y in self._wrapped(b["x"], b["y"], 4):
                p.drawPoint(QPointF(x, y))
                p.setPen(QPen(QColor(255, 107, 107, 110), 6))
                p.drawPoint(QPointF(x, y))
                p.setPen(QPen(QColor("#ff6b6b"), 3))
        for part in eng.particles:               # искры и обломки
            k = 1 - part["t"] / part["life"]
            p.setPen(QPen(QColor(255, 220, 140, int(255 * k)), 2))
            if part["line"]:
                dx, dy = math.cos(part["a"]) * 6, math.sin(part["a"]) * 6
                p.drawLine(QPointF(part["x"] - dx, part["y"] - dy), QPointF(part["x"] + dx, part["y"] + dy))
            else:
                p.drawPoint(QPointF(part["x"], part["y"]))
        if eng.ship_alive:                       # корабль (мигает при неуязвимости)
            if not (eng.invuln > 0 and int(self._t * 14) % 2 == 0):
                for x, y in self._wrapped(eng.sx, eng.sy, 14):
                    p.setPen(QPen(QColor("#4cff6a"), 2))
                    p.setBrush(QColor(76, 255, 106, 40))
                    p.drawPolygon(self._ship_polygon(x, y, eng.sa))
                    if eng.thrusting and int(self._t * 30) % 2 == 0:       # пламя двигателя
                        ca, sa = math.cos(eng.sa), math.sin(eng.sa)
                        tip = (0, 20)
                        p.setPen(QPen(QColor("#ffb84a"), 2))
                        p.drawLine(QPointF(x + (-3) * ca - 7 * sa, y + (-3) * sa + 7 * ca),
                                   QPointF(x + tip[0] * ca - tip[1] * sa, y + tip[0] * sa + tip[1] * ca))
                        p.drawLine(QPointF(x + 3 * ca - 7 * sa, y + 3 * sa + 7 * ca),
                                   QPointF(x + tip[0] * ca - tip[1] * sa, y + tip[0] * sa + tip[1] * ca))
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
        p.setPen(QColor("#ff8080"))
        p.drawText(QRectF(12, 28, 120, 18), left, f"Жизни: {eng.lives}")
        for i in range(max(0, eng.lives)):       # жизни — маленькие кораблики
            p.setPen(QPen(QColor("#4cff6a"), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolygon(self._ship_polygon(106 + i * 18, 38, 0.0, 0.6))
        p.setPen(QColor("#9fb4ff"))
        p.drawText(QRectF(eng.W - 232, 28, 220, 18), right, f"Уровень: {eng.level}")

    def _draw_overlay(self, p):
        eng = self.engine
        blink = int(self._t * 2) % 2 == 0
        center = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter

        def text(y, s, size, color, h=30):
            p.setFont(self._font(size))
            p.setPen(QColor(color))
            p.drawText(QRectF(0, y, eng.W, h), center, s)

        if eng.state == "playing":
            if eng.banner > 0:
                alpha = int(255 * min(1.0, eng.banner / 0.6))
                text(200, f"Уровень {eng.level}", 30, QColor(255, 216, 74, alpha), 40)
            elif eng.ship_alive is False and eng.lives > 0 and blink:
                text(250, "Корабль восстанавливается…", 14, "#9fb4ff", 24)
            return
        p.fillRect(QRectF(0, 0, eng.W, eng.H), QColor(0, 0, 0, 165))
        if eng.state == "ready":
            text(130, "АСТЕРОИДЫ", 44, "#7da2ff", 56)
            text(220, "← →  или  A D  —  поворот", 16, "#ffffff")
            text(246, "↑  или  W  —  тяга (корабль скользит по инерции)", 16, "#ffffff")
            text(272, "Пробел  —  огонь", 16, "#ffffff")
            text(298, "P  —  пауза     Esc  —  пауза / выход в меню", 16, "#ffffff")
            text(330, "Края экрана замкнуты: вылетел справа — появился слева", 13, "#9fb4ff")
            if blink:
                text(400, "Нажмите Пробел, чтобы начать", 17, "#ffd84a")
        elif eng.state == "paused":
            text(210, "ПАУЗА", 38, "#ffd84a", 50)
            text(280, "P или Пробел  —  продолжить", 16, "#ffffff")
            text(306, "Esc  —  к выбору игры", 16, "#ffffff")
        else:
            text(170, "Игра окончена", 36, "#ff4a4a", 48)
            text(240, f"Счет: {eng.score}", 22, "#ffffff", 32)
            text(274, f"Рекорд: {eng.high}", 18, "#ffd84a")
            text(300, f"Достигнут уровень: {eng.level}", 15, "#9fb4ff", 24)
            if eng.record_beaten:
                text(328, "Новый рекорд!", 18, "#4cff6a")
            if blink:
                text(390, "Пробел  —  играть заново", 16, "#ffffff")
            text(418, "Esc  —  назад к выбору игры", 16, "#9fb4ff")
