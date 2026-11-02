"""Определение ранга S / A / B по цвету рамки или фона."""

import difflib
import re

from ..compat import Image, ImageChops, ImageOps, ImageStat
from .config import (
    _NAME_WORD_RE, GOLD_HUE, GOLD_MIN_SAT, GOLD_MIN_VAL, PURPLE_HUE, PURPLE_MIN_SAT, PURPLE_MIN_VAL,
    TEXT_COLOR_MIN_FRACTION, TEXT_FG_DIFF, TEXT_MIN_PIXELS,
)
from .layout import _right_column_index
from .names import BONUS_MARK_RE, fold_name, STRANA_SNA_RE


# ---------------------------------------------------------------------------
# Анализ цвета рамки / фона слота -> ранг S / A / B
# ---------------------------------------------------------------------------
# Для каждого цветового диапазона строится бинарная маска средствами Pillow
# (таблицы подстановки + умножение масок — всё на C), а пиксели считаются по
# гистограмме: на порядок быстрее попиксельного цикла на Python.
def _hue255(deg: float) -> int:
    """Оттенок из градусов (0..360) в шкалу Pillow (0..255)."""
    return int(deg * 255 / 360)



def _lut_mask(band, lo, hi):
    """Маска канала: 255 там, где значение лежит в [lo, hi], иначе 0."""
    lo, hi = int(lo), int(hi)
    return band.point([255 if lo <= v <= hi else 0 for v in range(256)])



def _hsv_count(h, s, v, hue, sat, val) -> int:
    """Число пикселей, у которых оттенок, насыщенность и яркость лежат в заданных диапазонах."""
    mask = _lut_mask(h, *hue)
    for band, rng in ((s, sat), (v, val)):
        mask = ImageChops.multiply(mask, _lut_mask(band, *rng))
    return mask.histogram()[255]



def classify_rarity_color(region):
    """OCR-ФИКС: ранг по цвету ТЕКСТА в области region (PIL.Image с названием предмета).

    Золотистый / жёлтый текст -> 5 (S), фиолетовый / пурпурный -> 4 (A), серый, белый или
    тёмный -> 3 (B). Если текста в области не нашлось (слишком мало пикселей) — None.

    Как считается: фоном считается медианный цвет области; «текст» — пиксели, заметно
    отличающиеся от фона (TEXT_FG_DIFF). Среди них считаются золотые и фиолетовые (по
    оттенку, насыщенности и яркости). Если одного из цветов не меньше
    TEXT_COLOR_MIN_FRACTION всех пикселей текста — это S или A (побеждает тот, которого
    больше); иначе текст бесцветный (серый / белый / тёмный) — это B."""
    img = region.convert("RGB")
    factor = max(1, max(img.size) // 640)  # уменьшаем крупные области (быстрее считать)
    if factor > 1:
        img = img.reduce(factor)
    if img.width * img.height < TEXT_MIN_PIXELS:
        return None
    bg = tuple(int(v) for v in ImageStat.Stat(img).median)
    diff = ImageChops.difference(img, Image.new("RGB", img.size, bg))
    dr, dg, db = diff.split()
    dmax = ImageChops.lighter(ImageChops.lighter(dr, dg), db)
    text_mask = dmax.point([255 if v >= TEXT_FG_DIFF else 0 for v in range(256)])
    text_px = text_mask.histogram()[255]
    if text_px < TEXT_MIN_PIXELS:
        return None
    h, s, v = img.convert("HSV").split()  # в Pillow H, S, V лежат в диапазоне 0..255

    def count(hue, sat, val) -> int:
        """Сколько пикселей ТЕКСТА попадает в цветовой диапазон."""
        mask = _lut_mask(h, *tuple(map(_hue255, hue)))
        for band, rng in ((s, (sat[0] * 255, 255)), (v, (val[0] * 255, 255))):
            mask = ImageChops.multiply(mask, _lut_mask(band, *rng))
        return ImageChops.multiply(mask, text_mask).histogram()[255]

    gold = count(GOLD_HUE, (GOLD_MIN_SAT,), (GOLD_MIN_VAL,))
    purple = count(PURPLE_HUE, (PURPLE_MIN_SAT,), (PURPLE_MIN_VAL,))
    if max(gold, purple) / text_px >= TEXT_COLOR_MIN_FRACTION:
        return 5 if gold >= purple else 4
    return 3



def _left_label_count(words: list) -> int:
    """ИСПРАВЛЕНО: число первых слов строки, образующих подпись ЛЕВОГО столбца («Подарок за очки»,
    «Страна сна»). Раньше подпись входила в рамку названия: цвет считался вместе с серыми буквами
    подписи (фиолетовая дуга читалась как серая), а название перечитывалось вместе с подписью, и
    Tesseract выдавал мусор («NlepeerEnx Ayana» вместо «Персонаж - Аурелия»)."""
    for k, label in ((3, "подарок за очки"), (2, "страна сна"), (3, "страна сна")):
        if len(words) <= k:
            continue
        joined = " ".join(w["text"] for w in words[:k])
        if (BONUS_MARK_RE if label[0] == "п" else STRANA_SNA_RE).search(joined) or difflib.SequenceMatcher(
                None, re.sub(r"\W", "", fold_name(joined)), fold_name(label.replace(" ", ""))).ratio() >= 0.72:
            return k
    return 0



def _label_canon(words: list, k: int) -> str:
    if not k:
        return ""
    joined = " ".join(w["text"] for w in words[:k])
    return "Страна сна" if (STRANA_SNA_RE.search(joined) or fold_name(joined)[:3] == fold_name("стр")) \
        and not BONUS_MARK_RE.search(joined) and fold_name(joined)[:1] != fold_name("п") else "Подарок за очки"



def _name_box(ln: dict):
    """OCR-ФИКС: рамка ТЕКСТА названия в строке (x0, y0, x1, y1) в пикселях исходного
    снимка — от первого слова до столбца «Количество» / «Время». Значки слева и числа с датой
    справа в рамку не входят, поэтому цвет считается только по буквам названия.
    Нет слов у строки — берётся левая часть рамки строки."""
    if ln.get("name_box"):               # рамка названия, найденная по цвету (_recover_missing_names)
        return tuple(int(v) for v in ln["name_box"])
    words = ln.get("words") or []
    first = next((i for i, w in enumerate(words) if _NAME_WORD_RE.search(w["text"])), None)
    if first is not None:
        label_n = _left_label_count(words[first:])
        first += label_n                                    # подпись левого столбца — не название
        lr = ln.get("label_right")
        if lr is not None:       # слова целиком в левом столбце (подпись, которую OCR исказил)
            while first < len(words) - 1 and words[first]["box"][2] <= lr + 4:
                first += 1
                label_n += 1
        idx = _right_column_index(words, first + 1)
        chosen = words[first:idx] if idx is not None else words[first:]
        if chosen:
            x0 = min(w["box"][0] for w in chosen)
            x1 = max(w["box"][2] for w in chosen)
            if label_n:        # слова названия могли слиться с подписью: рамка — от конца подписи
                x0 = min(x0, int(words[first - 1]["box"][2]) + 2)
                if idx is not None:
                    x1 = max(x1, int(words[idx]["box"][0]) - 4)
            return (x0, min(w["box"][1] for w in chosen), x1, max(w["box"][3] for w in chosen))
    left, top, right, bottom = ln["box"]
    left = int(ln.get("name_left", left))
    return left, top, left + int(0.55 * max(1, right - left)), bottom



def detect_rarity_colors(path: str, lines: list):
    """Цветовой анализ скриншота по ЦВЕТУ ТЕКСТА названия. Возвращает (ранги по строкам, None).

    OCR-ФИКС: вместо значка слева от названия (так ранг определялся в последней версии)
    анализируется вырезка с самим текстом названия каждой строки: жёлтый -> S (5),
    фиолетовый -> A (4), серый / белый / тёмный -> B (3). Второй элемент результата всегда
    None (цвет всего снимка не используется: на нём всегда есть золотые элементы).
    Нет Pillow, файл не открылся или текст не найден — ранг строки None."""
    empty = ([None] * len(lines), None)
    if Image is None:
        return empty
    try:
        img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError):
        return empty
    width, height = img.size
    ranks = []
    for ln in lines:
        x0, y0, x1, y1 = _name_box(ln)
        pad_x = max(4, (y1 - y0) // 3)
        pad_y = max(2, (y1 - y0) // 3)   # рамка слов бывает уже буквы с обводкой: золото обрезалось и читалось серым
        x0, x1 = max(0, x0 - pad_x), min(width, x1 + pad_x)
        y0, y1 = max(0, y0 - pad_y), min(height, y1 + pad_y)
        if x1 - x0 < 8 or y1 - y0 < 4:
            ranks.append(None)                           # области текста нет — цвет не используем
            continue
        ranks.append(classify_rarity_color(img.crop((x0, y0, x1, y1))))
    return ranks, None
