"""Мини-игра «Захватчики»."""

import math
import random

from PyQt6.QtCore import pyqtSignal, QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QSizePolicy, QWidget

from .audio import GameSfxMixin


# Пиксельные спрайты (# — закрашенный пиксель). У пришельцев по два кадра анимации.
SPRITE_SQUID = (
    ("...##...", "..####..", ".######.", "##.##.##", "########", ".#.##.#.", "#......#", ".#....#."),
    ("...##...", "..####..", ".######.", "##.##.##", "########", "..#..#..", ".#.##.#.", "#.#..#.#"),
)



SPRITE_CRAB = (
    ("..#.....#..", "...#...#...", "..#######..", ".##.###.##.",
     "###########", "#.#######.#", "#.#.....#.#", "...##.##..."),
    ("..#.....#..", "#..#...#..#", "#.#######.#", "###.###.###",
     "###########", ".#########.", "..#.....#..", ".#.......#."),
)



SPRITE_OCTOPUS = (
    ("....####....", ".##########.", "############", "###..##..###",
     "############", "...##..##...", "..##.##.##..", "##........##"),
    ("....####....", ".##########.", "############", "###..##..###",
     "############", "..###..###..", ".##..##..##.", "..##....##.."),
)



SPRITE_PLAYER = (
    "......#......", ".....###.....", ".....###.....", ".###########.",
    "#############", "#############", "#############", "#############",
)



SPRITE_UFO = (
    ".....######.....", "...##########...", "..############..", ".##.##.##.##.##.",
    "################", "..###..##..###..", "...#........#...",
)



SHIELD_PATTERN = (
    "..#######..", ".#########.", "###########", "###########",
    "###########", "###.....###", "###.....###", "###.....###",
)



class InvadersEngine(GameSfxMixin):
    """Чистая логика «Космических захватчиков» (без Qt). Координаты — в логических пикселях
    поля W×H; виджет сам масштабирует поле под размер окна."""

    W, H = 480, 560
    COLS, ROWS = 8, 5
    DX, DY = 44, 34                  # шаг сетки пришельцев
    ALIEN_W, ALIEN_H = 36, 24
    PLAYER_W, PLAYER_H, PLAYER_Y = 39, 24, 516
    TOP = 48                         # высота строки со счётом
    SHIELD_Y, SHIELD_CELL = 428, 5
    POINTS = (30, 20, 20, 10, 10)    # очки за ряд сверху вниз

    def __init__(self, high_score: int = 0):
        self.high = max(0, int(high_score))
        self.state = "ready"         # ready / playing / paused / over
        self.new_game()

    # ---------- подготовка ----------
    def new_game(self):
        self.score = 0
        self.lives = 3
        self.level = 1
        self.record_beaten = False
        self.player_x = self.W / 2
        self.bullets, self.ebullets, self.blasts = [], [], []
        self.cooldown = 0.0
        self.invuln = 0.0
        self.banner = 0.0
        self.ufo = None
        self.ufo_t = random.uniform(10, 18)
        self.fire_t = 1.0
        self.spawn_wave()
        self.make_shields()

    def spawn_wave(self):
        self.aliens = [{"c": c, "r": r, "alive": True}
                       for r in range(self.ROWS) for c in range(self.COLS)]
        self.total = len(self.aliens)
        self.ox = (self.W - ((self.COLS - 1) * self.DX + self.ALIEN_W)) / 2
        self.oy = self.TOP + 26 + min(self.level - 1, 5) * 14
        self.dir = 1
        self.anim = 0.0
        self.bullets.clear()
        self.ebullets.clear()

    def make_shields(self):
        cell = self.SHIELD_CELL
        width = len(SHIELD_PATTERN[0]) * cell
        self.shields = []
        for i in range(4):
            x = self.W / 4 * (i + 0.5) - width / 2
            cells = {(cx, cy) for cy, row in enumerate(SHIELD_PATTERN)
                     for cx, ch in enumerate(row) if ch == "#"}
            self.shields.append({"x": x, "y": self.SHIELD_Y, "cells": cells})

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
    def alien_pos(self, a):
        return self.ox + a["c"] * self.DX, self.oy + a["r"] * self.DY

    def alive_aliens(self):
        return [a for a in self.aliens if a["alive"]]

    @staticmethod
    def _hit(ax, ay, aw, ah, bx, by, bw, bh):
        return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah

    def _add_score(self, pts):
        self.score += pts
        if self.score > self.high:
            self.high = self.score
            self.record_beaten = True

    def _shield_hit(self, bx, by, bw, bh, erode=True) -> bool:
        """Попадание в щит: разрушает клетку (и соседнюю) под пулей."""
        cell = self.SHIELD_CELL
        for sh in self.shields:
            w, h = len(SHIELD_PATTERN[0]) * cell, len(SHIELD_PATTERN) * cell
            if not self._hit(sh["x"], sh["y"], w, h, bx, by, bw, bh):
                continue
            for cx, cy in list(sh["cells"]):
                if self._hit(sh["x"] + cx * cell, sh["y"] + cy * cell, cell, cell, bx, by, bw, bh):
                    sh["cells"].discard((cx, cy))
                    if erode:
                        for ddx, ddy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                            if random.random() < 0.35:
                                sh["cells"].discard((cx + ddx, cy + ddy))
                    return True
        return False

    def _player_hit(self):
        self.lives -= 1
        self.blasts.append({"x": self.player_x, "y": self.PLAYER_Y + 10, "t": 0.0, "c": "p"})
        self.ebullets.clear()
        self.invuln = 1.8
        if self.lives <= 0:
            self.state = "over"
            self._snd("gameover")
        else:
            self._snd("hit")

    # ---------- один шаг игры ----------
    def update(self, dt: float, left: bool, right: bool, fire: bool):
        if self.state != "playing":
            return
        dt = min(max(dt, 0.0), 0.05)
        for b in self.blasts:
            b["t"] += dt
        self.blasts = [b for b in self.blasts if b["t"] < 0.4]
        self.invuln = max(0.0, self.invuln - dt)
        if self.banner > 0:                      # пауза между волнами: двигается только корабль
            self.banner -= dt
            self._move_player(dt, left, right)
            return
        self._move_player(dt, left, right)
        self.cooldown = max(0.0, self.cooldown - dt)
        if fire and self.cooldown <= 0 and len(self.bullets) < 2:
            self.bullets.append({"x": self.player_x, "y": self.PLAYER_Y - 4})
            self.cooldown = 0.32
            self._snd("shoot")
        self._step_player_bullets(dt)
        self._step_aliens(dt)
        self._step_enemy_fire(dt)
        self._step_enemy_bullets(dt)
        self._step_ufo(dt)
        if self.state != "playing":
            return
        if not self.alive_aliens():              # волна уничтожена
            self.level += 1
            self._add_score(100)
            self._snd("win")
            self.spawn_wave()
            self.banner = 1.4
            self.invuln = 0.0

    def _move_player(self, dt, left, right):
        speed = 270.0
        if left and not right:
            self.player_x -= speed * dt
        elif right and not left:
            self.player_x += speed * dt
        half = self.PLAYER_W / 2
        self.player_x = min(self.W - 10 - half, max(10 + half, self.player_x))

    def _step_player_bullets(self, dt):
        keep = []
        for b in self.bullets:
            b["y"] -= 520.0 * dt
            bx, by, bw, bh = b["x"] - 1.5, b["y"], 3, 12
            gone = False
            for a in self.aliens:
                if not a["alive"]:
                    continue
                ax, ay = self.alien_pos(a)
                if self._hit(ax, ay, self.ALIEN_W, self.ALIEN_H, bx, by, bw, bh):
                    a["alive"] = False
                    self._add_score(self.POINTS[a["r"]])
                    self._snd("explode_small")
                    self.blasts.append({"x": ax + self.ALIEN_W / 2, "y": ay + self.ALIEN_H / 2,
                                        "t": 0.0, "c": "a"})
                    gone = True
                    break
            if not gone and self.ufo and self._hit(self.ufo["x"], 52, 48, 21, bx, by, bw, bh):
                self._add_score(self.ufo["pts"])
                self._snd("ufo")
                self.blasts.append({"x": self.ufo["x"] + 24, "y": 62, "t": 0.0, "c": "u"})
                self.ufo = None
                gone = True
            if not gone and self._shield_hit(bx, by, bw, bh):
                gone = True
            if not gone and by + bh > self.TOP:
                keep.append(b)
        self.bullets = keep

    def _step_aliens(self, dt):
        alive = self.alive_aliens()
        if not alive:
            return
        n = len(alive)
        speed = 28 + self.level * 5 + (1 - n / self.total) * 150 + (80 if n == 1 else 0)
        move = self.dir * speed * dt
        left = self.ox + min(a["c"] for a in alive) * self.DX
        right = self.ox + max(a["c"] for a in alive) * self.DX + self.ALIEN_W
        if right + move > self.W - 12 or left + move < 12:
            self.dir = -self.dir
            self.oy += 14
        else:
            self.ox += move
        self.anim += abs(move)
        low = max(self.oy + a["r"] * self.DY + self.ALIEN_H for a in alive)
        if low > self.SHIELD_Y:                  # пришельцы «стирают» щиты, до которых дошли
            for a in alive:
                ax, ay = self.alien_pos(a)
                if ay + self.ALIEN_H > self.SHIELD_Y:
                    self._shield_hit(ax, ay, self.ALIEN_W, self.ALIEN_H, erode=False)
        if low >= self.PLAYER_Y - 2:             # вторжение — игра окончена
            self.lives = 0
            self.state = "over"
            self._snd("gameover")

    def _step_enemy_fire(self, dt):
        self.fire_t -= dt
        if self.fire_t > 0:
            return
        limit = min(6, 2 + self.level // 2)
        self.fire_t = random.uniform(0.4, 1.0) * max(0.3, 1.2 - 0.09 * self.level)
        if len(self.ebullets) >= limit:
            return
        columns = {}
        for a in self.alive_aliens():
            if a["c"] not in columns or a["r"] > columns[a["c"]]["r"]:
                columns[a["c"]] = a
        if columns:
            a = random.choice(list(columns.values()))
            ax, ay = self.alien_pos(a)
            self.ebullets.append({"x": ax + self.ALIEN_W / 2, "y": ay + self.ALIEN_H})

    def _step_enemy_bullets(self, dt):
        keep = []
        speed = 190.0 + self.level * 12
        for b in self.ebullets:
            b["y"] += speed * dt
            bx, by, bw, bh = b["x"] - 1.5, b["y"], 3, 12
            if (self.invuln <= 0 and self._hit(self.player_x - self.PLAYER_W / 2, self.PLAYER_Y,
                                               self.PLAYER_W, self.PLAYER_H, bx, by, bw, bh)):
                self._player_hit()
                return
            if self._shield_hit(bx, by, bw, bh) or by > self.H:
                continue
            keep.append(b)
        self.ebullets = keep

    def _step_ufo(self, dt):
        if self.ufo is None:
            self.ufo_t -= dt
            if self.ufo_t <= 0 and len(self.alive_aliens()) > 3:
                d = random.choice((-1, 1))
                self.ufo = {"x": -48.0 if d > 0 else float(self.W), "d": d,
                            "pts": random.choice((50, 100, 150, 300))}
                self.ufo_t = random.uniform(15, 25)
            return
        self.ufo["x"] += self.ufo["d"] * 110.0 * dt
        if self.ufo["x"] < -60 or self.ufo["x"] > self.W + 12:
            self.ufo = None



class InvadersWidget(QWidget):
    """Поле игры: рисует кадр и обрабатывает клавиши. Игровой цикл — QTimer ~60 к/с."""

    closeRequested = pyqtSignal()
    highScoreChanged = pyqtSignal(int)

    COL_PLAYER, COL_UFO = QColor("#4cff6a"), QColor("#ff4a4a")
    COL_ALIEN = (QColor("#ff5cf0"), QColor("#5ce1ff"), QColor("#5ce1ff"),
                 QColor("#ffd84a"), QColor("#ffd84a"))

    def __init__(self, high_score: int = 0, parent=None):
        super().__init__(parent)
        self.engine = InvadersEngine(high_score)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(240, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._keys = set()
        self._t = 0.0
        self._over_since = None
        self._reported_high = self.engine.high
        self._ticks = 0
        stars = random.Random(7)
        self._stars = [(stars.uniform(0, InvadersEngine.W), stars.uniform(0, InvadersEngine.H),
                        stars.choice((1, 1, 2))) for _ in range(60)]
        self._sprite_px = 3
        self._sprites = self._build_sprites()
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)   # ровные ~60 кадров в секунду
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    # ---------- спрайты ----------
    @staticmethod
    def _pixmap(rows, color, px=3):
        pm = QPixmap(len(rows[0]) * px, len(rows) * px)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch == "#":
                    p.fillRect(x * px, y * px, px, px, color)
        p.end()
        pm.setDevicePixelRatio(px / 3.0)         # логический размер спрайта не зависит от px
        return pm

    def _build_sprites(self, px=3):
        kinds = (SPRITE_SQUID, SPRITE_CRAB, SPRITE_CRAB, SPRITE_OCTOPUS, SPRITE_OCTOPUS)
        return {
            "alien": [[self._pixmap(frame, self.COL_ALIEN[r], px) for frame in kinds[r]]
                      for r in range(InvadersEngine.ROWS)],
            "player": self._pixmap(SPRITE_PLAYER, self.COL_PLAYER, px),
            "ufo": self._pixmap(SPRITE_UFO, self.COL_UFO, px),
        }

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
            eng.update(dt, Qt.Key.Key_Left in self._keys, Qt.Key.Key_Right in self._keys,
                       Qt.Key.Key_Up in self._keys or Qt.Key.Key_Space in self._keys)
            if eng.state == "over":
                self._over_since = self._t
                self._keys.clear()
                self._report_high()
            self.update()
        elif self._ticks % 15 == 0:              # мигающие подсказки на экранах паузы / конца
            self.update()

    # ---------- клавиши ----------
    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            event.accept()
            return
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self._keys.add(key)
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Space):
            self._keys.add(key)
            self._action()
        elif key == Qt.Key.Key_P:
            if self.engine.state == "playing":
                self.engine.pause()
            elif self.engine.state == "paused":
                self.engine.resume()
            self.update()
        elif key == Qt.Key.Key_Escape:
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
            self._keys.discard(event.key())
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.pause()                             # потеряли фокус — автопауза
        super().focusOutEvent(event)

    def _action(self):
        eng = self.engine
        if eng.state == "ready":
            eng.start()
        elif eng.state == "over":
            if self._over_since is None or self._t - self._over_since >= 0.6:
                eng.start()
        elif eng.state == "paused":
            eng.resume()
        self.update()

    # ---------- рисование ----------
    def paintEvent(self, event):
        eng = self.engine
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#05060d"))
        scale = min(self.width() / eng.W, self.height() / eng.H)
        px = max(1, min(24, round(3 * scale * self.devicePixelRatioF())))
        if px != self._sprite_px:                # спрайты перестраиваются под текущий масштаб / DPI
            self._sprite_px = px
            self._sprites = self._build_sprites(px)
        p.translate((self.width() - eng.W * scale) / 2, (self.height() - eng.H * scale) / 2)
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
        frame = int(eng.anim / 12) % 2
        for a in eng.aliens:
            if a["alive"]:
                x, y = eng.alien_pos(a)
                pm = self._sprites["alien"][a["r"]][frame]
                p.drawPixmap(QPointF(x + (eng.ALIEN_W - pm.deviceIndependentSize().width()) / 2, y), pm)
        cell = eng.SHIELD_CELL
        for sh in eng.shields:
            for cx, cy in sh["cells"]:
                p.fillRect(QRectF(sh["x"] + cx * cell, sh["y"] + cy * cell, cell, cell), self.COL_PLAYER)
        if eng.ufo:
            p.drawPixmap(QPointF(eng.ufo["x"], 52), self._sprites["ufo"])
        blink_off = eng.invuln > 0 and int(self._t * 12) % 2 == 0
        if eng.lives > 0 and not blink_off:
            p.drawPixmap(QPointF(eng.player_x - eng.PLAYER_W / 2, eng.PLAYER_Y), self._sprites["player"])
        for b in eng.bullets:
            p.fillRect(QRectF(b["x"] - 1.5, b["y"], 3, 12), QColor("#ffffff"))
        for b in eng.ebullets:
            p.fillRect(QRectF(b["x"] - 1.5, b["y"], 3, 12), QColor("#ff9a3c"))
        for b in eng.blasts:                     # короткие вспышки взрывов
            k = b["t"] / 0.4
            col = {"p": QColor("#4cff6a"), "u": QColor("#ff4a4a")}.get(b["c"], QColor("#ffffff"))
            col.setAlpha(int(255 * (1 - k)))
            p.setPen(QPen(col, 2))
            r = 6 + 16 * k
            for ang in range(0, 360, 45):
                dx, dy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
                p.drawLine(QPointF(b["x"] + dx * r * 0.5, b["y"] + dy * r * 0.5),
                           QPointF(b["x"] + dx * r, b["y"] + dy * r))

    def _font(self, size):
        f = QFont("Consolas")
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPixelSize(size)
        f.setBold(True)
        return f

    def _draw_hud(self, p):
        eng = self.engine
        p.setFont(self._font(16))
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(12, 6, 200, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"Счет: {eng.score}")
        p.setPen(QColor("#ffd84a"))
        p.drawText(QRectF(eng.W - 212, 6, 200, 22), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"Рекорд: {eng.high}")
        p.setPen(QColor("#9fb4ff"))
        p.setFont(self._font(13))
        p.drawText(QRectF(12, 26, 200, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"Уровень: {eng.level}")
        for i in range(max(0, eng.lives)):       # жизни — маленькие кораблики
            p.drawPixmap(QRectF(eng.W - 28 - i * 30, 28, 24, 14), self._sprites["player"],
                         QRectF(self._sprites["player"].rect()))
        p.setPen(QPen(QColor("#3a4a8a"), 1))
        p.drawLine(0, eng.TOP - 2, eng.W, eng.TOP - 2)

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
                text(250, f"Уровень {eng.level}", 26, "#ffd84a", 40)
            return
        p.fillRect(QRectF(0, 0, eng.W, eng.H), QColor(0, 0, 0, 165))
        if eng.state == "ready":
            text(150, "КОСМИЧЕСКИЕ", 34, "#4cff6a", 44)
            text(192, "ЗАХВАТЧИКИ", 34, "#4cff6a", 44)
            text(270, "← →  —  движение", 16, "#ffffff")
            text(296, "↑ / Пробел  —  огонь", 16, "#ffffff")
            text(322, "P  —  пауза     Esc  —  пауза / выход в меню", 16, "#ffffff")
            if blink:
                text(400, "Нажмите Пробел или ↑, чтобы начать", 17, "#ffd84a")
        elif eng.state == "paused":
            text(210, "ПАУЗА", 38, "#ffd84a", 50)
            text(280, "P или Пробел  —  продолжить", 16, "#ffffff")
            text(306, "Esc  —  к выбору игры", 16, "#ffffff")
        else:
            text(180, "ИГРА ОКОНЧЕНА", 32, "#ff4a4a", 44)
            text(240, f"Счет: {eng.score}", 22, "#ffffff", 32)
            text(274, f"Рекорд: {eng.high}", 18, "#ffd84a")
            if eng.record_beaten:
                text(304, "Новый рекорд!", 18, "#4cff6a")
            if blink:
                text(370, "Пробел или ↑  —  играть снова", 16, "#ffffff")
            text(398, "Esc  —  назад к выбору игры", 16, "#9fb4ff")
