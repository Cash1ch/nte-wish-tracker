"""Звуки мини-игр."""

import math
import random
import tempfile
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, QUrl

from ..compat import QSoundEffect
from ..fortune.sounds import _fortune_write_wav


# =====================================================================================
# НОВОЕ: встроенная мини-игра «Космические захватчики» (кнопка «Поиграй 🎮» на вкладке
# «Скриншоты разом»). Логика игры (InvadersEngine) не зависит от Qt и работает по
# времени кадра (dt), поэтому скорость не зависит от частоты таймера. Виджет рисует кадр
# в paintEvent и обновляется таймером ~60 кадров/с в основном потоке: игра очень лёгкая
# и не мешает фоновым потокам OCR.
# =====================================================================================
MINIGAME_INVADERS_KEY = "minigame_invaders_highscore"



# =====================================================================================
# НОВОЕ: звуковые эффекты мини-игр. Все звуки синтезируются при первом запуске (WAV во
# временной папке) — внешние файлы не нужны. Воспроизведение — QSoundEffect; при любом
# сбое мультимедиа игры работают в тишине. Движки игр вызывают self._snd("имя") — это
# обычный колбэк (engine.sfx), поэтому логика остаётся независимой от Qt.
# =====================================================================================
MINIGAME_SOUND_OFF_KEY = "minigame_sound_muted"        # 0 / отсутствует — звук включён, 1 — выключен



GAME_SFX_RATE = 22050



GAME_SFX_LOOPS = frozenset({"thrust"})                 # зацикленные звуки (гул двигателя)



def _sfx_sweep(f0, f1, dur, shape="square", vol=0.6, decay=1.5, duty=0.5):
    """Тон с плавным изменением частоты f0 -> f1 и затуханием."""
    n = max(1, int(GAME_SFX_RATE * dur))
    out, phase = [], 0.0
    att = GAME_SFX_RATE * 0.003
    rel = GAME_SFX_RATE * 0.006
    for i in range(n):
        k = i / max(1, n - 1)
        phase += (f0 + (f1 - f0) * k) / GAME_SFX_RATE
        ph = phase % 1.0
        if shape == "square":
            v = 1.0 if ph < duty else -1.0
        elif shape == "tri":
            v = 4.0 * abs(ph - 0.5) - 1.0
        elif shape == "saw":
            v = 2.0 * ph - 1.0
        else:
            v = math.sin(math.tau * ph)
        env = (1.0 - k) ** decay if decay else 1.0
        out.append(v * vol * env * min(1.0, i / att) * min(1.0, (n - i) / rel))
    return out



def _sfx_noise(dur, vol=0.6, decay=2.0, smooth0=0.0, smooth1=None, seed=1):
    """Шум (взрывы, удары); smooth — «глухость» (0 — резкий, ближе к 1 — низкий гул)."""
    rnd = random.Random(seed)
    n = max(1, int(GAME_SFX_RATE * dur))
    smooth1 = smooth0 if smooth1 is None else smooth1
    out, last = [], 0.0
    rel = GAME_SFX_RATE * 0.006
    for i in range(n):
        k = i / max(1, n - 1)
        s = smooth0 + (smooth1 - smooth0) * k
        last = last * s + rnd.uniform(-1.0, 1.0) * (1.0 - s)
        gain = 1.0 / max(0.15, 1.0 - s) ** 0.5 if s else 1.0
        out.append(last * gain * vol * (1.0 - k) ** decay * min(1.0, (n - i) / rel))
    return out



def _sfx_seq(*parts):
    out = []
    for part in parts:
        out.extend(part)
    return out



def _sfx_mix(*parts):
    n = max(len(p) for p in parts)
    return [sum(p[i] for p in parts if i < len(p)) for i in range(n)]



def _sfx_notes(freqs, each, shape="square", vol=0.35, last=None, decay=0.8):
    parts = []
    for i, f in enumerate(freqs):
        d = last if (last and i == len(freqs) - 1) else each
        parts.append(_sfx_sweep(f, f, d, shape, vol, decay if i == len(freqs) - 1 else 0.3))
    return _sfx_seq(*parts)



def _sfx_rumble():
    """Бесшовный гул двигателя (целое число периодов -> без щелчка при зацикливании)."""
    n = int(GAME_SFX_RATE * 0.4)
    out = []
    for i in range(n):
        t = i / GAME_SFX_RATE
        saw = 2.0 * ((30.0 * t) % 1.0) - 1.0
        out.append(0.45 * math.sin(math.tau * 60 * t) + 0.3 * math.sin(math.tau * 90 * t + 1.0)
                   + 0.12 * math.sin(math.tau * 120 * t) + 0.13 * saw)
    return out



def _game_sfx_samples() -> dict:
    return {
        # Марио / общие
        "jump": _sfx_sweep(260, 760, 0.17, "square", 0.45, 1.0),
        "block": _sfx_mix(_sfx_sweep(230, 110, 0.09, "square", 0.5, 1.0), _sfx_noise(0.05, 0.25, 2.0, 0.5, seed=3)),
        "item": _sfx_notes((392, 523, 659, 784, 988), 0.045, "tri", 0.5, last=0.12),
        "coin": _sfx_seq(_sfx_sweep(988, 988, 0.06, "square", 0.32, 0.0),
                         _sfx_sweep(1319, 1319, 0.26, "square", 0.32, 2.0)),
        "powerup": _sfx_notes((262, 330, 392, 523, 659, 784, 1047, 1319), 0.05, "square", 0.32, last=0.2),
        "fireball": _sfx_mix(_sfx_sweep(950, 280, 0.15, "square", 0.38, 1.5, 0.25),
                             _sfx_noise(0.1, 0.18, 2.0, 0.2, seed=5)),
        "stomp": _sfx_seq(_sfx_sweep(420, 140, 0.09, "square", 0.5, 0.8), _sfx_sweep(180, 90, 0.07, "tri", 0.45, 1.5)),
        "death": _sfx_seq(_sfx_notes((523, 392, 330), 0.12, "tri", 0.5, last=0.14),
                          _sfx_sweep(320, 60, 0.55, "square", 0.38, 1.2)),
        "gameover": _sfx_seq(_sfx_notes((392, 370, 349, 330, 294), 0.16, "square", 0.34),
                             _sfx_sweep(262, 196, 0.6, "tri", 0.5, 1.4)),
        "win": _sfx_notes((523, 659, 784, 1047, 784, 1047), 0.09, "square", 0.34, last=0.4),
        # Астероиды / захватчики
        "shoot": _sfx_sweep(1500, 320, 0.13, "saw", 0.36, 1.4),
        "explode": _sfx_mix(_sfx_noise(0.55, 0.85, 2.2, 0.72, 0.93, seed=7),
                            _sfx_sweep(130, 40, 0.5, "square", 0.3, 1.5)),
        "explode_small": _sfx_noise(0.22, 0.65, 2.0, 0.35, 0.7, seed=9),
        "hit": _sfx_mix(_sfx_noise(0.35, 0.6, 1.8, 0.55, 0.85, seed=11), _sfx_sweep(320, 60, 0.32, "saw", 0.4, 1.2)),
        "ufo": _sfx_mix(_sfx_sweep(220, 1250, 0.32, "saw", 0.34, 0.8), _sfx_noise(0.25, 0.3, 1.5, 0.3, seed=13)),
        "thrust": _sfx_rumble(),
        # Арканоид
        "paddle": _sfx_sweep(440, 440, 0.07, "square", 0.42, 1.5),
        "wall": _sfx_sweep(220, 220, 0.045, "square", 0.32, 1.0),
        "brick": _sfx_sweep(660, 900, 0.08, "square", 0.42, 1.5),
    }



_GAME_SFX_FILES = {}



def _game_sfx_files() -> dict:
    """Пишет (один раз) WAV-файлы звуков во временную папку и возвращает {имя: путь}."""
    if _GAME_SFX_FILES:
        return _GAME_SFX_FILES
    folder = Path(tempfile.gettempdir()) / "nte_gacha_game_sfx_v1"
    folder.mkdir(parents=True, exist_ok=True)
    for name, samples in _game_sfx_samples().items():
        path = folder / f"{name}.wav"
        if not path.exists() or path.stat().st_size < 64:
            top = max((abs(v) for v in samples), default=1.0) or 1.0
            _fortune_write_wav(path, [v * min(1.0, 0.9 / top) for v in samples], GAME_SFX_RATE)
        _GAME_SFX_FILES[name] = path
    return _GAME_SFX_FILES



class GameAudio(QObject):
    """Звуки мини-игр. Все эффекты создаются один раз, воспроизводятся из небольшого пула
    QSoundEffect; при отключении звука, паузе и закрытии окна всё останавливается и освобождается."""

    POOL = 3

    def __init__(self, enabled: bool = True, parent=None):
        super().__init__(parent)
        self.enabled = bool(enabled)
        self.ready = False
        self._fx = {}
        self._pos = {}
        self._last = {}
        self._loop_watchdog = QTimer(self)               # гул гаснет сам, если тяга больше не приходит
        self._loop_watchdog.setSingleShot(True)
        self._loop_watchdog.setInterval(140)
        self._loop_watchdog.timeout.connect(self._stop_loops)

    def prepare(self):
        if self.ready or QSoundEffect is None:
            return
        try:
            for name, path in _game_sfx_files().items():
                effects = []
                for _ in range(1 if name in GAME_SFX_LOOPS else self.POOL):
                    fx = QSoundEffect(self)
                    fx.setSource(QUrl.fromLocalFile(str(path)))
                    fx.setVolume(0.45 if name in GAME_SFX_LOOPS else 0.6)
                    if name in GAME_SFX_LOOPS:
                        try:
                            fx.setLoopCount(-2)          # бесконечно
                        except Exception:  # noqa: BLE001
                            pass
                    effects.append(fx)
                self._fx[name] = effects
            self.ready = bool(self._fx)
        except Exception:  # noqa: BLE001 — сбой мультимедиа не должен ломать игры
            self.ready = False
            self._fx.clear()

    def set_enabled(self, flag: bool):
        self.enabled = bool(flag)
        if not self.enabled:
            self.stop_all()

    def play(self, name: str):
        if not self.enabled:
            return
        if not self.ready:
            self.prepare()
        effects = self._fx.get(name)
        if not effects:
            return
        try:
            if name in GAME_SFX_LOOPS:
                if not effects[0].isPlaying():
                    effects[0].play()
                self._loop_watchdog.start()
                return
            now = time.monotonic()
            if now - self._last.get(name, 0.0) < 0.03:   # не «дребезжим» одним звуком
                return
            self._last[name] = now
            i = self._pos.get(name, 0) % len(effects)
            self._pos[name] = i + 1
            effects[i].stop()
            effects[i].play()
        except Exception:  # noqa: BLE001
            pass

    def _stop_loops(self):
        for name in GAME_SFX_LOOPS:
            for fx in self._fx.get(name, ()):
                try:
                    fx.stop()
                except Exception:  # noqa: BLE001
                    pass

    def stop_all(self):
        self._loop_watchdog.stop()
        for effects in self._fx.values():
            for fx in effects:
                try:
                    fx.stop()
                except Exception:  # noqa: BLE001
                    pass

    def release(self):
        """Останавливает звуки и освобождает ресурсы (закрытие окна мини-игр)."""
        self.stop_all()
        for effects in self._fx.values():
            for fx in effects:
                try:
                    fx.setSource(QUrl())
                    fx.deleteLater()
                except Exception:  # noqa: BLE001
                    pass
        self._fx.clear()
        self.ready = False



class GameSfxMixin:
    """Подмешивается в движки игр: engine.sfx — колбэк звука (None — тишина)."""
    sfx = None

    def _snd(self, name: str):
        cb = self.sfx
        if cb is not None:
            try:
                cb(name)
            except Exception:  # noqa: BLE001
                pass
