"""Удаление служебных строк интерфейса игры из текста OCR и разбор строк."""

import difflib
import re

from .dates import DATE_RE, find_valid_date_match
from .names import (
    _find_timestamp, DICE_RE, normalize_iroy_text, normalize_zanku_text, split_fused_item_label,
    strip_leading_junk,
)


# ----------------------------------------------------------------------------
# НОВОЕ: очистка текста OCR от служебных строк интерфейса игры
# ----------------------------------------------------------------------------
# Фразы интерфейса, которые никогда не бывают названием предмета. Сравнение без учёта
# регистра, «ё/е» и знаков препинания. Список можно дополнять.
OCR_NOISE_PHRASES = (
    "Подробности доски", "История бросков", "Результат броска", "Количество",
    "Время получения", "Повторно воспроизвести анимацию первого входа?",
    "Название предмета",     # НОВОЕ: заголовок столбца таблицы истории
)



# Одиночные заголовки столбцов и кнопки: убираются, только если ВСЯ строка — это слово
# (строка «Ранг S» или «Время 2026-01-31 18:45» под это правило не попадает)
OCR_NOISE_WORDS = {"название", "предмет", "тип", "ранг", "редкость", "время", "дата",
                   "отмена", "закрыть", "назад", "подтвердить", "далее",
                   # заголовки столбцов таблицы дуг и слова колонки «Тип»
                   "дуги", "дуга", "чудо", "коробка", "чудокоробка"}



OCR_NOISE_FUZZY = 0.80      # порог сходства для строк с опечатками OCR



OCR_NOISE_MIN_FUZZY = 8     # нечётко сравниваются только фразы от 8 знаков



OCR_MAX_ROWS = 300          # предел числа строк, разбираемых с одного скриншота



def _norm_ui(text: str) -> str:
    """Форма для сравнения: нижний регистр, ё -> е, без знаков препинания и лишних пробелов."""
    return re.sub(r"[\W_]+", " ", (text or "").lower().replace("ё", "е")).strip()



def _noise_regex(phrase: str):
    """Регулярное выражение фразы: слова через любые разделители, «е» совпадает и с «ё»."""
    words = [re.escape(w).replace("е", "[её]") for w in _norm_ui(phrase).split()]
    return re.compile(r"[\W_]*".join(words), re.I | re.U)



_NOISE_FOLDED = tuple(_norm_ui(p) for p in OCR_NOISE_PHRASES)



_NOISE_REGEXES = tuple(_noise_regex(p) for p in OCR_NOISE_PHRASES)



# ---------------------------------------------------------------------------
# OCR-ФИКС 4: СТРОГИЙ фильтр служебной подсказки интерфейса игры
#   «Здесь отображаются записи о ваших бросках кубика за последние полгода.»
# Слово «кубика» из этой подсказки раньше распознавалось как ключевое слово и строка
# превращалась в фантомную запись «Твердый кубик (1 шт)». Теперь подсказка (целиком, любая
# её часть и любой вариант с опечатками OCR, в том числе разорванная на две строки)
# вырезается из текста ДО разбора строк — её нельзя ни сопоставить по ключевым словам,
# ни превратить в запись. Список шаблонов МОЖНО ДОПОЛНЯТЬ.
# ---------------------------------------------------------------------------
UI_NOTE_TEXT = "Здесь отображаются записи о ваших бросках кубика за последние полгода."



# Шаблоны (регистр не важен, между словами — любые разделители, включая перенос строки):
UI_NOTE_PATTERNS = tuple(re.compile(p, re.I | re.U) for p in (
    # вся фраза или её хвост, содержащий «бросках кубика»
    r"(?:здесь\W+)?(?:отобража\w*\W+)?(?:записи\W+)?(?:о\W+)?(?:ваших\W+)?"
    r"бросках?\W+кубик\w*(?:\W+за\W+последние\W+пол\W?года)?",
    r"(?:здесь\W+)?отобража\w*\W+записи(?:\W+о\W+ваших)?",   # «Здесь отображаются записи»
    r"записи\W+о\W+ваших\W+бросках?",                          # «записи о ваших бросках»
    r"за\W+последние\W+пол\W?года",                            # «за последние полгода»
    r"здесь\W+отобража\w*",                                     # «Здесь отображаются»
))



_UI_NOTE_NORM = _norm_ui(UI_NOTE_TEXT)



UI_NOTE_FUZZY = 0.75        # доля строки, совпадающая с подсказкой (для опечаток OCR)



UI_NOTE_MIN_LEN = 12        # более короткие обрывки нечётко не сравниваются



def strip_ui_notes_lines(lines: list) -> list:
    """OCR-ФИКС 4: предварительный фильтр. Вырезает служебную подсказку из списка строк и
    возвращает список ТОЙ ЖЕ длины (индексы строк, а значит и цвета рангов line_ranks, не
    сдвигаются). Подсказка ищется по склеенному тексту, поэтому находится и тогда, когда OCR
    разорвал её на две строки («… записи о ваших» / «бросках кубика за последние полгода»).
    Вырезанные символы заменяются пробелами; полностью служебные строки становятся пустыми."""
    lines = list(lines)
    joined = "\n".join(lines)
    mask = [False] * len(joined)
    for rx in UI_NOTE_PATTERNS:
        for m in rx.finditer(joined):
            for k in range(m.start(), m.end()):
                mask[k] = True
    out, pos = [], 0
    for ln in lines:
        seg = "".join(" " if mask[pos + k] else ch for k, ch in enumerate(ln))
        out.append(re.sub(r"\s+", " ", seg).strip())
        pos += len(ln) + 1                         # +1 — символ переноса строки
    return out



def is_ui_note_line(line: str) -> bool:
    """OCR-ФИКС 4: строка — служебная подсказка (или её обрывок с опечатками OCR).
    Настоящие строки таблицы содержат дату и под правило не попадают."""
    if any(rx.search(line or "") for rx in UI_NOTE_PATTERNS):
        return True
    if DATE_RE.search(line or ""):
        return False
    norm = _norm_ui(line)
    if len(norm) < UI_NOTE_MIN_LEN:
        return False
    sm = difflib.SequenceMatcher(None, norm, _UI_NOTE_NORM, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) / len(norm) >= UI_NOTE_FUZZY



# Колонка «Тип» в таблице дуг: «Чудо-коробка» / «Чудо коробка» / «Чудокоробка» (+ искажения OCR)
TYPE_COLUMN_RE = re.compile(r"(?<!\w)[чЧ][уyУ][дlл][оo0][\W_]*[кk][оo0][рp][оo0][бb6]\w*", re.I | re.U)



# Заголовки столбцов: «Дуги Тип Время», «Дуга - Тип Время», «Тип Время», «Дуги Тип»
HEADER_COMBO_RE = re.compile(
    r"(?<!\w)(?:д[уy][гr][аиaи]?)?[\s:|\-–—]*т[иu]п[\s:|\-–—]+(?:в[рp][еe]м[яа]|time)(?!\w)"
    r"|(?<!\w)д[уy][гr][аи][\s:|\-–—]+т[иu]п(?!\w)", re.I | re.U)



HEADER_WORDS = {"дуги", "дуга", "тип", "время", "type", "time"}



def strip_type_column(text: str) -> str:
    """Убирает из строки текст колонки «Тип» («Чудо-коробка») и заголовки столбцов
    («Дуги Тип Время»). Если ничего, кроме них, не было — возвращает пустую строку.
    Строки с датой (настоящие записи) сохраняют название и дату."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return ""
    t = TYPE_COLUMN_RE.sub(" ", t)
    t = HEADER_COMBO_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" |¦,;:-–—")
    words = _norm_ui(t).split()
    if not DATE_RE.search(t) and words and all(w in HEADER_WORDS for w in words):
        return ""                                   # остались только заголовки столбцов
    if _norm_ui(t) in ("дуга", "дуги", "чудо", "коробка"):
        return ""                                   # одинокая подпись типа без названия
    return t



def clean_ocr_line(line: str) -> str:
    """Строка без служебного текста интерфейса; пустая строка — если вся строка служебная
    или в ней нет ни слова, ни времени (одиночные цифры, «|», номера страниц)."""
    # OCR-ФИКС 4: служебная подсказка «… записи о ваших бросках кубика …» убирается первой
    line = strip_ui_notes_lines([line or ""])[0]
    if is_ui_note_line(line):
        return ""
    text = strip_type_column(line or "")            # «Чудо-коробка» и заголовки столбцов
    folded = _norm_ui(text)
    if not folded or folded in OCR_NOISE_WORDS:
        return ""
    # строка целиком похожа на служебную фразу (с опечатками OCR)
    for phrase in _NOISE_FOLDED:
        if (len(phrase) >= OCR_NOISE_MIN_FUZZY
                and abs(len(folded) - len(phrase)) <= max(3, len(phrase) // 4)
                and difflib.SequenceMatcher(None, folded, phrase).ratio() >= OCR_NOISE_FUZZY):
            return ""
    # служебная фраза внутри строки (например, заголовки столбцов в одну строку) — вырезаем
    for rx in _NOISE_REGEXES:
        text = rx.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if _norm_ui(text) in OCR_NOISE_WORDS:       # остался одиночный заголовок («Название»)
        return ""
    # без слов и без времени строка бесполезна
    if not (re.search(r"[^\W\d_]{2,}", text) or DATE_RE.search(text)):
        return ""
    return text



def filter_ocr_lines(lines: list) -> list:
    """Убирает служебные строки из результата ocr_image ([{"text", "box"}]).
    Рамки (box) остаются у своих строк, поэтому цветовой анализ рангов не сбивается."""
    out = []
    # OCR-ФИКС 4: подсказка вырезается по ВСЕМУ списку сразу (она может быть разорвана на
    # две строки), затем каждая строка очищается обычными правилами
    stripped = strip_ui_notes_lines([ln["text"] for ln in lines])
    for ln, src in zip(lines, stripped):
        text = clean_ocr_line(src)
        if text:
            out.append(dict(ln, text=text))
    return out



# ----------------------------------------------------------------------------
# НОВОЕ: разбор ВСЕХ круток со скриншота
# ----------------------------------------------------------------------------
_QTY_TOKEN_RE = re.compile(r"^[x×х]?\d{1,3}$", re.I)       # «1», «×5», «x30»



# ИСПРАВЛЕНО: кириллическая «С» убрана — это не S, а буква «Сэ»; она давала ложный ранг S
_RANK_TOKENS = {"S": "S", "A": "A", "B": "B", "А": "A", "В": "B"}  # + кириллица А/В



def _split_row_quantity(body: str):
    """(строка без количества, количество или None). Количество — отдельное число в конце
    или начале строки (столбец «Количество»), с «×» или без; слово «шт» отбрасывается."""
    tokens = body.split()
    if len(tokens) > 1 and tokens[-1].lower().strip(".") == "шт":
        tokens.pop()
    qty = None
    if len(tokens) > 1 and _QTY_TOKEN_RE.match(tokens[-1]):
        qty = re.sub(r"\D", "", tokens.pop())
    elif len(tokens) > 1 and _QTY_TOKEN_RE.match(tokens[0]):
        qty = re.sub(r"\D", "", tokens.pop(0))
    return " ".join(tokens), qty



def _split_row_rank(body: str):
    """(строка без буквы ранга, буква S/A/B или None). Одиночная заглавная буква ранга в
    начале или конце строки (столбец «Ранг»); разделители «|» убираются."""
    tokens = [t for t in body.split() if t.strip("|¦") != ""]
    letter = None
    if len(tokens) > 1 and tokens[-1].strip(".,:;") in _RANK_TOKENS:
        letter = _RANK_TOKENS[tokens.pop().strip(".,:;")]
    elif len(tokens) > 1 and tokens[0].strip(".,:;") in _RANK_TOKENS:
        letter = _RANK_TOKENS[tokens.pop(0).strip(".,:;")]
    return " ".join(tokens), letter



def prepare_ocr_row(line: str):
    """НОВОЕ: ЕДИНАЯ предобработка строки списка перед разбором — одинаковая для ВСЕХ строк
    пакета (и верхних, и нижних), поэтому правила больше не расходятся.
    Убирает значок кубика (запоминая его наличие) и одиночный мусор OCR по краям.
    Возвращает (строка, был_ли_значок_кубика). Звёзды ранга (★) не трогаются."""
    text = strip_type_column(line or "")
    has_dice = bool(DICE_RE.search(text))
    text = re.sub(r"\s+", " ", DICE_RE.sub(" ", text)).strip()
    # OCR-ФИКС 5: «8 персонажеиИрой» / «персонажиИрой» -> «Персонаж: Ирой» ДО отделения
    # количества (одиночная цифра слева не должна стать количеством) и до любых словарей
    text = normalize_iroy_text(text)[0]
    text = normalize_zanku_text(text)[0]            # OCR-ФИКС 7: «Мереспепх - Sexxy» -> Занку
    # OCR-ФИКС 2: мусор, двоеточия и знаки препинания в начале строки срезаются ДО разбора
    # («: Прут …»), затем разделяется слипшийся префикс «предметтолерянны …»
    text = split_fused_item_label(strip_leading_junk(text))
    return strip_leading_junk(text), has_dice



def split_ocr_line(line: str) -> dict:
    """НОВОЕ: делит строку скриншота на название, количество и дату (регулярными выражениями).

    Пример: «Дуга - Настоящая музыка 1 30 апр. 2026 г. 12:03:36» ->
        {"body": "Дуга - Настоящая музыка", "qty": "1",
         "raw_date": "30 апр. 2026 г. 12:03:36", "stamp": "2026-04-30 12:03:36"}
    Порядок действий:
      1) DATE_RE находит дату (числовую или русскую) — она вырезается из строки целиком;
      2) из остатка отделяется количество — отдельное число в конце/начале (_split_row_quantity);
      3) остаток — «чистое» название (дальнейшая очистка — в parse_ocr_result).
    stamp — дата в формате DATE_FMT или None, если даты нет / она не разобралась
    (raw_date при этом сохраняется — её можно показать пользователю)."""
    text = re.sub(r"\s+", " ", line or "").strip()
    m = find_valid_date_match(text)
    raw_date = m.group().strip() if m else ""
    stamp = _find_timestamp(raw_date) if raw_date else None
    # OCR-ФИКС: ПОСЛЕ даты в таблице ничего полезного нет — только мусор OCR от значков и
    # рамок («Ub», «|»). Он мешал найти количество: «… Фравмени 50 Ub». Оставляем лишь
    # числа (на случай другого порядка столбцов) и настоящие слова (от 3 букв).
    tail = ""
    if m:
        tail = " ".join(t for t in text[m.end():].split()
                        if _QTY_TOKEN_RE.match(t) or re.search(r"[^\W\d_]{3,}", t))
    rest = f"{text[:m.start()]} {tail}" if m else text
    rest = strip_leading_junk(re.sub(r"\s+", " ", rest)).strip(" |¦,;:")  # OCR-ФИКС 2
    body, qty = _split_row_quantity(rest)
    return {"body": body, "qty": qty, "raw_date": raw_date, "stamp": stamp}
