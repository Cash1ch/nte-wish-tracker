"""Русские даты и время на скриншотах (распознавание, разбор, нормализация)."""

import difflib
import re
from datetime import datetime
from pathlib import Path

from ..config import DATE_FMT


EXTRA_DATE_FORMATS = ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
                      "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y.%m.%d %H:%M:%S",
                      "%Y.%m.%d %H:%M", "%Y-%m-%d")



def _normalize_date(value) -> str:
    if value is None or str(value).strip() == "":
        raise ValueError("не указана дата")
    if isinstance(value, (int, float)) or re.fullmatch(r"\d{9,13}", str(value).strip()):
        ts = float(value)
        if ts > 1e11:  # миллисекунды
            ts /= 1000.0
        return datetime.fromtimestamp(ts).strftime(DATE_FMT)
    s = str(value).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt.strftime(DATE_FMT)
    except ValueError:
        pass
    # НОВОЕ: русская дата с названием месяца («30 апр. 2026 г. 12:03:36»)
    if RU_DATE_RE.search(s):
        return parse_russian_datetime(s)  # при неверной дате бросит ValueError
    for fmt in EXTRA_DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime(DATE_FMT)
        except ValueError:
            continue
    raise ValueError(f"не удалось разобрать дату: {value!r}")



# ----------------------------------------------------------------------------
# OCR скриншотов (pytesseract)
# ----------------------------------------------------------------------------
TESSERACT_WIN_PATH = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")



# Слова, которые сами по себе — тип добычи, а не название предмета
KEYWORD_SET = {"кубик", "костюм", "планер", "скин", "окраска", "фрагмент", "кешбэк", "кэшбэк",
               "кешбек", "cube", "outfit", "glider", "skin", "cashback"}



# ---------------------------------------------------------------------------
# ИСПРАВЛЕНО: русские даты со скриншота («30 апр. 2026 г. 12:03:36»)
# ---------------------------------------------------------------------------
# ПРИЧИНА БАГА: DATE_RE знал только числовые форматы («2026-04-30 12:03:36»,
# «30.04.2026 12:03»). Дата с названием месяца не находилась, поэтому она оставалась в
# названии предмета, а время записи подменялось текущим системным.
# Ключ — первые три буквы месяца (без «ё», в нижнем регистре): «апр.», «апреля», «апрель»
# сводятся к «апр». У мая две формы: «май» (именительный) и «мая» (родительный).
RU_MONTHS = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6,
             "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12}



# OCR-ФИКС 6 (даты): типичные искажения названия месяца. Tesseract читает «май» как «man»,
# «маи», «ман» и т. п. Ключи — написание ПОСЛЕ замены латинских «двойников» букв на русские
# (man -> ман, mai -> маи, cen -> сен). Словарь МОЖНО ДОПОЛНЯТЬ.
MONTH_OCR_TYPOS = {"ман": 5, "маи": 5, "мап": 5, "мам": 5, "мав": 5, "мау": 5, "мей": 5,
                   "мяи": 5, "мии": 5}



_LATIN_TO_CYR = str.maketrans({"a": "а", "c": "с", "e": "е", "k": "к", "m": "м", "o": "о",
                               "p": "р", "t": "т", "x": "х", "y": "у", "h": "н", "n": "н",
                               "b": "в", "i": "и", "u": "и", "r": "г"})



# День, который OCR прочитал буквой («Б май» = «6 май»; «З» = 3; «l», «I», «|» = 1)
DAY_OCR_LETTERS = {"б": 6, "з": 3, "l": 1, "i": 1, "|": 1}



def month_from_token(token: str):
    """OCR-ФИКС 6: номер месяца по слову с возможными опечатками OCR или None.
    Порядок: словарь искажений -> первые три буквы -> нечёткое сходство с трёхбуквенными
    основами (засчитывается, только если лучший результат относится к ЕДИНСТВЕННОМУ месяцу)."""
    t = (token or "").lower().replace("ё", "е").strip(".,")
    if len(t) < 2:
        return None
    f = t.translate(_LATIN_TO_CYR)
    for form in (t, f):
        if form in MONTH_OCR_TYPOS:
            return MONTH_OCR_TYPOS[form]
        if form[:3] in RU_MONTHS:
            return RU_MONTHS[form[:3]]
    if len(f) < 3:
        return None
    scores = {}
    for stem, num in RU_MONTHS.items():
        r = difflib.SequenceMatcher(None, f[:3], stem).ratio()
        scores[num] = max(scores.get(num, 0.0), r)
    best = max(scores.values())
    winners = [n for n, v in scores.items() if v == best]
    return winners[0] if best >= 0.66 and len(winners) == 1 else None



# Русская дата и время одной цепочкой. Допуски на типичные ошибки OCR:
#   * между днём и месяцем пробела может не быть («30апр.»);
#   * точка после месяца, запятые и «г.» необязательны (OCR часто читает «г» как «r»);
#   * разделитель времени — «:» или «;»; секунды необязательны.
# Название месяца берётся любым словом из 3–9 букв — так дата вырезается из названия
# предмета, даже если месяц распознан с ошибкой (тогда время просто не определится и его
# можно будет поправить вручную в списке). Проверка месяца — в parse_russian_datetime().
# OCR-ФИКС 6: день может быть прочитан буквой («Б май» = 6 мая; такая буква не должна быть
# концом другого слова), название месяца — от 2 букв (проверка — month_from_token()).
RU_DATE_RE = re.compile(
    r"(?<![\d:;.,/\-+×xх(])"
    r"(?P<d>(?<!\d)\d{1,2}(?!\d)|(?<![^\W\d_])[БбЗзlI|])[ \t]*(?P<m>[^\W\d_]{3,9})\.?,?[ \t]*(?P<y>(?:19|20)\d{2})(?!\d)[ \t]*(?:[гrГ]\.?)?,?[ \t]*"
    r"(?P<h>\d{1,2})[:;](?P<mi>\d{2})(?:[:;](?P<s>\d{2}))?(?!\d)", re.I)



# Общий поиск даты: числовые форматы (как раньше) ИЛИ русский формат.
# ВНИМАНИЕ: в RU_DATE_RE есть именованные группы, поэтому DATE_RE.findall() возвращает
# кортежи — для получения строк используйте DATE_RE.finditer() и m.group().
DATE_RE = re.compile(r"\d{4}[-/.]\d{2}[-/.]\d{2}[ T]\d{2}:\d{2}(?::\d{2})?"
                     r"|\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}(?::\d{2})?"
                     r"|" + RU_DATE_RE.pattern, re.I)



def _ocr_day(token: str):
    """День месяца из токена даты: число или буква-двойник цифры (Б -> 6)."""
    token = token.strip()
    if token.isdigit():
        return int(token)
    return DAY_OCR_LETTERS.get(token.lower())



def _stamp_from_match(m, day=None) -> str:
    month = month_from_token(m.group("m"))
    if month is None:
        raise ValueError(f"неизвестный месяц: {m.group('m')!r}")
    day = day if day is not None else _ocr_day(m.group("d"))
    if day is None:
        raise ValueError(f"неизвестный день: {m.group('d')!r}")
    try:
        dt = datetime(int(m.group("y")), month, day,
                      int(m.group("h")), int(m.group("mi")), int(m.group("s") or 0))
    except ValueError as e:  # 31 апреля, 25:99 и т. п.
        raise ValueError(f"невозможная дата: {e}") from e
    return dt.strftime(DATE_FMT)



def find_valid_date_match(text: str):
    """Первое совпадение DATE_RE, которое является настоящей датой."""
    for m in DATE_RE.finditer(text or ""):
        try:
            if m.groupdict().get("m") is not None:
                _stamp_from_match(m)
            else:
                _normalize_date(m.group())
        except ValueError:
            continue
        return m
    return None



def parse_russian_datetime(text: str) -> str:
    """Русская дата -> строка ISO «ГГГГ-ММ-ДД ЧЧ:ММ:СС» (формат DATE_FMT).

    Пример: «30 апр. 2026 г. 12:03:36» -> «2026-04-30 12:03:36».
    OCR-ФИКС 6: допускаются опечатки месяца («4 man.» = 4 мая) и день-буква («Б май» = 6 мая).
    Бросает ValueError, если это не русская дата, месяц неизвестен или дата невозможна."""
    for m in RU_DATE_RE.finditer(text or ""):
        try:
            return _stamp_from_match(m)
        except ValueError:
            continue
    raise ValueError(f"не русская дата: {text!r}")



# День-БУКВА, за которой скрываются несколько цифр: в шрифте игры «5» часто читается как «Б»,
# но «Б» бывает и настоящей «6». Первая цифра — запасной вариант, если контекста нет.
AMBIG_DAY_LETTERS = {"б": (6, 5)}



def soft_day_stamps(raw_date: str) -> list:
    """Если день в сыром тексте даты — неоднозначная буква («Б май» = 5 или 6 мая), возвращает
    список возможных меток времени (первая — по умолчанию), иначе пустой список."""
    m = next((x for x in RU_DATE_RE.finditer(raw_date or "")
              if month_from_token(x.group("m")) is not None), None)
    if not m:
        return []
    days = AMBIG_DAY_LETTERS.get(m.group("d").strip().lower())
    out = []
    for d in days or ():
        try:
            out.append(_stamp_from_match(m, d))
        except ValueError:
            pass
    return out if len(out) > 1 else []



def alt_day_stamp(raw_date: str):
    """OCR-ФИКС 6: запасной разбор даты, когда к дню приклеилась цифра количества
    («15 май» = количество 1 + день 5): день — только последняя цифра. None, если нельзя."""
    m = next((x for x in RU_DATE_RE.finditer(raw_date or "")
              if month_from_token(x.group("m")) is not None), None)
    if not m or not (m.group("d").isdigit() and len(m.group("d")) == 2):
        return None
    try:
        return _stamp_from_match(m, int(m.group("d")[-1]))
    except ValueError:
        return None
