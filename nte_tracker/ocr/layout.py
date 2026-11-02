"""Слова, строки и столбцы таблицы по результату Tesseract."""

import re

from ..compat import pytesseract
from ..errors import OcrError
from .config import (
    _JUNK_EDGE_RE, _JUNK_WORD_RE, _NAME_WORD_RE, _QTY_WORD_RE, OCR_BASE_CONFIG, OCR_LOW_CONF,
    OCR_MIN_LETTER_RATIO, OCR_MIN_WORD_CONF, OCR_PSM_LAYOUT, OCR_PSM_SPARSE,
)
from .dates import DATE_RE, TESSERACT_WIN_PATH
from .noise import TYPE_COLUMN_RE
from .preprocess import _adaptive_binarize, _binarize_fallback, _save_debug


def _extract_words(data: dict, scale: float) -> list:
    """Слова из image_to_data: [{"text", "conf", "box"}]; рамка пересчитана обратно в пиксели
    исходного скриншота."""
    words = []
    for i, word in enumerate(data["text"]):
        word = word.strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if not word or conf < 0:
            continue
        left, top = data["left"][i], data["top"][i]
        right, bottom = left + data["width"][i], top + data["height"][i]
        words.append({"text": word, "conf": conf,
                      "box": tuple(int(v / scale) for v in (left, top, right, bottom))})
    return words



def _clean_words(words: list) -> list:
    """НОВОЕ: вычищает мусор из слов ДО сборки строк.
      * символы-рамки и маркеры по краям слова срезаются («|Дуга», «кубик**» -> «Дуга», «кубик»);
      * слова из одних лишних знаков («|», «**», «!») удаляются (дефис, «:», «×» остаются);
      * короткие слова (до 3 знаков) с низкой уверенностью удаляются — это почти всегда шум;
      * слишком высокие «слова» (значки и рамки, прочитанные как символ) удаляются."""
    heights = sorted(w["box"][3] - w["box"][1] for w in words)
    med_h = heights[len(heights) // 2] if heights else 0
    out = []
    for w in words:
        text = _JUNK_EDGE_RE.sub("", w["text"]).strip()
        if not text or _JUNK_WORD_RE.fullmatch(text):
            continue
        if len(text) <= 3 and w["conf"] < OCR_MIN_WORD_CONF:
            continue
        if med_h and (w["box"][3] - w["box"][1]) > 2.5 * med_h:
            continue
        out.append(dict(w, text=text))
    return out



def _group_words(words: list) -> list:
    """Собирает слова в строки по ВЕРТИКАЛЬНОМУ положению: слова, чьи центры по высоте близки,
    — одна строка таблицы (Tesseract мог разбить её на несколько блоков — отсюда дубликаты).
    Возвращает [{"text", "box": (l, t, r, b), "words": [...]}] сверху вниз."""
    rows = []   # каждая: {"cy", "h", "words"}
    for w in sorted(words, key=lambda w: (w["box"][1] + w["box"][3])):
        cy = (w["box"][1] + w["box"][3]) / 2
        h = max(1, w["box"][3] - w["box"][1])
        for r in rows[-3:]:                       # сравниваем только с ближайшими строками
            if abs(cy - r["cy"]) <= 0.6 * max(h, r["h"]):
                r["words"].append(w)
                n = len(r["words"])
                r["cy"] += (cy - r["cy"]) / n     # центр строки — скользящее среднее
                r["h"] = max(r["h"], h)
                break
        else:
            rows.append({"cy": cy, "h": h, "words": [w]})
    lines = []
    for r in rows:
        ws = sorted(r["words"], key=lambda w: w["box"][0])
        box = (min(w["box"][0] for w in ws), min(w["box"][1] for w in ws),
               max(w["box"][2] for w in ws), max(w["box"][3] for w in ws))
        lines.append({"text": " ".join(w["text"] for w in ws), "box": box, "words": ws})
    lines.sort(key=lambda ln: (ln["box"][1], ln["box"][0]))
    return lines



def _mean_conf(words: list) -> float:
    """Средняя уверенность Tesseract по словам (0 — если слов нет)."""
    return sum(w["conf"] for w in words) / len(words) if words else 0.0



# НОВОЕ: пороги проверки результата OCR (уверенность Tesseract — 0..100)
OCR_REVIEW_CONF = 70       # строка с уверенностью ниже — подсвечивается жёлтым и идёт в редактор



OCR_FALLBACK_CONF = 85     # запасное правило / словарь исправлений + уверенность ниже — проверка



FUZZY_REVIEW_SIM = 0.85    # итоговое название похоже на прочитанное меньше — проверка



def line_confidence(ln: dict):
    """НОВОЕ: уверенность Tesseract для строки (0–100) или None, если данных нет.
    Берётся уверенность названия (у перечитанного названия — конвейера Б); если слова с
    цифрами (дата, количество) читаются хуже — берётся меньшее значение: неверная дата
    нарушает хронологию, поэтому она тоже должна привлекать внимание."""
    words = ln.get("words") or []
    conf = ln.get("name_conf") or _mean_conf(words)
    if not conf:
        return None
    digit = [w["conf"] for w in words if re.search(r"\d", w.get("text", ""))]
    if digit:
        conf = min(conf, sum(digit) / len(digit))
    if ln.get("time_doubt"):                       # время прочитано по-разному — на проверку
        conf = min(conf, OCR_REVIEW_CONF - 1)
    return round(max(0.0, min(100.0, float(conf))), 1)



def _letter_ratio(text: str) -> float:
    """Доля букв среди непробельных знаков строки."""
    chars = re.sub(r"\s+", "", text)
    return len(re.findall(r"[^\W\d_]", chars)) / len(chars) if chars else 0.0



def _filter_table_lines(lines: list) -> list:
    """НОВОЕ: оставляет только строки таблицы.
      * строки с низкой долей букв без даты («| o |**», обрывки рамок) удаляются;
      * если на снимке есть строки с датой (они — «якоря» таблицы), строки заметно выше первой
        и ниже последней записи (заголовок окна, кнопки, подсказки) удаляются."""
    kept = [ln for ln in lines
            if DATE_RE.search(ln["text"]) or (_NAME_WORD_RE.search(ln["text"])
                                              and _letter_ratio(ln["text"]) >= OCR_MIN_LETTER_RATIO)]
    anchors = [ln for ln in kept if DATE_RE.search(ln["text"])]
    if not anchors:
        return kept
    heights = sorted(ln["box"][3] - ln["box"][1] for ln in anchors)
    med_h = heights[len(heights) // 2]
    top = min(ln["box"][1] for ln in anchors) - 3 * med_h
    bottom = max(ln["box"][3] for ln in anchors) + 3 * med_h
    return [ln for ln in kept if ln["box"][3] >= top and ln["box"][1] <= bottom]



def _tess_words(img, lang: str, psm: int, scale: float) -> list:
    """Один запуск Tesseract. Ошибки: TesseractNotFoundError -> OcrError,
    TesseractError пробрасывается (вызывающий пробует другой язык)."""
    try:
        data = pytesseract.image_to_data(img, lang=lang, config=f"--psm {psm} {OCR_BASE_CONFIG}",
                                         output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractNotFoundError as e:
        raise OcrError("Программа Tesseract OCR не найдена. Установите её в "
                       f"{TESSERACT_WIN_PATH.parent}, добавьте в PATH или положите папку "
                       "Tesseract-OCR рядом с программой.") from e
    return _clean_words(_extract_words(data, scale))



def _run_langs(img, psm: int, scale: float, langs=("rus+eng", "eng")):
    """Запуск Tesseract с запасным языком (без русского пакета — только английский).
    Возвращает (слова, язык, последняя ошибка)."""
    last_error = None
    for lang in langs:
        try:
            return _tess_words(img, lang, psm, scale), lang, None
        except pytesseract.TesseractError as e:
            last_error = e
    return None, None, last_error



def _layout_pass(gray, scale: float):
    """ПРОХОД 1: распознаёт весь снимок. Обычно ОДИН запуск (серая картинка, --psm 6).
    Если уверенность ниже OCR_LOW_CONF — одна попытка по бинаризованной картинке; если слов
    нет вовсе — одна попытка в режиме --psm 11. Возвращает (слова, язык)."""
    words, lang, err = _run_langs(gray, OCR_PSM_LAYOUT, scale)
    if words is None:
        raise OcrError(f"Ошибка распознавания:\n{err}")
    best = (sum(w["conf"] for w in words), words)
    if not words or _mean_conf(words) < OCR_LOW_CONF:
        for tag, make in (("otsu", _binarize_fallback), ("adaptive", _adaptive_binarize)):
            bw = make(gray)
            _save_debug("layout_" + tag, bw)
            alt, _, _ = _run_langs(bw, OCR_PSM_LAYOUT, scale, (lang,))
            if alt and sum(w["conf"] for w in alt) > best[0]:
                best = (sum(w["conf"] for w in alt), alt)
            if best[1] and _mean_conf(best[1]) >= OCR_LOW_CONF:
                break
    if not best[1]:
        alt, _, _ = _run_langs(gray, OCR_PSM_SPARSE, scale, (lang,))
        if alt:
            best = (0, alt)
    return best[1], lang



def _right_column_index(words: list, start: int = 1):
    """Индекс первого слова правых столбцов («Количество», «Время получения») в строке или None.
    Это либо отдельное число (количество), либо начало даты. Слова левее — название предмета."""
    offsets, pos = [], 0
    for w in words:
        offsets.append(pos)
        pos += len(w["text"]) + 1
    m = DATE_RE.search(" ".join(w["text"] for w in words))
    date_idx = None
    if m:
        date_idx = max(i for i, off in enumerate(offsets) if off <= m.start())
    for i in range(max(1, start), len(words)):
        if _QTY_WORD_RE.match(words[i]["text"]) or i == date_idx:
            return i
        # ИСПРАВЛЕНО (таблица дуг): между названием и временем стоит столбец «Тип»
        # («Чудо-коробка»). Раньше он попадал в рамку названия: цвет текста считался вместе с
        # серой подписью типа (золотые/фиолетовые дуги читались как серые), а название
        # перечитывалось вместе с «Чудо-коробка». Теперь столбец «Тип» — тоже правая колонка:
        # она начинается со слова «Чудо-коробка» либо после широкого разрыва между словами.
        if TYPE_COLUMN_RE.search(words[i]["text"]):
            return i
        try:
            prev, cur = words[i - 1]["box"], words[i]["box"]
            height = max(1, cur[3] - cur[1])
            if cur[0] - prev[2] > max(2.2 * height, 50):
                return i
        except (KeyError, TypeError, IndexError):
            pass
    return date_idx if date_idx is not None and date_idx >= start else None
