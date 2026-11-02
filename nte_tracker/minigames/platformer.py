"""Мини-игра «Платформер»."""

import math
import random

from PyQt6.QtCore import pyqtSignal, QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QSizePolicy, QWidget

from .audio import GameSfxMixin


# =====================================================================================
# НОВОЕ: мини-игра «Платформер» (в духе классических 2D-платформеров): три уровня с
# нарастающей сложностью, бег и прыжки с настоящей физикой, блоки «?» с усилениями,
# Супер гриб, Огненный цветок, Звезда неуязвимости, монеты, враги, шипы, ямы, контрольные
# точки и финишный флаг. Логика (PlatformerEngine) не зависит от Qt: физика считается
# маленькими подшагами по времени кадра, поэтому игра идёт одинаково при любой частоте
# таймера. Виджет рисует кадр в paintEvent; цикл — QTimer ~60 кадров/с в основном потоке
# (игра очень лёгкая и не мешает фоновым потокам OCR). Все рисунки — простые фигуры.
# =====================================================================================
PLATFORMER_SOLID = frozenset("#BQU=T")      # твёрдые клетки: земля, кирпич, блок «?», пустой блок, платформа, труба



# описание уровней: номер, название, оформление, ширина, столбец флага, скорость врагов
PLATFORMER_LEVELS = (
    {"name": "1-1", "title": "Зелёные луга", "theme": "day", "cols": 120, "flag": 114, "enemy_speed": 50.0},
    {"name": "1-2", "title": "Тёмная пещера", "theme": "cave", "cols": 130, "flag": 124, "enemy_speed": 62.0},
    {"name": "1-3", "title": "Ночные небеса", "theme": "night", "cols": 140, "flag": 134, "enemy_speed": 76.0},
)



class PlatformerEngine(GameSfxMixin):
    """Чистая логика платформера (без Qt). Мир — сетка клеток TILE×TILE, камера движется
    по горизонтали; все координаты в логических пикселях."""

    TILE = 32
    VIEW_W, VIEW_H = 512, 384
    ROWS = 12
    GRAVITY, JUMP_V, MAX_FALL = 1800.0, 650.0, 640.0
    MAX_SPEED = 200.0
    PW, PH, BIG_PH = 22, 30, 46              # размер героя: обычный и «большой» (после гриба)
    LIVES = 3
    GROUND_ROW = 10
    STAR_TIME = 10.0
    FB = 12                                  # размер огненного шара

    def __init__(self, high_score: int = 0):
        self.high = max(0, int(high_score))
        self.state = "ready"                 # ready / playing / paused / over / won / levelclear
        self.new_game()

    # ---------- новая игра / уровни ----------
    def new_game(self):
        self.score = 0
        self.coins = 0
        self.lives = self.LIVES
        self.level_idx = 0
        self.record_beaten = False
        self.t = 0.0
        self.power = 0                       # 0 — обычный, 1 — Супер гриб, 2 — Огненный цветок
        self.star_t = 0.0
        self.level_bonus = 0
        self.dying = 0.0
        self.load_level()

    @property
    def level_count(self) -> int:
        return len(PLATFORMER_LEVELS)

    @property
    def meta(self) -> dict:
        return PLATFORMER_LEVELS[self.level_idx]

    @property
    def theme(self) -> str:
        return self.meta["theme"]

    def load_level(self):
        self.cols = self.meta["cols"]
        self.grid, self.coin_list, self.enemies, self.qcontent = self._build_level(self.level_idx)
        self.items, self.fireballs = [], []
        self.checkpoint = (2 * self.TILE, self.GROUND_ROW * self.TILE - self.PH)
        self.checkpoint_hit = False
        self.bumps, self.pops, self.particles = {}, [], []
        self.dying = 0.0
        self.fire_cd = 0.0
        self.banner = 2.4                    # заставка «Уровень 1-1» в начале уровня
        self.cam_x = 0.0
        self.ph = self.PH
        self._respawn(invuln=0.0)
        self._try_enlarge()

    def next_level(self):
        """Переход на следующий уровень после финишного флага (усиления сохраняются)."""
        if self.state == "levelclear" and self.level_idx < self.level_count - 1:
            self.level_idx += 1
            self.load_level()
            self.state = "playing"

    def _build_level(self, idx):
        T, R = self.TILE, self.ROWS
        meta = PLATFORMER_LEVELS[idx]
        C = meta["cols"]
        g = [[" "] * C for _ in range(R)]
        qc = {}

        def put(c, r, ch):
            if 0 <= c < C and 0 <= r < R:
                g[r][c] = ch

        def row(c0, c1, r, ch):
            for c in range(c0, c1):
                put(c, r, ch)

        def ground(segs):                                   # земля; промежутки между кусками — ямы
            for a, b in segs:
                row(a, b, 10, "#")
                row(a, b, 11, "#")

        def pipe(c, h):
            for cc in (c, c + 1):
                for r in range(10 - h, 10):
                    put(cc, r, "T")

        def stairs(c0, tops):
            for i, top in enumerate(tops):
                for r in range(top, 10):
                    put(c0 + i, r, "#")

        def block(c, r, ch="Q", content=None):
            put(c, r, ch)
            if content:
                qc[(c, r)] = content

        if idx == 0:                                        # 1-1: мягкий старт
            ground([(0, 28), (30, 52), (55, 78), (81, 100), (102, 120)])
            block(11, 7, "B"); block(12, 7, "Q", "power"); block(13, 7, "B")
            block(14, 7, "Q", "coin"); block(15, 7, "B")
            row(18, 22, 7, "="); row(18, 22, 6, "o")
            row(5, 8, 9, "o"); row(27, 31, 8, "o")
            pipe(38, 2); pipe(42, 2)
            put(57, 9, "C")
            row(60, 62, 9, "^"); row(63, 66, 7, "=")
            row(68, 73, 5, "="); row(68, 73, 4, "o"); row(53, 55, 8, "o")
            row(88, 90, 9, "^"); row(82, 86, 7, "=")
            block(90, 7, "Q", "power"); row(92, 95, 9, "o")
            stairs(105, (9, 8, 7, 6))
            enemy_cols = (20, 36, 45, 66, 72, 91, 94)
        elif idx == 1:                                      # 1-2: пещера, больше ям, шипов и труб
            ground([(0, 22), (24, 42), (45, 62), (64, 84), (87, 104), (106, 130)])
            row(0, 130, 0, "#"); row(0, 130, 1, "#")        # каменный потолок
            for c in (14, 15, 33, 34, 57, 58, 75, 76, 97, 98):
                put(c, 2, "#")
            block(27, 7, "B"); block(28, 7, "Q", "power"); block(29, 7, "B"); block(30, 7, "Q", "coin")
            block(57, 7, "B"); block(58, 7, "Q", "power"); block(59, 7, "B")
            block(77, 7, "B"); block(78, 7, "Q", "star"); block(79, 7, "B")
            pipe(34, 2); pipe(54, 2); pipe(70, 3)
            row(50, 52, 9, "^"); row(74, 76, 9, "^"); row(99, 101, 9, "^")
            row(28, 32, 6, "o"); row(10, 14, 9, "o"); row(42, 45, 8, "o"); row(84, 87, 8, "o")
            row(66, 70, 6, "o"); row(99, 103, 6, "o")
            row(88, 91, 7, "="); row(92, 97, 5, "="); row(92, 97, 4, "o")
            put(66, 9, "C")
            stairs(119, (9, 8, 7, 6))
            enemy_cols = (12, 16, 29, 32, 56, 68, 78, 90, 96, 110, 114, 116)
        else:                                               # 1-3: небо, узкие острова, много врагов и шипов
            ground([(0, 16), (19, 29), (32, 38), (41, 52), (55, 60), (63, 78), (81, 90),
                    (93, 108), (111, 140)])
            block(5, 7, "B"); block(6, 7, "Q", "power"); block(7, 7, "B")
            block(42, 7, "B"); block(43, 7, "Q", "star"); block(44, 7, "B")
            block(68, 7, "B"); block(69, 7, "Q", "power"); block(70, 7, "B")
            block(97, 7, "Q", "coin"); block(98, 7, "Q", "power")
            pipe(20, 2); pipe(124, 2)
            row(12, 14, 9, "^"); row(48, 50, 9, "^"); row(73, 75, 9, "^"); put(86, 9, "^")
            row(118, 120, 9, "^")
            for a0, b0 in ((16, 19), (29, 32), (38, 41), (52, 55), (60, 63), (78, 81), (90, 93), (108, 111)):
                row(a0, b0, 8, "o")                         # монеты дугой над ямами
            row(2, 5, 9, "o"); row(88, 90, 9, "o"); row(127, 130, 9, "o")
            put(64, 9, "C")
            stairs(126, (9, 8, 7, 6))
            enemy_cols = (8, 25, 68, 96, 116, 122, 131)
        flag = meta["flag"]
        for r in range(4, 10):
            put(flag, r, "F")
        coin_list = []
        for r in range(R):
            for c in range(C):
                if g[r][c] == "o":
                    g[r][c] = " "
                    coin_list.append({"x": c * T + 8, "y": r * T + 8, "taken": False})
        sp = meta["enemy_speed"]
        enemies = [{"x": c * T + 3.0, "y": 10 * T - 24.0, "w": 26, "h": 24, "vx": -sp, "vy": 0.0,
                    "alive": True, "squash": 0.0} for c in enemy_cols]
        return g, coin_list, enemies, qc

    def tile(self, c, r) -> str:
        if c < 0 or c >= self.cols:
            return "#"                       # края уровня — невидимые стены
        if r < 0 or r >= self.ROWS:
            return " "
        return self.grid[r][c]

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

    def press_jump(self):
        self.jump_buf = 0.12                 # «запас» нажатия: прыжок сработает чуть раньше приземления

    def fire(self):
        """Огненный шар (клавиши F / Ctrl): только с Огненным цветком, не больше двух на экране."""
        if (self.state == "playing" and self.power == 2 and self.dying <= 0 and self.fire_cd <= 0
                and len(self.fireballs) < 2):
            self.fire_cd = 0.28
            self._snd("fireball")
            self.fireballs.append({"x": self.x + (self.PW if self.facing > 0 else -self.FB),
                                   "y": self.y + self.ph * 0.6, "vx": 330.0 * self.facing,
                                   "vy": 0.0, "t": 0.0, "dead": False})

    def _respawn(self, invuln=2.0):
        self.x = float(self.checkpoint[0])
        self.y = float(self.checkpoint[1] + self.PH - self.ph)
        self.vx = self.vy = 0.0
        self.on_ground = False
        self.coyote = 0.0
        self.jump_buf = 0.0
        self.facing = 1
        self.invuln = invuln
        self.walk_t = 0.0
        self.cam_x = self._cam_target()

    def _cam_target(self) -> float:
        return min(max(0.0, self.x + self.PW / 2 - self.VIEW_W * 0.42), self.cols * self.TILE - self.VIEW_W)

    def _add_score(self, pts: int):
        self.score += pts
        if self.score > self.high:
            self.high = self.score
            self.record_beaten = True

    # ---------- размер героя ----------
    def _try_enlarge(self):
        """Большой герой (Супер гриб / Огненный цветок): вырастает вверх, если над головой есть место."""
        if self.power >= 1 and self.ph == self.PH:
            diff = self.BIG_PH - self.PH
            if not any(ch in PLATFORMER_SOLID for _c, _r, ch in
                       self._tiles_in(self.x, self.y - diff, self.PW, self.BIG_PH)):
                self.y -= diff
                self.ph = self.BIG_PH

    def _shrink(self):
        """Удар по большому герою: усиление пропадает, но жизнь не теряется."""
        self._snd("hit")
        self.power = 0
        if self.ph > self.PH:
            self.y += self.ph - self.PH
            self.ph = self.PH
        self.invuln = 2.0

    # ---------- шаг ----------
    def update(self, dt: float, left: bool, right: bool, jump_held: bool):
        if self.state != "playing":
            return
        dt = min(max(dt, 0.0), 0.05)
        self.t += dt
        self.banner = max(0.0, self.banner - dt)
        n = max(1, math.ceil(dt / 0.008))    # подшаги ≤ 8 мс: герой не пролетает сквозь клетки
        for _ in range(n):
            self._physics(dt / n, left, right, jump_held)
            if self.state != "playing":
                break
        self._step_fx(dt)
        self.cam_x += (self._cam_target() - self.cam_x) * min(1.0, dt * 8)

    def _step_fx(self, dt):
        for k in list(self.bumps):
            self.bumps[k] += dt
            if self.bumps[k] > 0.18:
                del self.bumps[k]
        for p in self.pops:
            p["t"] += dt
        self.pops = [p for p in self.pops if p["t"] < 0.5]
        for p in self.particles:
            p["t"] += dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vy"] += 700 * dt
        self.particles = [p for p in self.particles if p["t"] < 0.6]

    def _physics(self, h, left, right, jump_held):
        if self.dying > 0:                   # анимация потери жизни: герой подлетает и падает
            self.dying -= h
            self.vy += self.GRAVITY * h
            self.y += self.vy * h
            if self.dying <= 0:
                if self.lives <= 0:
                    self.state = "over"
                    self._snd("gameover")
                else:
                    self._respawn()
            return
        self.invuln = max(0.0, self.invuln - h)
        self.star_t = max(0.0, self.star_t - h)
        self.fire_cd = max(0.0, self.fire_cd - h)
        self.jump_buf = max(0.0, self.jump_buf - h)
        self.coyote = self.coyote - h if not self.on_ground else 0.09     # «время койота»: прыжок сразу после края
        # горизонталь: разгон, трение (со звездой герой чуть быстрее)
        top_speed = self.MAX_SPEED * (1.2 if self.star_t > 0 else 1.0)
        target = (int(right) - int(left)) * top_speed
        if target:
            self.facing = 1 if target > 0 else -1
        accel = (1500.0 if self.on_ground else 900.0) if target else (1800.0 if self.on_ground else 250.0)
        if self.vx < target:
            self.vx = min(target, self.vx + accel * h)
        elif self.vx > target:
            self.vx = max(target, self.vx - accel * h)
        # прыжок: высота зависит от того, как долго удерживают клавишу
        if self.jump_buf > 0 and (self.on_ground or self.coyote > 0):
            self.vy = -self.JUMP_V
            self.jump_buf = 0.0
            self.coyote = 0.0
            self.on_ground = False
            self._snd("jump")
        grav = self.GRAVITY * (2.4 if self.vy < 0 and not jump_held else 1.0)
        self.vy = min(self.MAX_FALL, self.vy + grav * h)
        self._move_x(self.vx * h)
        self._move_y(self.vy * h)
        self._try_enlarge()
        if self.on_ground and abs(self.vx) > 10:
            self.walk_t += h * abs(self.vx) / 22.0
        if self.y > self.ROWS * self.TILE + 40:                           # упал в яму
            self._lose_life()
            return
        self._step_enemies(h)
        self._step_items(h)
        self._step_fireballs(h)
        self._interact()

    # ---------- столкновения со сеткой ----------
    def _tiles_in(self, x, y, w, h):
        T = self.TILE
        for r in range(int(y // T), int((y + h - 0.001) // T) + 1):
            for c in range(int(x // T), int((x + w - 0.001) // T) + 1):
                yield c, r, self.tile(c, r)

    def _move_x(self, dx):
        T = self.TILE
        self.x += dx
        for c, r, ch in self._tiles_in(self.x, self.y, self.PW, self.ph):
            if ch in PLATFORMER_SOLID:
                self.x = c * T - self.PW if dx > 0 else (c + 1) * T
                self.vx = 0.0
                break

    def _move_y(self, dy):
        T = self.TILE
        self.y += dy
        self.on_ground = False
        for c, r, ch in self._tiles_in(self.x, self.y, self.PW, self.ph):
            if ch not in PLATFORMER_SOLID:
                continue
            if dy > 0:
                self.y = r * T - self.ph
                self.vy = 0.0
                self.on_ground = True
            elif dy < 0:
                self.y = (r + 1) * T
                self.vy = 0.0
                self._hit_block(c, r)
            break

    def _hit_block(self, c, r):
        """Удар головой снизу: «?» даёт монету или усиление, кирпич ломается (большим героем)."""
        ch = self.tile(c, r)
        T = self.TILE
        if ch == "Q":
            self.grid[r][c] = "U"
            self.bumps[(c, r)] = 0.0
            content = self.qcontent.get((c, r), "coin")
            if content == "coin":
                self.coins += 1
                self._add_score(10)
                self._snd("coin")
                self.pops.append({"x": c * T + T / 2, "y": r * T, "t": 0.0})
            else:
                self._snd("block")
                kind = ("mushroom" if self.power == 0 else "flower") if content == "power" else content
                self._spawn_item(kind, c, r)
        elif ch == "B":
            if self.power >= 1:
                self.grid[r][c] = " "
                self._add_score(10)
                self._snd("explode_small")
                for _ in range(6):
                    self.particles.append({"x": c * T + T / 2, "y": r * T + T / 2,
                                           "vx": random.uniform(-120, 120), "vy": random.uniform(-260, -80), "t": 0.0})
            else:
                self.bumps[(c, r)] = 0.0
                self._snd("block")
        else:
            self.bumps[(c, r)] = 0.0
            self._snd("block")

    def _spawn_item(self, kind, c, r):
        T = self.TILE
        self._snd("item")
        self.items.append({"kind": kind, "x": c * T + 3.0, "y": r * T + 3.0, "y0": r * T + 3.0,
                           "y1": r * T - 26.0, "w": 26, "h": 26, "vx": 0.0, "vy": 0.0, "emerge": 0.5})

    # ---------- враги, предметы, огненные шары ----------
    def _kill_enemy(self, e, pts):
        e["alive"], e["squash"] = False, 0.35
        self._add_score(pts)
        self._snd("stomp")

    def _step_enemies(self, h):
        T = self.TILE
        for e in self.enemies:
            if not e["alive"]:
                e["squash"] -= h
                continue
            if abs(e["x"] - self.x) > self.VIEW_W:      # далёкие враги «спят»
                continue
            e["vy"] = min(self.MAX_FALL, e["vy"] + self.GRAVITY * h)
            e["x"] += e["vx"] * h
            for c, r, ch in self._tiles_in(e["x"], e["y"], e["w"], e["h"]):
                if ch in PLATFORMER_SOLID:
                    e["x"] = c * T - e["w"] if e["vx"] > 0 else (c + 1) * T
                    e["vx"] = -e["vx"]
                    break
            e["y"] += e["vy"] * h
            grounded = False
            for c, r, ch in self._tiles_in(e["x"], e["y"], e["w"], e["h"]):
                if ch in PLATFORMER_SOLID and e["vy"] > 0:
                    e["y"] = r * T - e["h"]
                    e["vy"] = 0.0
                    grounded = True
                    break
            if grounded:                                  # не падать с края платформы
                lead = e["x"] + (e["w"] + 2 if e["vx"] > 0 else -2)
                if self.tile(int(lead // T), int((e["y"] + e["h"] + 2) // T)) not in PLATFORMER_SOLID:
                    e["vx"] = -e["vx"]
            if e["y"] > self.ROWS * T + 60:
                e["alive"], e["squash"] = False, 0.0

    def _step_items(self, h):
        T = self.TILE
        keep = []
        for it in self.items:
            if it["emerge"] > 0:                          # предмет «выезжает» из блока
                it["emerge"] -= h
                k = 1 - max(0.0, it["emerge"]) / 0.5
                it["y"] = it["y0"] + (it["y1"] - it["y0"]) * k
                if it["emerge"] <= 0:
                    it["vx"] = {"mushroom": 70.0, "star": 95.0}.get(it["kind"], 0.0)
                    it["vy"] = -380.0 if it["kind"] == "star" else 0.0
                keep.append(it)
                continue
            it["vy"] = min(self.MAX_FALL, it["vy"] + self.GRAVITY * h)
            it["x"] += it["vx"] * h
            for c, r, ch in self._tiles_in(it["x"], it["y"], it["w"], it["h"]):
                if ch in PLATFORMER_SOLID:
                    it["x"] = c * T - it["w"] if it["vx"] > 0 else (c + 1) * T
                    it["vx"] = -it["vx"]
                    break
            it["y"] += it["vy"] * h
            for c, r, ch in self._tiles_in(it["x"], it["y"], it["w"], it["h"]):
                if ch in PLATFORMER_SOLID:
                    if it["vy"] > 0:
                        it["y"] = r * T - it["h"]
                        it["vy"] = -380.0 if it["kind"] == "star" else 0.0   # звезда подпрыгивает
                    else:
                        it["y"] = (r + 1) * T
                        it["vy"] = 0.0
                    break
            if it["y"] < self.ROWS * T + 60:
                keep.append(it)
        self.items = keep

    def _step_fireballs(self, h):
        T = self.TILE
        for f in self.fireballs:
            f["t"] += h
            f["vy"] += 1500.0 * h
            f["x"] += f["vx"] * h
            if any(ch in PLATFORMER_SOLID for _c, _r, ch in self._tiles_in(f["x"], f["y"], self.FB, self.FB)):
                f["dead"] = True                          # ударился о стену
                continue
            f["y"] += f["vy"] * h
            for c, r, ch in self._tiles_in(f["x"], f["y"], self.FB, self.FB):
                if ch in PLATFORMER_SOLID:
                    if f["vy"] > 0:
                        f["y"] = r * T - self.FB
                        f["vy"] = -250.0                  # шар отскакивает от земли
                    else:
                        f["dead"] = True
                    break
            for e in self.enemies:
                if e["alive"] and self._overlap(f["x"], f["y"], self.FB, self.FB, e["x"], e["y"], e["w"], e["h"]):
                    self._kill_enemy(e, 100)
                    f["dead"] = True
                    break
            if f["t"] > 2.5 or f["y"] > self.ROWS * T + 40 or abs(f["x"] - self.x) > self.VIEW_W:
                f["dead"] = True
        self.fireballs = [f for f in self.fireballs if not f["dead"]]

    @staticmethod
    def _overlap(ax, ay, aw, ah, bx, by, bw, bh):
        return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah

    def _collect(self, it):
        kind = it["kind"]
        self._snd("powerup")
        if kind == "mushroom":
            if self.power == 0:
                self.power = 1
                self._try_enlarge()
            self._add_score(1000)
        elif kind == "flower":
            self.power = 2
            self._try_enlarge()
            self._add_score(1000)
        elif kind == "star":
            self.star_t = self.STAR_TIME
            self._add_score(1000)

    def _interact(self):
        T = self.TILE
        px, py, pw, ph = self.x, self.y, self.PW, self.ph
        for it in list(self.items):                         # усиления
            if it["emerge"] <= 0 and self._overlap(px, py, pw, ph, it["x"], it["y"], it["w"], it["h"]):
                self.items.remove(it)
                self._collect(it)
        for cn in self.coin_list:                           # монеты
            if not cn["taken"] and self._overlap(px, py, pw, ph, cn["x"], cn["y"], 16, 16):
                cn["taken"] = True
                self.coins += 1
                self._add_score(10)
                self._snd("coin")
        for e in self.enemies:                              # враги
            if e["alive"] and self._overlap(px, py, pw, ph, e["x"], e["y"], e["w"], e["h"]):
                if self.star_t > 0:                         # со звездой достаточно коснуться
                    self._kill_enemy(e, 200)
                elif self.vy > 0 and (py + ph) - e["y"] < 18:
                    self._kill_enemy(e, 100)                # прыжок сверху
                    self.vy = -(430.0 if self._jump_pressed_recently() else 300.0)
                else:
                    self._hurt()
                    return
        for c, r, ch in self._tiles_in(px, py, pw, ph):
            if ch == "^" and self.star_t <= 0 and self._overlap(px, py, pw, ph, c * T + 4, r * T + 14, 24, 18):
                self._hurt()                                # шипы
                return
            if ch == "C" and not self.checkpoint_hit:       # контрольная точка
                self.checkpoint_hit = True
                self.checkpoint = (c * T + 5, self.GROUND_ROW * T - self.PH)
                self._add_score(50)
            if ch == "F":                                   # финиш уровня
                self.level_bonus = 500 + 200 * self.lives + 100 * self.level_idx
                self._add_score(self.level_bonus)
                self.state = "levelclear" if self.level_idx < self.level_count - 1 else "won"
                self._snd("win")
                self.vx = 0.0
                return

    def _jump_pressed_recently(self) -> bool:
        return self.jump_buf > 0 or self._held_jump

    _held_jump = False

    def _hurt(self):
        """Удар: со звездой — ничего; большой герой теряет усиление; обычный — жизнь."""
        if self.invuln > 0 or self.dying > 0 or self.star_t > 0:
            return
        if self.power > 0:
            self._shrink()
        else:
            self._lose_life()

    def _lose_life(self):
        if self.dying > 0:
            return
        self.lives = max(0, self.lives - 1)
        self.power = 0
        self.star_t = 0.0
        if self.ph > self.PH:
            self.y += self.ph - self.PH
            self.ph = self.PH
        self.fireballs.clear()
        self.dying = 0.9
        self._snd("death")
        self.vy = -560.0
        self.vx = 0.0



class PlatformerWidget(QWidget):
    """Поле платформера: рисует кадр и обрабатывает клавиши. Цикл — QTimer ~60 кадров/с."""

    closeRequested = pyqtSignal()
    highScoreChanged = pyqtSignal(int)

    # коды клавиш как обычные числа (event.key() возвращает int) — не зависит от типа enum
    K_LEFT, K_RIGHT = int(Qt.Key.Key_Left.value), int(Qt.Key.Key_Right.value)
    K_UP, K_SPACE = int(Qt.Key.Key_Up.value), int(Qt.Key.Key_Space.value)
    K_P, K_ESC = int(Qt.Key.Key_P.value), int(Qt.Key.Key_Escape.value)
    K_F, K_CTRL = int(Qt.Key.Key_F.value), int(Qt.Key.Key_Control.value)

    def __init__(self, high_score: int = 0, parent=None):
        super().__init__(parent)
        self.engine = PlatformerEngine(high_score)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(256, 192)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._keys = set()
        self._t = 0.0
        self._ticks = 0
        self._end_since = None
        self._reported_high = self.engine.high
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

    def _jump_held(self) -> bool:
        return self.K_UP in self._keys or self.K_SPACE in self._keys

    def _tick(self):
        dt = min(self._clock.restart() / 1000.0, 0.05)
        self._t += dt
        self._ticks += 1
        eng = self.engine
        if eng.state == "playing":
            eng._held_jump = self._jump_held()
            eng.update(dt, self.K_LEFT in self._keys, self.K_RIGHT in self._keys, self._jump_held())
            if eng.state in ("over", "won", "levelclear"):
                self._end_since = self._t
                self._keys.clear()
                self._report_high()
            self.update()
        elif self._ticks % 15 == 0:              # мигающие подсказки на экранах паузы / конца
            self.update()

    # ---------- ввод ----------
    @staticmethod
    def _letter(event) -> str:
        """Буква клавиши с учётом русской раскладки: F = А, P = З."""
        return {"f": "f", "а": "f", "p": "p", "з": "p"}.get((event.text() or "").lower(), "")

    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            event.accept()
            return
        key = int(event.key())
        letter = self._letter(event)
        if key in (self.K_LEFT, self.K_RIGHT):
            self._keys.add(key)
        elif key in (self.K_UP, self.K_SPACE):
            self._keys.add(key)
            self._action()
        elif key == self.K_CTRL or letter == "f" or key == self.K_F:
            self.engine.fire()                   # огненный шар (нужен Огненный цветок)
        elif key == self.K_P or letter == "p":
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

    def mousePressEvent(self, event):
        self.setFocus()
        super().mousePressEvent(event)

    def _action(self):
        """Пробел / ↑: начать игру, прыгнуть, продолжить после паузы, перейти на следующий
        уровень или сыграть заново."""
        eng = self.engine
        locked = self._end_since is not None and self._t - self._end_since < 0.6   # защита от случайного пропуска экрана
        if eng.state == "ready":
            eng.start()
            eng.press_jump()
        elif eng.state in ("over", "won"):
            if not locked:
                eng.start()
        elif eng.state == "levelclear":
            if not locked:
                eng.next_level()
        elif eng.state == "paused":
            eng.resume()
        elif eng.state == "playing":
            eng.press_jump()
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
        scale = min(self.width() / eng.VIEW_W, self.height() / eng.VIEW_H)
        p.translate((self.width() - eng.VIEW_W * scale) / 2, (self.height() - eng.VIEW_H * scale) / 2)
        p.scale(scale, scale)
        p.setClipRect(QRectF(0, 0, eng.VIEW_W, eng.VIEW_H))
        self._draw_background(p)
        self._draw_tiles(p)
        self._draw_actors(p)
        self._draw_hud(p)
        self._draw_overlay(p)
        p.setClipping(False)
        p.setPen(QPen(QColor("#3a4a8a"), 2 / max(scale, 0.1)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(0, 0, eng.VIEW_W, eng.VIEW_H))
        p.end()

    def _draw_background(self, p):
        eng = self.engine
        theme = eng.theme
        grad = QLinearGradient(0, 0, 0, eng.VIEW_H)
        top, bottom = {"day": ("#4a7bff", "#a9d8ff"), "cave": ("#0b0f1a", "#222a4a"),
                       "night": ("#090d33", "#3a2a6a")}[theme]
        grad.setColorAt(0.0, QColor(top))
        grad.setColorAt(1.0, QColor(bottom))
        p.fillRect(QRectF(0, 0, eng.VIEW_W, eng.VIEW_H), QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        if theme == "day":
            p.setBrush(QColor("#7fc46a"))                  # дальние холмы (медленный параллакс)
            shift = -(eng.cam_x * 0.3) % 400
            for i in range(-1, 3):
                p.drawEllipse(QRectF(i * 400 + shift, 250, 300, 180))
            p.setBrush(QColor("#ffffffd0"))                # облака
            cshift = -(eng.cam_x * 0.15) % 360
            for i in range(-1, 3):
                cx = i * 360 + cshift
                p.drawEllipse(QRectF(cx + 40, 60, 90, 30))
                p.drawEllipse(QRectF(cx + 70, 46, 60, 36))
                p.drawEllipse(QRectF(cx + 130, 150, 80, 26))
        elif theme == "cave":
            p.setBrush(QColor("#151b33"))                  # силуэты сталагмитов
            shift = -(eng.cam_x * 0.35) % 320
            for i in range(-1, 3):
                x = i * 320 + shift
                p.drawPolygon(QPolygonF([QPointF(x, 330), QPointF(x + 60, 200), QPointF(x + 120, 330)]))
                p.drawPolygon(QPolygonF([QPointF(x + 150, 330), QPointF(x + 190, 250), QPointF(x + 230, 330)]))
            p.setBrush(QColor(120, 160, 255, 70))          # светящиеся кристаллы
            cshift = -(eng.cam_x * 0.5) % 260
            for i in range(-1, 3):
                p.drawEllipse(QRectF(i * 260 + cshift + 50, 120 + 12 * math.sin(self._t + i), 6, 6))
        else:
            p.setBrush(QColor("#ffffff"))                  # звёзды и луна
            for sx, sy in ((30, 40), (120, 90), (200, 30), (290, 110), (380, 50), (460, 100), (70, 160),
                           (250, 170), (420, 190), (160, 220)):
                x = (sx - eng.cam_x * 0.1) % eng.VIEW_W
                p.drawRect(QRectF(x, sy + 2 * math.sin(self._t * 2 + sx), 2, 2))
            p.setBrush(QColor("#fff3c0"))
            p.drawEllipse(QRectF(400 - (eng.cam_x * 0.05) % 60, 50, 44, 44))
            p.setBrush(QColor("#2a1f5a"))
            shift = -(eng.cam_x * 0.3) % 400
            for i in range(-1, 3):
                p.drawEllipse(QRectF(i * 400 + shift, 270, 300, 180))
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_tiles(self, p):
        eng = self.engine
        T = eng.TILE
        c0 = max(0, int(eng.cam_x // T))
        c1 = min(eng.cols - 1, int((eng.cam_x + eng.VIEW_W) // T) + 1)
        p.setPen(Qt.PenStyle.NoPen)
        for r in range(eng.ROWS):
            for c in range(c0, c1 + 1):
                ch = eng.grid[r][c]
                if ch == " ":
                    continue
                x = c * T - eng.cam_x
                y = r * T
                if (c, r) in eng.bumps:                    # «подпрыгивание» блока от удара
                    y -= 6 * math.sin(math.pi * eng.bumps[(c, r)] / 0.18)
                self._draw_tile(p, ch, x, y, c, r)
        for cn in eng.coin_list:                           # монеты
            if cn["taken"]:
                continue
            x = cn["x"] - eng.cam_x
            if -20 < x < eng.VIEW_W + 20:
                w = 5 + 5 * abs(math.sin(self._t * 5 + cn["x"] * 0.05))
                p.setBrush(QColor("#ffd84a"))
                p.drawEllipse(QRectF(x + 8 - w, cn["y"], w * 2, 16))
                p.setBrush(QColor("#fff3a0"))
                p.drawEllipse(QRectF(x + 8 - w * 0.4, cn["y"] + 3, w * 0.8, 10))
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_tile(self, p, ch, x, y, c, r):
        eng = self.engine
        T = eng.TILE
        theme = eng.theme
        rect = QRectF(x, y, T, T)
        if ch == "#":                                      # земля / камень, швы, трава сверху
            fill, shade, cap, cap_shade = {
                "day": ("#9a6a3a", "#7a5228", "#4cb04a", "#357a33"),
                "cave": ("#5a6070", "#3e4352", None, None),
                "night": ("#3a2f6a", "#271f4a", "#5ce1ff", "#2a8aa8"),
            }[theme]
            above = eng.tile(c, r - 1) not in PLATFORMER_SOLID
            p.fillRect(rect, QColor(fill))
            p.fillRect(QRectF(x, y + T - 3, T, 3), QColor(shade))
            p.fillRect(QRectF(x + T - 3, y, 3, T), QColor(shade))
            if above and cap:
                p.fillRect(QRectF(x, y, T, 8), QColor(cap))
                p.fillRect(QRectF(x, y + 8, T, 3), QColor(cap_shade))
            elif above:
                p.fillRect(QRectF(x, y, T, 4), QColor("#8a90a4"))
        elif ch == "B":                                    # кирпич
            p.fillRect(rect, QColor("#c8643a"))
            p.fillRect(QRectF(x, y + 15, T, 2), QColor("#7a3a1e"))
            p.fillRect(QRectF(x + 15, y, 2, 15), QColor("#7a3a1e"))
            p.fillRect(QRectF(x + 7, y + 17, 2, 15), QColor("#7a3a1e"))
            p.fillRect(QRectF(x + 23, y + 17, 2, 15), QColor("#7a3a1e"))
            p.fillRect(QRectF(x, y, T, 2), QColor("#e8946a"))
        elif ch in ("Q", "U"):                             # блок «?» / пустой блок
            used = ch == "U"
            p.fillRect(rect, QColor("#6b5a46" if used else "#ffb81f"))
            p.fillRect(QRectF(x, y, T, 3), QColor("#8a7a64" if used else "#ffe08a"))
            p.fillRect(QRectF(x, y + T - 3, T, 3), QColor("#4a3d2e" if used else "#b36b00"))
            if not used:
                p.setPen(QColor("#7a3a00"))
                p.setFont(self._font(22))
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "?")
                p.setPen(Qt.PenStyle.NoPen)
        elif ch == "=":                                    # платформа
            p.fillRect(QRectF(x, y, T, 14), QColor("#d98b3a"))
            p.fillRect(QRectF(x, y, T, 4), QColor("#f4bb6a"))
            p.fillRect(QRectF(x, y + 12, T, 2), QColor("#8a5420"))
        elif ch == "T":                                    # труба
            top = eng.tile(c, r - 1) != "T"
            p.fillRect(QRectF(x + (0 if top else 3), y, T - (0 if top else 6), T), QColor("#2fb04a"))
            p.fillRect(QRectF(x + (3 if top else 6), y, 5, T), QColor("#7ee08a"))
            if top:
                p.fillRect(QRectF(x, y, T, 3), QColor("#1e7a33"))
        elif ch == "^":                                    # шипы
            p.setBrush(QColor("#d0d6e4"))
            for i in range(3):
                poly = QPolygonF([QPointF(x + i * 11 + 1, y + T), QPointF(x + i * 11 + 6, y + 14),
                                  QPointF(x + i * 11 + 11, y + T)])
                p.drawPolygon(poly)
            p.setBrush(Qt.BrushStyle.NoBrush)
        elif ch == "C":                                    # контрольная точка
            hit = eng.checkpoint_hit
            p.fillRect(QRectF(x + 14, y - 8, 3, T + 8), QColor("#e8e8f0"))
            p.fillRect(QRectF(x + 17, y - 6, 14, 10), QColor("#4cff6a" if hit else "#ff9a3c"))
        elif ch == "F":                                    # финишный флаг
            p.fillRect(QRectF(x + 14, y, 4, T), QColor("#e8e8f0"))
            if eng.tile(c, r - 1) != "F":
                p.setBrush(QColor("#ffd84a"))
                p.drawEllipse(QRectF(x + 11, y - 6, 10, 10))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.fillRect(QRectF(x + 18, y + 3, 24, 14), QColor("#ff4d4d"))

    def _draw_actors(self, p):
        eng = self.engine
        cam = eng.cam_x
        p.setPen(Qt.PenStyle.NoPen)
        for e in eng.enemies:                              # враги-«жуки»
            x = e["x"] - cam
            if x < -40 or x > eng.VIEW_W + 40:
                continue
            if not e["alive"]:
                if e["squash"] > 0:
                    p.setBrush(QColor("#8a4b2a"))
                    p.drawEllipse(QRectF(x - 2, e["y"] + 16, e["w"] + 4, 8))
                continue
            step = int(self._t * 8) % 2
            p.setBrush(QColor("#8a4b2a"))
            p.drawEllipse(QRectF(x, e["y"], e["w"], e["h"] - 4))
            p.setBrush(QColor("#4a2a18"))
            p.drawRect(QRectF(x + 2 + step * 3, e["y"] + e["h"] - 6, 8, 6))
            p.drawRect(QRectF(x + e["w"] - 10 - step * 3, e["y"] + e["h"] - 6, 8, 6))
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QRectF(x + 5, e["y"] + 5, 6, 7))
            p.drawEllipse(QRectF(x + 15, e["y"] + 5, 6, 7))
            p.setBrush(QColor("#000000"))
            p.drawEllipse(QRectF(x + 7, e["y"] + 8, 3, 3))
            p.drawEllipse(QRectF(x + 16, e["y"] + 8, 3, 3))
        for it in eng.items:                               # усиления
            self._draw_item(p, it)
        for pop in eng.pops:                               # вылетающая из блока монета
            k = pop["t"] / 0.5
            p.setBrush(QColor(255, 216, 74, int(255 * (1 - k))))
            p.drawEllipse(QRectF(pop["x"] - eng.cam_x - 6, pop["y"] - 10 - 40 * k, 12, 16))
        for part in eng.particles:                         # осколки кирпича
            p.setBrush(QColor(200, 100, 58, int(255 * (1 - part["t"] / 0.6))))
            p.drawRect(QRectF(part["x"] - cam, part["y"], 6, 6))
        for f in eng.fireballs:                            # огненные шары
            fx, fy = f["x"] - cam, f["y"]
            p.setBrush(QColor(255, 120, 30, 110))
            p.drawEllipse(QRectF(fx - 3 - f["vx"] * 0.02, fy - 2, eng.FB + 6, eng.FB + 4))
            p.setBrush(QColor("#ff7a1e"))
            p.drawEllipse(QRectF(fx, fy, eng.FB, eng.FB))
            p.setBrush(QColor("#ffe27a"))
            p.drawEllipse(QRectF(fx + 3, fy + 3, eng.FB - 6, eng.FB - 6))
        self._draw_player(p)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_item(self, p, it):
        eng = self.engine
        x = it["x"] - eng.cam_x
        y = it["y"]
        if x < -40 or x > eng.VIEW_W + 40:
            return
        p.setPen(Qt.PenStyle.NoPen)
        kind = it["kind"]
        if kind == "mushroom":                             # Супер гриб
            p.setBrush(QColor("#f5deb3"))
            p.drawRect(QRectF(x + 6, y + 14, 14, 12))
            p.setBrush(QColor("#e0342b"))
            p.drawChord(QRectF(x, y, 26, 24), 0, 180 * 16)
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QRectF(x + 4, y + 5, 6, 6))
            p.drawEllipse(QRectF(x + 15, y + 5, 6, 6))
            p.drawEllipse(QRectF(x + 10, y + 1, 6, 5))
            p.setBrush(QColor("#2a1a10"))
            p.drawRect(QRectF(x + 9, y + 17, 3, 4))
            p.drawRect(QRectF(x + 15, y + 17, 3, 4))
        elif kind == "flower":                             # Огненный цветок
            p.setBrush(QColor("#2fb04a"))
            p.drawRect(QRectF(x + 11, y + 14, 4, 12))
            p.drawEllipse(QRectF(x + 2, y + 17, 10, 5))
            p.drawEllipse(QRectF(x + 14, y + 17, 10, 5))
            petal = QColor("#ff5a1e") if int(self._t * 6) % 2 else QColor("#ff9a3c")
            p.setBrush(petal)
            for dx, dy in ((0, 6), (14, 6), (7, 0), (7, 12)):
                p.drawEllipse(QRectF(x + dx, y + dy, 12, 12))
            p.setBrush(QColor("#ffe27a"))
            p.drawEllipse(QRectF(x + 8, y + 7, 10, 10))
        else:                                              # Звезда неуязвимости
            col = QColor.fromHsv(int(self._t * 500) % 360, 120, 255)
            p.setBrush(QColor(255, 240, 120, 70))
            p.drawEllipse(QRectF(x - 4, y - 4, 34, 34))
            pts = []
            for i in range(10):
                ang = -math.pi / 2 + i * math.pi / 5
                rad = 13 if i % 2 == 0 else 5.5
                pts.append(QPointF(x + 13 + math.cos(ang) * rad, y + 14 + math.sin(ang) * rad))
            p.setBrush(col)
            p.drawPolygon(QPolygonF(pts))

    def _draw_player(self, p):
        eng = self.engine
        star = eng.star_t > 0 and (eng.star_t > 2.0 or int(self._t * 10) % 2 == 0)   # в конце звезда мигает
        if eng.dying <= 0 and eng.invuln > 0 and not star and int(self._t * 14) % 2 == 0:
            return                                          # мигание после возрождения / удара
        x = eng.x - eng.cam_x
        y = eng.y
        f = eng.facing
        big = eng.ph > eng.PH
        step = int(eng.walk_t) % 2 if eng.on_ground and abs(eng.vx) > 10 else 0
        cap, suit, shirt = QColor("#e0342b"), QColor("#3b5bdb"), QColor("#ffcf9a")
        if eng.power == 2:                                  # огненный костюм: белая кепка, красный комбинезон
            cap, suit = QColor("#ffffff"), QColor("#e0342b")
        if star:                                            # звезда: переливающиеся цвета и свечение
            hue = int(self._t * 700) % 360
            cap, suit = QColor.fromHsv(hue, 230, 255), QColor.fromHsv((hue + 120) % 360, 230, 255)
            p.setPen(Qt.PenStyle.NoPen)
            glow = 60 + int(50 * math.sin(self._t * 12))
            p.setBrush(QColor(255, 240, 120, glow))
            p.drawEllipse(QRectF(x - 14, y - 10, eng.PW + 28, eng.ph + 20))
        p.save()
        p.translate(x + eng.PW / 2, y)
        p.scale(f * (1.1 if big else 1.0), eng.ph / 30.0)  # большой герой выше (Супер гриб)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(suit)                                    # комбинезон
        p.drawRect(QRectF(-8, 14, 16, 10))
        p.setBrush(QColor("#2a2a3a"))                       # ботинки
        if eng.on_ground:
            p.drawRect(QRectF(-9 + step * 3, 24, 8, 6))
            p.drawRect(QRectF(1 - step * 3, 24, 8, 6))
        else:
            p.drawRect(QRectF(-10, 23, 8, 6))
            p.drawRect(QRectF(2, 25, 8, 5))
        p.setBrush(shirt)                                   # голова
        p.drawRect(QRectF(-7, 3, 14, 12))
        p.setBrush(cap)                                     # кепка
        p.drawRect(QRectF(-8, 0, 16, 6))
        p.drawRect(QRectF(2, 4, 8, 3))
        p.setBrush(QColor("#2a1a10"))
        p.drawRect(QRectF(2, 8, 3, 3))                      # глаз
        p.setBrush(shirt)                                   # рука
        p.drawRect(QRectF(5 if not eng.on_ground else 4, 13 - (4 if not eng.on_ground else 0), 5, 4))
        p.restore()

    def _draw_hud(self, p):
        eng = self.engine
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        p.fillRect(QRectF(0, 0, eng.VIEW_W, 40), QColor(0, 0, 0, 140))
        p.setFont(self._font(13))
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(8, 0, 130, 20), left, f"Счет: {eng.score}")
        p.setPen(QColor("#ffd84a"))
        p.drawText(QRectF(140, 0, 120, 20), left, f"Монеты: {eng.coins}")
        p.setPen(QColor("#ff8080"))
        p.drawText(QRectF(262, 0, 110, 20), left, f"Жизни: {eng.lives}")
        p.setPen(QColor("#b8c8ff"))
        p.drawText(QRectF(eng.VIEW_W - 150, 0, 142, 20), right, f"Рекорд: {eng.high}")
        p.setFont(self._font(12))
        p.setPen(QColor("#9fb4ff"))
        p.drawText(QRectF(8, 20, 160, 20), left, f"Уровень: {eng.level_idx + 1} / {eng.level_count}")
        status = {0: ("Усиление: нет", "#8a93b8"), 1: ("Усиление: Супер гриб", "#ff6b6b"),
                  2: ("Усиление: Огненный цветок", "#ff9a3c")}[eng.power]
        p.setPen(QColor(status[1]))
        p.drawText(QRectF(150, 20, 230, 20), left, status[0])
        if eng.star_t > 0:
            p.setPen(QColor.fromHsv(int(self._t * 500) % 360, 150, 255))
            p.drawText(QRectF(eng.VIEW_W - 130, 20, 122, 20), right, f"Звезда: {eng.star_t:.1f} с")
        elif eng.power == 2:
            p.setPen(QColor("#ffe27a"))
            p.drawText(QRectF(eng.VIEW_W - 170, 20, 162, 20), right, "F / Ctrl — огонь")

    def _draw_overlay(self, p):
        eng = self.engine
        blink = int(self._t * 2) % 2 == 0
        center = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter

        def text(y, s, size, color, h=28):
            p.setFont(self._font(size))
            p.setPen(QColor(color))
            p.drawText(QRectF(0, y, eng.VIEW_W, h), center, s)

        if eng.state == "playing":
            if eng.banner > 0:                             # заставка уровня
                alpha = int(255 * min(1.0, eng.banner / 0.6))
                p.fillRect(QRectF(0, 120, eng.VIEW_W, 100), QColor(0, 0, 0, int(alpha * 0.5)))
                text(128, f"Уровень {eng.meta['name']}", 32, QColor(255, 216, 74, alpha), 44)
                text(176, eng.meta["title"], 18, QColor(255, 255, 255, alpha), 28)
            return
        p.fillRect(QRectF(0, 0, eng.VIEW_W, eng.VIEW_H), QColor(0, 0, 0, 170))
        if eng.state == "ready":
            text(48, "ПЛАТФОРМЕР", 38, "#ffd84a", 50)
            text(110, "← →  —  бег", 14, "#ffffff")
            text(132, "↑ / Пробел  —  прыжок (держите — выше)", 14, "#ffffff")
            text(154, "F / Ctrl  —  огненный шар (с Огненным цветком)", 14, "#ffffff")
            text(176, "P  —  пауза     Esc  —  пауза / выход в меню", 14, "#ffffff")
            text(210, "Блоки «?» дают монеты и усиления:", 14, "#9fb4ff")
            text(232, "Гриб — вы большой и можете принять удар", 13, "#ff8080")
            text(252, "Цветок — стреляете огнём", 13, "#ff9a3c")
            text(272, "Звезда — неуязвимость: враги гибнут от касания", 13, "#ffe27a")
            if blink:
                text(318, "Нажмите Пробел, чтобы начать", 16, "#4cff6a")
        elif eng.state == "paused":
            text(130, "ПАУЗА", 38, "#ffd84a", 50)
            text(195, "P или Пробел  —  продолжить", 15, "#ffffff")
            text(220, "Esc  —  к выбору игры", 15, "#ffffff")
        elif eng.state == "levelclear":                     # экран перехода между уровнями
            nxt = PLATFORMER_LEVELS[eng.level_idx + 1]
            text(52, f"Уровень {eng.meta['name']} пройден!", 28, "#4cff6a", 40)
            text(112, f"Бонус: +{eng.level_bonus}", 18, "#ffd84a", 28)
            text(142, f"Счет: {eng.score}", 18, "#ffffff", 28)
            text(172, f"Монеты: {eng.coins}   Жизни: {eng.lives}", 16, "#b8c8ff", 26)
            text(212, f"Дальше: Уровень {nxt['name']}", 18, "#ffffff", 28)
            text(238, nxt["title"], 16, "#9fb4ff", 26)
            text(266, f"Пройдено уровней: {eng.level_idx + 1} / {eng.level_count}", 14, "#8a93b8", 24)
            if blink:
                text(316, "Пробел  —  следующий уровень", 16, "#ffd84a")
            text(344, "Esc  —  к выбору игры", 14, "#9fb4ff")
        else:
            won = eng.state == "won"
            text(70, "Победа!" if won else "Игра окончена", 36, "#4cff6a" if won else "#ff4a4a", 48)
            if won:
                text(124, f"Все уровни пройдены: {eng.level_count} / {eng.level_count}", 15, "#ffffff", 24)
            else:
                text(124, f"Дошли до уровня: {eng.level_idx + 1} / {eng.level_count}", 15, "#ffffff", 24)
            text(158, f"Счет: {eng.score}", 20, "#ffffff", 30)
            text(190, f"Монеты: {eng.coins}", 16, "#ffd84a")
            text(216, f"Рекорд: {eng.high}", 16, "#b8c8ff")
            if eng.record_beaten:
                text(242, "Новый рекорд!", 16, "#4cff6a")
            if blink:
                text(296, "Пробел  —  играть заново", 15, "#ffffff")
            text(322, "Esc  —  назад к выбору игры", 15, "#9fb4ff")
