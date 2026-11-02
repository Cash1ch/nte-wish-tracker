"""Синтез и загрузка звуков Колеса Фортуны."""

import array
import math
import random
import sys
import tempfile
import time
import wave
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, QUrl

from ..compat import QSoundEffect
from ..paths import app_dir, search_roots


# ---------- свои звуки ----------
# Положите WAV-файлы в папку  assets/audio/fortune/  рядом с main.py (или рядом с базой данных):
#   ambient.wav — фоновая тема (звучит по кругу, пока открыто окно колеса)
#   spin.wav    — шум вращения (по кругу; громкость следует за скоростью колеса)
#   tick.wav    — короткий щелчок штифта (проигрывается на каждом секторе)
#   win.wav     — победный звук после остановки
# Любой файл можно не класть — тогда вместо него играет встроенный синтезированный звук.
# Формат: несжатый PCM WAV (QSoundEffect не читает mp3 / ogg). Файлы подхватываются при открытии окна.
FORTUNE_SOUND_DIR = "assets/audio/fortune"



FORTUNE_SOUND_FILES = {"ambient": "ambient.wav", "whirr": "spin.wav", "tick": "tick.wav", "win": "win.wav"}



def fortune_sound_dir() -> Path:
    return app_dir() / FORTUNE_SOUND_DIR



def _fortune_custom_file(key: str, theme: str = "classic"):
    """Путь к своему звуку из assets/audio/fortune (без учёта регистра имени) или None.
    Классическая тема берёт ambient.wav / spin.wav / tick.wav / win.wav, «Стиль NTE» —
    nte_ambient.wav / nte_spin.wav / nte_tick.wav / nte_win.wav, «Сакура» —
    sakura_ambient.wav / sakura_spin.wav / sakura_tick.wav / sakura_win.wav, «Белые лапки» —
    paws_ambient.wav / paws_spin.wav / paws_tick.wav / paws_win.wav."""
    wanted = {"nte": "nte_", "sakura": "sakura_", "paws": "paws_"}.get(theme, "") + FORTUNE_SOUND_FILES[key]
    roots = search_roots()
    for root in roots:
        folder = root / FORTUNE_SOUND_DIR
        try:
            if folder.is_dir():
                for p in folder.iterdir():
                    if p.is_file() and p.name.lower() == wanted:
                        return p
        except OSError:
            continue
    return None



# ---------- синтез звуков ----------
_FORTUNE_SOUNDS = {}                              # {тема: {имя: путь}}



_FORTUNE_DIR = []                                 # временная папка со звуками (создаётся один раз)



def _fortune_write_wav(path, samples, rate):
    """Записывает список чисел -1..1 в 16-битный моно WAV."""
    data = array.array("h", [max(-32767, min(32767, int(v * 32767))) for v in samples])
    if sys.byteorder == "big":
        data.byteswap()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())



def _fortune_normalize(samples, peak):
    top = max((abs(v) for v in samples), default=1.0) or 1.0
    return [v * peak / top for v in samples]



def _synth_classic(folder: Path) -> dict:
    """Классический набор: механические щелчки, мягкий «лаунж»-пэд с колокольчиками, шум вращения
    и победный перезвон."""
    rnd = random.Random(42)
    # «тики»: три высоты — чем быстрее колесо, тем выше и суше щелчок
    rate = 22050
    for name, freq in (("tick_low", 900.0), ("tick_mid", 1400.0), ("tick_high", 2100.0)):
        n = int(rate * 0.05)
        s = [(math.sin(math.tau * freq * i / rate) * math.exp(-i / rate * 120)
              + (rnd.random() - 0.5) * 0.5 * math.exp(-i / rate * 400)) for i in range(n)]
        _fortune_write_wav(folder / f"{name}.wav", _fortune_normalize(s, 0.7), rate)
    # шум вращения: сглаженный шум, склеенный по кругу (плавный переход конца в начало)
    n = int(rate * 1.2)
    lp, noise = 0.0, []
    for _ in range(n):
        lp += 0.12 * ((rnd.random() - 0.5) - lp)
        noise.append(lp)
    fade = int(rate * 0.08)
    for i in range(fade):
        k = i / fade
        noise[i] = noise[i] * k + noise[n - fade + i] * (1 - k)
    noise = noise[:n - fade]
    _fortune_write_wav(folder / "whirr.wav", _fortune_normalize(noise, 0.6), rate)
    # фоновая тема: тихий «пэд» + редкие колокольчики; все частоты кратны 1/8 Гц, поэтому
    # петля длиной 8 секунд замыкается без щелчка
    rate_a, length = 11025, 8.0
    total = int(rate_a * length)
    snap = lambda f: round(f * 8) / 8.0
    pad = [(snap(220.0), 0.30), (snap(329.63), 0.22), (snap(440.0), 0.18), (snap(523.25), 0.12),
           (snap(220.0) + 0.25, 0.18), (snap(329.63) - 0.25, 0.12)]
    bells = [(0.0, 880.0), (1.0, 659.25), (2.0, 784.0), (3.0, 659.25), (4.0, 1046.5), (5.0, 880.0),
             (6.0, 784.0), (7.0, 659.25)]
    amb = []
    for i in range(total):
        t = i / rate_a
        v = 0.0
        for f, a in pad:
            v += a * math.sin(math.tau * f * t)
        v *= 0.55 + 0.45 * math.sin(math.tau * t / 8.0) ** 2
        amb.append(v)
    for start, f in bells:                            # колокольчики с хвостом, переходящим через границу петли
        f = snap(f)
        for i in range(int(rate_a * 2.4)):
            idx = (int(start * rate_a) + i) % total
            t = i / rate_a
            amb[idx] += 0.16 * math.sin(math.tau * f * t) * math.exp(-t * 2.2)
    _fortune_write_wav(folder / "ambient.wav", _fortune_normalize(amb, 0.55), rate_a)
    # победный перезвон: арпеджио до-мажора + мерцающий аккорд и лёгкое эхо
    rate = 22050
    n = int(rate * 2.6)
    win = [0.0] * n
    for k, f in enumerate((523.25, 659.25, 783.99, 1046.5)):
        t0 = int(rate * 0.11 * k)
        for i in range(n - t0):
            t = i / rate
            e = math.exp(-t * 2.4)
            win[t0 + i] += e * (math.sin(math.tau * f * t) + 0.3 * math.sin(math.tau * 2 * f * t)
                                + 0.12 * math.sin(math.tau * 3 * f * t))
    t0 = int(rate * 0.5)
    for f in (783.99, 1046.5, 1318.5):
        for i in range(n - t0):
            t = i / rate
            win[t0 + i] += 0.5 * math.exp(-t * 1.5) * math.sin(math.tau * f * t) * (0.8 + 0.2 * math.sin(math.tau * 6 * t))
    delay = int(rate * 0.18)
    for i in range(n - 1, delay - 1, -1):
        win[i] += 0.32 * win[i - delay]
    _fortune_write_wav(folder / "win.wav", _fortune_normalize(win, 0.85), rate)
    return {name: folder / f"{name}.wav" for name in ("tick_low", "tick_mid", "tick_high", "whirr", "ambient", "win")}



def _synth_nte(folder: Path) -> dict:
    """Набор «Стиль NTE»: синтвейв-фон (бас, пэд, арпеджио, бочка, хэт), электронные блипы вместо
    щелчков, киберпанковый гул вращения и энергичный победный «стаб». Все петли замыкаются бесшовно."""
    rnd = random.Random(7)
    saw = lambda f, t: 2.0 * ((f * t) % 1.0) - 1.0
    # электронные тики: прямоугольная волна с быстрым падением высоты
    rate = 22050
    for name, freq in (("tick_low", 1100.0), ("tick_mid", 1700.0), ("tick_high", 2600.0)):
        n, ph, s = int(rate * 0.045), 0.0, []
        for i in range(n):
            t = i / rate
            ph += freq * (1 + 0.6 * math.exp(-t * 70)) / rate
            s.append((1.0 if ph % 1.0 < 0.5 else -1.0) * math.exp(-t * 85) * 0.8
                     + (rnd.random() - 0.5) * 0.25 * math.exp(-t * 300))
        _fortune_write_wav(folder / f"{name}.wav", _fortune_normalize(s, 0.7), rate)
    # гул вращения: пила + шумоподобная сумма синусоид; все частоты кратны 1/1.2 Гц — петля без щелчка
    n = int(rate * 1.2)
    f0 = 100 / 1.2
    comps = [(rnd.randint(120, 3000) / 1.2, rnd.uniform(0, math.tau)) for _ in range(24)]
    whirr = []
    for i in range(n):
        t = i / rate
        tonal = 0.55 * saw(f0, t) + 0.25 * saw(2 * f0, t)
        grit = sum(math.sin(math.tau * f * t + ph) for f, ph in comps) / 8.0
        whirr.append((tonal + 0.35 * grit) * (0.75 + 0.25 * math.sin(math.tau * 10 * t / 1.2)))
    _fortune_write_wav(folder / "whirr.wav", _fortune_normalize(whirr, 0.55), rate)
    # фон: синтвейв 120 BPM, 4 такта (Am – F – C – G) = 8 секунд; ноты начинаются и заканчиваются в тишине
    rate_a = 11025
    total = int(rate_a * 8.0)
    amb = [0.0] * total
    chords = ((55.0, (220.0, 261.63, 329.63)), (43.65, (174.61, 220.0, 261.63)),
              (65.41, (261.63, 329.63, 392.0)), (49.0, (196.0, 246.94, 293.66)))
    for bar, (root, chord) in enumerate(chords):
        base = int(bar * 2.0 * rate_a)
        for i in range(int(2.0 * rate_a)):               # пэд: две расстроенные пилы на ноту
            t = i / rate_a
            env = math.sin(math.pi * t / 2.0) ** 0.6
            amb[base + i] += env * sum(0.06 * (saw(f * 1.004, t) + saw(f * 0.996, t)) for f in chord)
        for step in range(8):                             # бас восьмыми
            for i in range(int(0.25 * rate_a)):
                t = i / rate_a
                env = math.exp(-t * 6) * min(1.0, (0.25 - t) / 0.01)
                amb[base + int(step * 0.25 * rate_a) + i] += 0.30 * env * (0.5 * saw(root, t) + 0.5 * math.sin(math.tau * root * t))
        for step in range(16):                            # арпеджио шестнадцатыми
            f = chord[(0, 1, 2, 1)[step % 4]] * 2
            for i in range(int(0.125 * rate_a)):
                t = i / rate_a
                env = math.exp(-t * 14) * min(1.0, (0.125 - t) / 0.008)
                amb[base + int(step * 0.125 * rate_a) + i] += 0.15 * env * (saw(f, t) + (1.0 if (f * t) % 1.0 < 0.5 else -1.0))
    for beat in range(16):                                # бочка на каждую долю и «хэт» между ними
        base = int(beat * 0.5 * rate_a)
        ph = 0.0
        for i in range(int(0.22 * rate_a)):
            t = i / rate_a
            ph += (45 + 90 * math.exp(-t * 18)) / rate_a
            amb[base + i] += 0.85 * math.sin(math.tau * ph) * math.exp(-t * 14) * min(1.0, (0.22 - t) / 0.01)
        hat = base + int(0.25 * rate_a)
        for i in range(int(0.04 * rate_a)):
            amb[hat + i] += 0.16 * (rnd.random() - 0.5) * math.exp(-i / rate_a * 90)
    _fortune_write_wav(folder / "ambient.wav", _fortune_normalize(amb, 0.55), rate_a)
    # победа: «райзер» + быстрое арпеджио + аккорд-стаб с басом и эхо
    n = int(rate * 2.6)
    win = [0.0] * n
    ph = 0.0
    for i in range(int(rate * 0.5)):                      # нарастающий свист
        t = i / rate
        ph += (300 + 3000 * t) / rate
        win[i] += 0.28 * math.sin(math.tau * ph) * (t / 0.5)
    for k, f in enumerate((440.0, 523.25, 659.25, 880.0, 1046.5, 1318.5)):
        t0 = int(rate * 0.07 * k)
        for i in range(min(n - t0, int(rate * 0.55))):
            t = i / rate
            win[t0 + i] += 0.30 * math.exp(-t * 5) * (0.6 * saw(f, t) + 0.4 * (1.0 if (f * t) % 1.0 < 0.5 else -1.0))
    t0 = int(rate * 0.5)
    ph = 0.0
    for i in range(n - t0):
        t = i / rate
        e = math.exp(-t * 2.2)
        stab = sum(saw(f * d, t) for f in (440.0, 523.25, 659.25, 987.77) for d in (0.997, 1.003))
        ph += (50 + 110 * math.exp(-t * 18)) / rate
        win[t0 + i] += 0.07 * e * stab + 0.55 * math.sin(math.tau * 110 * t) * e + 0.8 * math.sin(math.tau * ph) * math.exp(-t * 12)
    delay = int(rate * 0.15)
    for i in range(n - 1, delay - 1, -1):
        win[i] += 0.3 * win[i - delay]
    _fortune_write_wav(folder / "win.wav", _fortune_normalize(win, 0.9), rate)
    return {name: folder / f"{name}.wav" for name in ("tick_low", "tick_mid", "tick_high", "whirr", "ambient", "win")}



def _fortune_ks_pluck(freq: float, rate: int, seconds: float, rnd, decay: float = 0.996) -> list:
    """Щипок струны (алгоритм Карплюса — Стронга): звучит как кото / сямисэн."""
    size = max(2, int(rate / freq))
    buf = [rnd.uniform(-1.0, 1.0) for _ in range(size)]
    for _ in range(2):                                    # сглаживание начального «шума» — звук мягче, как у кото
        buf = [(buf[i] + buf[(i + 1) % size]) * 0.5 * 1.4 for i in range(size)]
    out, idx = [], 0
    for _ in range(int(rate * seconds)):
        out.append(buf[idx])
        nxt = buf[(idx + 1) % size]
        buf[idx] = decay * 0.5 * (buf[idx] + nxt)
        idx = (idx + 1) % size
    return out



def _synth_sakura(folder: Path) -> dict:
    """Набор «Сакура»: фон из кото и сякухати на ладу «ин» (A B♭ D E F), деревянные / бамбуковые щелчки,
    шелест бамбука при вращении и победный храмовый колокол с дзен-чашей. Петля фона замыкается бесшовно."""
    rnd = random.Random(21)
    # деревянные «тики»: короткий резонанс колодки + щелчок
    rate = 22050
    for name, freq in (("tick_low", 620.0), ("tick_mid", 880.0), ("tick_high", 1250.0)):
        n = int(rate * 0.07)
        s = []
        for i in range(n):
            t = i / rate
            s.append(math.sin(math.tau * freq * t) * math.exp(-t * 55)
                     + 0.45 * math.sin(math.tau * freq * 2.4 * t) * math.exp(-t * 90)
                     + (rnd.random() - 0.5) * 0.7 * math.exp(-t * 400))
        _fortune_write_wav(folder / f"{name}.wav", _fortune_normalize(s, 0.7), rate)
    # шелест бамбука: «шумоподобная» сумма синусоид (кратны 1/1.2 Гц — петля без щелчка) + тихий колокольчик
    n = int(rate * 1.2)
    comps = [(rnd.randint(350, 2400) / 1.2, rnd.uniform(0, math.tau)) for _ in range(20)]
    whirr = []
    for i in range(n):
        t = i / rate
        grit = sum(math.sin(math.tau * f * t + ph) for f, ph in comps) / 10.0
        whirr.append(grit * (0.65 + 0.35 * math.sin(math.tau * 5 * t / 1.2))
                     + 0.25 * math.sin(math.tau * (1800 / 1.2) * t) * (0.5 + 0.5 * math.sin(math.tau * 2 * t / 1.2)))
    _fortune_write_wav(folder / "whirr.wav", _fortune_normalize(whirr, 0.5), rate)
    # фон: 8 секунд, лад «ин» на ля; кото (щипки), басовый бурдон, две фразы сякухати и далёкий фурин
    rate_a = 11025
    total = int(rate_a * 8.0)
    amb = [0.0] * total
    A3, BB3, D4, E4, F4, A4, BB4, D5 = 220.0, 233.08, 293.66, 329.63, 349.23, 440.0, 466.16, 587.33
    melody = (A4, E4, F4, E4, D4, E4, A3, D4, E4, F4, A4, F4, E4, D4, BB3, A3)       # 16 нот по 0.5 с
    for k, f in enumerate(melody):
        pluck = _fortune_ks_pluck(f, rate_a, 1.6, rnd, 0.9965)
        start = int(k * 0.5 * rate_a)
        for i, v in enumerate(pluck):
            amb[(start + i) % total] += 0.35 * v * (1.0 - i / len(pluck)) ** 0.5
    for i in range(total):                                # бурдон на ля: плавное «дыхание»
        t = i / rate_a
        amb[i] += 0.10 * math.sin(math.tau * 110.0 * t) * (0.6 + 0.4 * math.sin(math.tau * t / 8.0 + 1.0) ** 2)
    for start_s, length_s, f in ((0.5, 3.0, A4), (4.5, 3.0, D5)):      # сякухати: тон, дыхание, вибрато
        start = int(start_s * rate_a)
        for i in range(int(length_s * rate_a)):
            t = i / rate_a
            env = math.sin(math.pi * t / length_s) ** 1.5
            vib = 1.0 + 0.006 * math.sin(math.tau * 5.0 * t)
            tone = math.sin(math.tau * f * vib * t) + 0.25 * math.sin(math.tau * 2 * f * t)
            breath = (rnd.random() - 0.5) * 0.35
            amb[(start + i) % total] += 0.16 * env * (tone + breath)
    for start_s in (1.75, 5.75):                          # ветряной колокольчик
        start = int(start_s * rate_a)
        for i in range(int(1.4 * rate_a)):
            t = i / rate_a
            amb[(start + i) % total] += 0.06 * math.sin(math.tau * 2093.0 * t) * math.exp(-t * 4)
    _fortune_write_wav(folder / "ambient.wav", _fortune_normalize(amb, 0.55), rate_a)
    # победа: быстрое глиссандо кото вверх по ладу, храмовый колокол и дзен-чаша
    n = int(rate * 3.4)
    win = [0.0] * n
    for k, f in enumerate((A3, D4, E4, F4, A4, BB4, D5)):
        pluck = _fortune_ks_pluck(f, rate, 1.2, rnd, 0.9965)
        start = int(rate * 0.06 * k)
        for i, v in enumerate(pluck):
            if start + i < n:
                win[start + i] += 0.30 * v * (1.0 - i / len(pluck)) ** 0.5
    t0 = int(rate * 0.45)
    for ratio, amp, dec in ((1.0, 1.0, 1.1), (2.0, 0.6, 1.5), (2.76, 0.5, 1.8), (5.4, 0.3, 2.6), (8.93, 0.15, 3.5)):
        f = 196.0 * ratio                                 # колокол: негармонические обертоны
        for i in range(n - t0):
            t = i / rate
            win[t0 + i] += 0.40 * amp * math.sin(math.tau * f * t) * math.exp(-t * dec)
    t1 = int(rate * 0.9)
    for f, amp in ((880.0, 0.5), (883.0, 0.5)):           # дзен-чаша: два близких тона дают плавные биения
        for i in range(n - t1):
            t = i / rate
            win[t1 + i] += 0.25 * amp * math.sin(math.tau * f * t) * math.exp(-t * 1.0) * min(1.0, t * 20)
    _fortune_write_wav(folder / "win.wav", _fortune_normalize(win, 0.9), rate)
    return {name: folder / f"{name}.wav" for name in ("tick_low", "tick_mid", "tick_high", "whirr", "ambient", "win")}



def _synth_paws(folder: Path) -> dict:
    """Набор «Белые лапки»: уютный lofi-фон на музыкальной шкатулке с тёплым пэдом, мягкие глухие «шлепки
    лапки» вместо щелчков, тихое мурлыканье при вращении и тёплый победный перезвон с лёгким «мяу».
    Петля фона замыкается бесшовно (каждый такт начинается и заканчивается в тишине)."""
    rnd = random.Random(33)
    rate = 22050
    # мягкие «шлепки лапки»: низкий круглый тон + приглушённый шум, плавная атака (без резкого клика)
    for name, freq in (("tick_low", 190.0), ("tick_mid", 260.0), ("tick_high", 360.0)):
        n = int(rate * 0.07)
        lp, s_ = 0.0, []
        for i in range(n):
            t = i / rate
            lp += 0.18 * ((rnd.random() - 0.5) - lp)
            att = min(1.0, t / 0.004)
            s_.append(att * (math.sin(math.tau * freq * t) * math.exp(-t * 62)
                             + 0.35 * math.sin(math.tau * freq * 2.0 * t) * math.exp(-t * 110)
                             + 1.6 * lp * math.exp(-t * 90)))
        _fortune_write_wav(folder / f"{name}.wav", _fortune_normalize(s_, 0.55), rate)
    # вращение: тихое мурлыканье — сглаженный шум с амплитудной модуляцией 25 Гц (петля с плавным стыком)
    n = int(rate * 1.2)
    lp, purr = 0.0, []
    for i in range(n):
        t = i / rate
        lp += 0.05 * ((rnd.random() - 0.5) - lp)
        purr.append(lp * (0.55 + 0.45 * math.sin(math.tau * 25.0 * t)))
    fade = int(rate * 0.08)
    for i in range(fade):
        k = i / fade
        purr[i] = purr[i] * k + purr[n - fade + i] * (1 - k)
    purr = purr[:n - fade]
    _fortune_write_wav(folder / "whirr.wav", _fortune_normalize(purr, 0.45), rate)
    # фон: 8 секунд, До – ля минор – Фа – Соль; музыкальная шкатулка, тёплый пэд, мягкий бас, тихий «винил»
    rate_a = 11025
    total = int(rate_a * 8.0)
    amb = [0.0] * total
    chords = ((130.81, (261.63, 329.63, 392.0)), (110.0, (220.0, 261.63, 329.63)),
              (87.31, (174.61, 220.0, 261.63)), (98.0, (196.0, 246.94, 293.66)))
    for bar, (root, chord) in enumerate(chords):
        base = int(bar * 2.0 * rate_a)
        for i in range(int(2.0 * rate_a)):
            t = i / rate_a
            env = math.sin(math.pi * t / 2.0) ** 2         # в начале и в конце такта — тишина: стык без щелчка
            v = 0.10 * math.sin(math.tau * root * t)
            for f in chord:
                v += 0.07 * (math.sin(math.tau * f * t) + 0.3 * math.sin(math.tau * 2 * f * t))
            amb[base + i] += env * v
    melody = (659.25, 783.99, 1046.5, 880.0, 783.99, 659.25, 587.33, 659.25,
              783.99, 880.0, 1046.5, 880.0, 783.99, 659.25, 587.33, 523.25)      # 16 нот по 0.5 с
    for k, f in enumerate(melody):
        start = int(k * 0.5 * rate_a)
        for i in range(int(rate_a * 1.5)):
            t = i / rate_a
            v = (math.sin(math.tau * f * t) * math.exp(-t * 3.2)
                 + 0.35 * math.sin(math.tau * 2 * f * t) * math.exp(-t * 6.0)
                 + 0.12 * math.sin(math.tau * 3 * f * t) * math.exp(-t * 9.0))
            amb[(start + i) % total] += 0.17 * min(1.0, t / 0.003) * v
    for _ in range(36):                                    # тихое потрескивание пластинки
        pos = rnd.randrange(total - 40)
        amp = rnd.uniform(0.01, 0.035)
        for j in range(30):
            amb[pos + j] += amp * (rnd.random() - 0.5) * math.exp(-j / 6.0)
    _fortune_write_wav(folder / "ambient.wav", _fortune_normalize(amb, 0.5), rate_a)
    # победа: тёплое арпеджио шкатулки, мягкий аккорд, мурлыканье и короткое «мяу»
    n = int(rate * 3.2)
    win = [0.0] * n
    for k, f in enumerate((523.25, 659.25, 783.99, 1046.5)):
        t0 = int(rate * 0.13 * k)
        for i in range(min(n - t0, int(rate * 2.2))):
            t = i / rate
            e = math.exp(-t * 2.6) * min(1.0, t / 0.004)
            win[t0 + i] += 0.5 * e * (math.sin(math.tau * f * t) + 0.3 * math.sin(math.tau * 2 * f * t)
                                      + 0.1 * math.sin(math.tau * 3 * f * t))
    t0 = int(rate * 0.5)
    for f in (261.63, 329.63, 392.0):
        for i in range(n - t0):
            t = i / rate
            win[t0 + i] += 0.12 * math.sin(math.tau * f * t) * math.exp(-t * 1.2) * min(1.0, t * 8)
    p0 = int(rate * 0.7)
    lp = 0.0
    for i in range(p0, n):                                 # мурлыканье
        t = (i - p0) / rate
        lp += 0.04 * ((rnd.random() - 0.5) - lp)
        win[i] += 2.2 * lp * min(1.0, t / 0.3) * math.exp(-t * 1.1) * (0.5 + 0.5 * math.sin(math.tau * 24.0 * t))
    m0, dur, ph = int(rate * 0.75), 0.45, 0.0
    for i in range(int(rate * dur)):                       # «мяу»: тон поднимается и опускается
        t = i / rate
        x = t / dur
        f = 480.0 + 320.0 * math.sin(math.pi * x) - 60.0 * x
        ph += f * (1.0 + 0.012 * math.sin(math.tau * 6.0 * t)) / rate
        tone = math.sin(math.tau * ph) + 0.5 * math.sin(math.tau * 2 * ph) + 0.3 * math.sin(math.tau * 3 * ph)
        win[m0 + i] += 0.16 * (math.sin(math.pi * x) ** 0.7) * tone
    delay = int(rate * 0.2)
    for i in range(n - 1, delay - 1, -1):
        win[i] += 0.25 * win[i - delay]
    _fortune_write_wav(folder / "win.wav", _fortune_normalize(win, 0.8), rate)
    return {name: folder / f"{name}.wav" for name in ("tick_low", "tick_mid", "tick_high", "whirr", "ambient", "win")}



def _fortune_sound_files(theme: str = "classic") -> dict:
    """Создаёт (один раз для каждой темы) звуки колеса и возвращает {имя: путь}.
    Бросает исключение при сбое записи."""
    theme = theme if theme in ("nte", "sakura", "paws") else "classic"
    if theme in _FORTUNE_SOUNDS:
        return _FORTUNE_SOUNDS[theme]
    if not _FORTUNE_DIR:
        _FORTUNE_DIR.append(Path(tempfile.mkdtemp(prefix="nte_fortune_")))
    folder = _FORTUNE_DIR[0] / theme
    folder.mkdir(parents=True, exist_ok=True)
    synth = {"nte": _synth_nte, "sakura": _synth_sakura, "paws": _synth_paws}.get(theme, _synth_classic)
    _FORTUNE_SOUNDS[theme] = synth(folder)
    return _FORTUNE_SOUNDS[theme]



class FortuneSounds(QObject):
    """Звуки колеса. Громкость берётся у фоновой музыки приложения (ползунок и «звук выкл»
    действуют и здесь). Любая ошибка мультимедиа отключает звуки — колесо работает без них."""

    def __init__(self, get_master, parent=None, theme: str = "classic"):
        super().__init__(parent)
        self.get_master = get_master             # () -> (громкость 0..1, выключено?)
        self.theme = theme                       # набор звуков: "classic" / "nte" / "sakura" / "paws"
        self.started = False                     # фон уже запускался (окно открыто)
        self.enabled = True                      # галочка «Звук» в окне колеса
        self.ready = False
        self._fx = {}
        self._tick_pool = {}
        self._tick_i = 0
        self._last_tick = 0.0
        self._whirr_on = False

    def prepare(self):
        """Создаёт звуки и QSoundEffect (вызывается после показа окна, чтобы оно открылось мгновенно)."""
        if QSoundEffect is None or self.ready:
            return
        try:
            self._generated = _fortune_sound_files(self.theme)  # встроенные звуки — запасной вариант
            self._custom = {k: _fortune_custom_file(k, self.theme) for k in FORTUNE_SOUND_FILES}
            for name in self._generated:
                self._fx[name] = self._make_effect(name)
            for name in ("ambient", "whirr"):
                self._set_loops(self._fx[name], True)
            for name in ("tick_low", "tick_mid", "tick_high"):
                self._tick_pool[name] = [self._fx[name], self._make_effect(name)]   # второй экземпляр — чтобы быстрые тики не обрывали друг друга
            self.ready = True
        except Exception:  # noqa: BLE001 — сбой мультимедиа не должен ломать колесо
            self.ready = False

    def _make_effect(self, name):
        """QSoundEffect для звука name: свой файл из assets/audio/fortune, иначе встроенный.
        Если свой файл не открылся (не WAV / повреждён), автоматически берётся встроенный."""
        key = "tick" if name.startswith("tick_") else name
        custom = self._custom.get(key)
        fx = QSoundEffect(self)
        fx.statusChanged.connect(lambda fx=fx, name=name, custom=custom: self._on_effect_status(fx, name, custom))
        fx.setSource(QUrl.fromLocalFile(str(custom or self._generated[name])))
        return fx

    def _on_effect_status(self, fx, name, custom):
        try:
            if custom is not None and fx.status() == QSoundEffect.Status.Error:
                fx.setSource(QUrl.fromLocalFile(str(self._generated[name])))
                if name in ("ambient", "whirr"):
                    self._set_loops(fx, True)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _set_loops(fx, loop: bool):
        try:
            fx.setLoopCount(-2 if loop else 1)                 # -2 = QSoundEffect.Infinite
        except Exception:  # noqa: BLE001
            pass

    def _master(self) -> float:
        if not self.enabled:
            return 0.0
        try:
            vol, muted = self.get_master()
        except Exception:  # noqa: BLE001
            return 0.0
        return 0.0 if muted else max(0.0, min(1.0, vol))

    def _play(self, name, vol):
        fx = self._fx.get(name)
        if fx is None or not self.ready:
            return
        try:
            fx.setVolume(max(0.0, min(1.0, vol)))
            if not fx.isPlaying():
                fx.play()
        except Exception:  # noqa: BLE001
            pass

    def refresh(self):
        """Применяет изменения громкости / галочки «Звук» к фоновой теме."""
        if not self.ready:
            return
        m = self._master()
        try:
            if m <= 0:
                self._fx["ambient"].stop()
            else:
                self._play("ambient", 0.30 * m)
        except Exception:  # noqa: BLE001
            pass

    def start_ambient(self):
        self.started = True
        self.refresh()

    def set_theme(self, theme: str):
        """Переключает набор звуков (классический / «Стиль NTE» / «Сакура» / «Белые лапки»): старые эффекты останавливаются и
        выгружаются, новые создаются сразу после смены оформления, фон запускается заново."""
        if theme == self.theme:
            return
        self.stop_all()
        for fx in list(self._fx.values()):
            try:
                fx.setSource(QUrl())
            except Exception:  # noqa: BLE001
                pass
        self._fx.clear()
        self._tick_pool.clear()
        self.ready = False
        self.theme = theme
        if self.started:
            QTimer.singleShot(0, self._reload)

    def _reload(self):
        self.prepare()
        self.refresh()

    def tick(self, speed: float):
        """Щелчок штифта: высота и громкость зависят от скорости, частые щелчки прореживаются."""
        m = self._master()
        now = time.monotonic()
        if not self.ready or m <= 0 or now - self._last_tick < 0.03:
            return
        self._last_tick = now
        name = "tick_high" if speed > 520 else "tick_mid" if speed > 200 else "tick_low"
        pool = self._tick_pool.get(name)
        if not pool:
            return
        self._tick_i += 1
        fx = pool[self._tick_i % len(pool)]
        try:
            fx.setVolume(min(1.0, (0.35 + 0.25 * min(1.0, speed / 600.0)) * m * 1.4))
            fx.play()
        except Exception:  # noqa: BLE001
            pass

    def set_spin(self, speed: float, spinning: bool):
        """Шум вращения: включён, пока колесо крутится; громкость следует за скоростью."""
        m = self._master()
        fx = self._fx.get("whirr")
        if fx is None or not self.ready:
            return
        try:
            if spinning and m > 0 and speed > 25:
                fx.setVolume(min(1.0, 0.5 * (min(1.0, speed / 900.0) ** 0.7) * m))
                if not self._whirr_on:
                    fx.play()
                    self._whirr_on = True
            elif self._whirr_on:
                fx.stop()
                self._whirr_on = False
        except Exception:  # noqa: BLE001
            pass

    def win(self):
        m = self._master()
        if m > 0:
            self._play("win", 0.9 * m)

    def stop_all(self):
        for fx in self._fx.values():
            try:
                fx.stop()
            except Exception:  # noqa: BLE001
                pass
        self._whirr_on = False

    def shutdown(self):
        self.stop_all()
        self.ready = False
        for fx in self._fx.values():
            try:
                fx.setSource(QUrl())
            except Exception:  # noqa: BLE001
                pass
