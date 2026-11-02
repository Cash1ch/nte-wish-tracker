"""Чтение и уточнение названий в колонке «Результат броска»."""

import difflib
import re

from ..compat import cv2, np, pytesseract
from .config import (
    _NAME_WORD_RE, OCR_B_CONF_MARGIN, OCR_ENHANCE_ROWS, OCR_GOOD_CONF, OCR_LOW_CONF, OCR_MIN_LETTER_RATIO,
    OCR_NAME_COL_FRACS, OCR_NAME_LANGS, OCR_NAME_MAX_CALLS, OCR_PAD, OCR_PSM_ROW,
)
from .dates import DATE_RE
from .enhance import (
    _color_fill_variants, _fill_rank_hint, _text_bbox, enhance_text_crop, enhance_text_crop_variants,
)
from .layout import _letter_ratio, _mean_conf, _right_column_index, _tess_words
from .names import _snap_rank_of, fold_name, lookalike_similarity, master_index
from .noise import clean_ocr_line, strip_type_column, TYPE_COLUMN_RE
from .preprocess import _available_langs, _save_debug
from .rarity import _label_canon, _left_label_count


def _read_name_enhanced(rgb_np, box: tuple, langs: list, debug_name: str = "",
                        color_first: bool = False):
    """КОНВЕЙЕР Б для одной строки: вырезает область названия из ИСХОДНОГО снимка (box — в
    пикселях исходника: x0, y0, x1, y1), улучшает копию (enhance_text_crop) и читает её как
    одну строку (--psm 7). Возвращает (текст, средняя уверенность)."""
    height, width = rgb_np.shape[:2]
    x0, y0 = max(0, box[0]), max(0, box[1])
    x1, y1 = min(width, box[2]), min(height, box[3])
    if x1 - x0 < 8 or y1 - y0 < 4:
        return "", 0.0
    crop = rgb_np[y0:y1, x0:x1]
    try:
        variants = enhance_text_crop_variants(crop)
    except cv2.error:
        variants = [enhance_text_crop(crop)]
    if color_first:                       # цветное название с обводкой: сначала маска по цвету
        variants = _color_fill_variants(crop) + variants
    best_text, best_conf = "", 0.0
    for v, row in enumerate(variants):
        if debug_name:
            _save_debug(f"{debug_name}{v}", row)
        for lang in langs:
            try:
                words = _tess_words(row, lang, OCR_PSM_ROW, 1.0)
            except pytesseract.TesseractError:
                continue
            text = " ".join(w["text"] for w in words).strip()
            conf = _mean_conf(words)
            if text and _NAME_WORD_RE.search(text) and conf > best_conf:
                best_text, best_conf = text, conf
            if best_text and best_conf >= OCR_GOOD_CONF:
                return best_text, best_conf
        if best_text and best_conf >= OCR_LOW_CONF and v >= 1:
            break
    return best_text, best_conf



# Флаг «сейчас обрабатывается баннер дуг». Дорогое перечитывание цветных названий
# (_recover_missing_names) нужно только в таблице дуг; в остальных баннерах оно не запускается,
# чтобы не замедлять распознавание. Выставляется перед запуском потоков OCR.
OCR_ARC_BANNER = False



def set_ocr_arc_banner(flag: bool):
    global OCR_ARC_BANNER
    OCR_ARC_BANNER = bool(flag)



def _line_name_part(ln: dict) -> str:
    """Название из текста строки (слева от даты, без «Чудо-коробка» и заголовков)."""
    t = strip_type_column(ln.get("text") or "")
    m = DATE_RE.search(t)
    return (t[:m.start()] if m else t).strip()



def _line_has_name(ln: dict) -> bool:
    """В строке есть прочитанное название (буквы слева от даты; «Чудо-коробка» и заголовки
    столбцов не считаются). Строка «только с датой» — название OCR не прочитал."""
    return bool(re.search(r"[^\W\d_]{2,}", _line_name_part(ln)))



def _date_start_x(ln: dict) -> int:
    """Левый край даты в строке (пиксели снимка): первое слово, с которого начинается дата."""
    words = ln.get("words") or []
    if words:
        offsets, pos = [], 0
        for w in words:
            offsets.append(pos)
            pos += len(w["text"]) + 1
        m = DATE_RE.search(" ".join(w["text"] for w in words))
        if m:
            idx = max(i for i, off in enumerate(offsets) if off <= m.start())
            return int(words[idx]["box"][0])
    return int(ln["box"][0])



NAME_CHAR_WIDTH = 0.74        # средняя ширина буквы названия в долях высоты текста (шрифт таблицы)



NAME_COMPLETE_RATIO = 0.6     # прочитано меньше 60% ожидаемых букв — название считается обрезанным



NAME_GOOD_SCORE = 0.88        # сходство с эталоном, при котором чтение признаётся надёжным



NAME_MIN_SCORE = 0.55         # ниже — кандидат с эталоном не связан



def _name_candidate_score(text: str, rank_hint=None):
    """Лучшее сходство прочитанного текста с названиями мастер-справочника: (оценка, название).
    При известном ранге (по цвету) сравнение идёт только с названиями этого ранга."""
    clean = re.sub(r"[^\w\s.]", " ", text or "")
    best = (0.0, "")
    for e in master_index():
        rk = _snap_rank_of(e)
        if rank_hint and rk and rk != rank_hint:
            continue
        sc = lookalike_similarity(clean, e["name"])
        if sc > best[0]:
            best = (sc, e["name"])
    return best



def _read_name_candidates(rgb_np, box: tuple, langs: list, rank_hint=None, debug_name: str = ""):
    """Несколько независимых прочтений названия из вырезки: цветовые маски + обычные варианты,
    режимы --psm 7 (строка) и --psm 8 (слово). Возвращает [(текст, уверенность)]; останавливается,
    как только найдено надёжное совпадение с эталоном."""
    height, width = rgb_np.shape[:2]
    x0, y0 = max(0, box[0]), max(0, box[1])
    x1, y1 = min(width, box[2]), min(height, box[3])
    if x1 - x0 < 8 or y1 - y0 < 4:
        return []
    crop = rgb_np[y0:y1, x0:x1]
    try:
        variants = _color_fill_variants(crop) + enhance_text_crop_variants(crop)
    except cv2.error:
        variants = _color_fill_variants(crop) + [enhance_text_crop(crop)]
    cands, calls = [], 0
    for v, row in enumerate(variants):
        if debug_name:
            _save_debug(f"{debug_name}{v}", row)
        for psm in (OCR_PSM_ROW, 8):
            for lang in langs:
                if calls >= OCR_NAME_MAX_CALLS:
                    return cands
                calls += 1
                try:
                    words = _tess_words(row, lang, psm, 1.0)
                except pytesseract.TesseractError:
                    continue
                text = " ".join(w["text"] for w in words).strip()
                if text and _NAME_WORD_RE.search(text):
                    cands.append((text, _mean_conf(words)))
                    if _name_candidate_score(text, rank_hint)[0] >= NAME_GOOD_SCORE:
                        return cands
    return cands



def _recover_missing_names(lines: list, src, lang: str) -> list:
    """ИСПРАВЛЕНО (таблица дуг): цветные названия (золото / розовый, чёрная обводка) первый
    проход Tesseract читает частично («ОИ», «Обн» вместо «Неверные врата», «Обнаженный клинок»)
    или не видит вовсе (в строке только дата). Для каждой строки вырезается столбец названия
    (левее столбцов «Тип» и «Время»); если название не прочитано или обрезано (букв заметно меньше,
    чем помещается в рамку текста), оно перечитывается несколькими способами по маске цвета, а
    из прочтений выбирается самое близкое к названиям справочника нужного ранга. Рамка текста
    запоминается (name_box) — по ней определяется ранг (S / A / B)."""
    if cv2 is None or np is None or not lines or not OCR_ARC_BANNER:
        return lines
    # ИСПРАВЛЕНО: это перечитывание рассчитано на таблицу дуг со столбцом «Тип». В таблице бросков
    # («Результат броска» / «Название предмета») столбцов другая геометрия, и оно портило
    # правильные названия («Настоящая музыка» -> «conanr», «Дуга - Мы.» -> «мы»); там названия
    # уже читаются по маске цвета в _refine_name_column.
    if _header_icon_center(lines) is not None:
        return lines
    if not any(DATE_RE.search(ln["text"]) and not ln.get("synthetic") for ln in lines):
        return lines
    avail = _available_langs()
    langs = [l for l in OCR_NAME_LANGS if all(p in avail for p in l.split("+"))] or [lang]
    if lang == "eng":
        langs = ["eng"]
    rgb_np = np.array(src)
    height, width = rgb_np.shape[:2]
    named_left = [int(ln["name_left"]) for ln in lines
                  if _line_has_name(ln) and ln.get("name_left") is not None]
    budget = OCR_ENHANCE_ROWS
    out = []
    for n, ln in enumerate(lines):
        m_date = DATE_RE.search(ln["text"])
        if ln.get("synthetic") or not m_date or budget <= 0:
            out.append(ln)
            continue
        date_left = _date_start_x(ln)
        x0 = int(date_left - OCR_NAME_COL_FRACS[0] * width)
        x1 = int(date_left - OCR_NAME_COL_FRACS[1] * width)
        if named_left:
            x0 = min(x0, min(named_left) - OCR_PAD)
        for w in ln.get("words") or ():                  # слова столбца «Тип» ограничивают справа
            if TYPE_COLUMN_RE.search(w["text"]):
                x1 = min(x1, int(w["box"][0]) - OCR_PAD)
        x0, x1 = max(0, x0), min(width, x1)
        top, bottom = int(ln["box"][1]), int(ln["box"][3])
        padv = max(OCR_PAD, int((bottom - top) * 0.6))
        y0, y1 = max(0, top - padv), min(height, bottom + padv)
        if x1 - x0 < 40 or y1 - y0 < 8:
            out.append(ln)
            continue
        crop = rgb_np[y0:y1, x0:x1]
        bbox = _text_bbox(crop)
        new = dict(ln)
        if bbox:
            new["name_box"] = (x0 + bbox[0], y0 + bbox[1], x0 + bbox[2], y0 + bbox[3])
            new["name_left"] = x0 + bbox[0]
        first = _line_name_part(ln)
        first_letters = len(re.findall(r"[^\W\d_]", first))
        rank_hint = _fill_rank_hint(crop)
        incomplete = not first_letters
        if bbox and first_letters:
            bw, bh = bbox[2] - bbox[0], max(1, bbox[3] - bbox[1])
            expected = 0.85 * bw / (NAME_CHAR_WIDTH * bh)
            incomplete = first_letters < NAME_COMPLETE_RATIO * expected
        if (first_letters and not incomplete
                and _name_candidate_score(first, rank_hint)[0] >= NAME_GOOD_SCORE):
            out.append(new)                              # название прочитано полностью и надёжно
            continue
        if first_letters and not incomplete and rank_hint == 3:
            out.append(new)                              # серое название прочитано целиком — оставляем
            continue
        budget -= 1
        cands = _read_name_candidates(rgb_np, (x0, y0, x1, y1), langs, rank_hint,
                                      f"line_{n:02d}_C")
        if first_letters:
            cands.append((first, 0.0))
        best, best_key = None, (-1.0, -1)
        for text, conf in cands:
            letters = len(re.findall(r"[^\W\d_]", text))
            if letters < 2:
                continue
            score = _name_candidate_score(text, rank_hint)[0]
            key = (round(score, 2), letters)
            if key > best_key:
                best, best_key = text, key
        if best and (best_key[0] >= NAME_MIN_SCORE or not first_letters):
            new.update(text=f"{best} {ln['text'][m_date.start():]}".strip(), refined=True,
                       text_src="C", recovered=True)
        out.append(new)
    return out



def _refine_name_column(lines: list, src, lang: str) -> list:
    """Определяет границы столбца «Название предмета» в каждой строке (поле name_left —
    левый край названия, нужен цветовому анализу значка слева) и перечитывает название
    КОНВЕЙЕРОМ Б (улучшенная копия строки) для каждой строки с названием (не более
    OCR_ENHANCE_ROWS). Текст конвейера Б берётся, если он не заметно хуже первого прохода
    (или первый проход был слабым). Количество и дата остаются из первого прохода.
    ВАЖНО: меняется только поле «text»; рамки («box», «words», «name_left») остаются
    прежними — конвейер А (цвет/ранг) читает именно их, поэтому его результат не меняется."""
    if not lines:
        return lines
    avail = _available_langs()
    langs = [l for l in OCR_NAME_LANGS if all(p in avail for p in l.split("+"))] or [lang]
    if lang == "eng":
        langs = ["eng"]
    rgb_np = np.array(src)                     # исходный снимок (RGB), конвейер Б только копирует
    budget = OCR_ENHANCE_ROWS
    label_right = _header_label_right(lines)
    out = []
    for n, ln in enumerate(lines):
        words = ln["words"]
        first = next((i for i, w in enumerate(words) if _NAME_WORD_RE.search(w["text"])), None)
        if first is None or not _line_has_name(ln):   # строка без названия (только дата) — не трогаем
            out.append(dict(ln, name_left=ln["box"][0]))
            continue
        label_n = _left_label_count(words[first:])
        label_text = _label_canon(words, label_n)
        first += label_n                      # название начинается ПОСЛЕ подписи левого столбца
        if label_right is not None:           # значок кубика, прочитанный как «ee» / «se?)»
            while first < len(words) - 1 and words[first]["box"][2] <= label_right + 4:
                first += 1
        idx = _right_column_index(words, first + 1)
        # одиночные знаки пунктуации перед столбцом количества — остатки разделителей
        cut = idx
        while cut is not None and cut - 1 > first and re.fullmatch(r"[\W_]+", words[cut - 1]["text"]):
            cut -= 1
        name_words = words[:cut] if cut is not None else words
        right_words = words[idx:] if idx is not None else []
        left = words[first]["box"][0]            # значки слева от названия отсекаются
        old_conf = _mean_conf(name_words)
        ln = dict(ln, name_left=left, text_src="A", name_conf=old_conf)   # + уверенность названия
        if budget <= 0 or not clean_ocr_line(ln["text"]):
            out.append(ln)
            continue
        right = (words[cut]["box"][0] - OCR_PAD // 2) if cut is not None else ln["box"][2] + OCR_PAD
        top, bottom = ln["box"][1], ln["box"][3]
        padv = max(OCR_PAD, (bottom - top) // 4)
        box = (int(left - OCR_PAD), int(top - padv), int(right), int(bottom + padv))
        budget -= 1
        # ИСПРАВЛЕНО: цветное название (золото / фиолетовый с чёрной обводкой) читается по маске
        # заливки: обычная бинаризация сливает обводку с буквами и даёт мусор
        try:
            colored = _fill_rank_hint(rgb_np[max(0, box[1]):box[3], max(0, box[0]):box[2]]) in (4, 5)
        except (ValueError, cv2.error):
            colored = False
        text, conf = _read_name_enhanced(rgb_np, box, langs, f"line_{n:02d}_B", color_first=colored)
        name_part = _line_name_part(ln)
        if label_n:
            name_part = " ".join(w["text"] for w in words[label_n:cut]) if cut is not None else ""
        better = colored and _NAME_WORD_RE.search(text) and (
            _name_candidate_score(text, None)[0] >= _name_candidate_score(name_part, None)[0] - 0.02
            or conf >= old_conf)
        if (_NAME_WORD_RE.search(text) and _letter_ratio(text) >= OCR_MIN_LETTER_RATIO
                and (better or conf >= old_conf - OCR_B_CONF_MARGIN or old_conf < OCR_LOW_CONF)):
            right_text = " ".join(w["text"] for w in right_words)
            ln = dict(ln, text=f"{label_text} {text} {right_text}".strip(), refined=True,
                      text_src="B", name_conf=conf)
        elif label_n:                                        # подпись сохраняем в любом случае
            ln = dict(ln, text=f"{label_text} {name_part} {' '.join(w['text'] for w in right_words)}".strip())
        out.append(ln)
    return out



def _header_icon_center(lines: list):
    """Центр столбца «Результат броска» (x) по заголовку таблицы, если он найден среди строк."""
    def like(word, target):
        return difflib.SequenceMatcher(None, fold_name(word), fold_name(target)).ratio() >= 0.75
    for ln in lines:
        words = ln.get("words") or ()
        hit = next((i for i, w in enumerate(words) if like(w["text"], "результат")), None)
        if hit is None:
            continue
        group = [words[hit]["box"]]
        if hit + 1 < len(words) and like(words[hit + 1]["text"], "броска"):
            group.append(words[hit + 1]["box"])
        return (min(b[0] for b in group) + max(b[2] for b in group)) / 2.0
    return None



def _header_label_right(lines: list):
    """Правая граница столбца «Результат броска» (x) по заголовку: всё, что целиком левее неё,
    — подпись левого столбца («Страна сна», «Подарок за очки») или значок, но не название."""
    def like(word, target):
        return difflib.SequenceMatcher(None, fold_name(word), fold_name(target)).ratio() >= 0.75
    for ln in lines:
        words = ln.get("words") or ()
        hit = next((i for i, w in enumerate(words) if like(w["text"], "результат")), None)
        if hit is None:
            continue
        box = words[hit]["box"]
        if hit + 1 < len(words) and like(words[hit + 1]["text"], "броска"):
            return float(words[hit + 1]["box"][2])
        return float(box[2] + 0.6 * (box[2] - box[0]))
    return None
