"""Распознавание и очистка названий: предметы, персонажи, дуги, мастер-справочник, жёсткие правила."""

import difflib
import json
import re

from PyQt6.QtCore import QDateTime

from ..catalog import (
    ARC_A_NAMES, ARC_B_NAMES, ARC_BANNER, ARC_KNOWN, ARC_S_NAMES, BONUS_TYPE_PREFIX, CYR_TO_LAT, DUGA_PREFIX,
    FIXED_RARITY, GLIDER_NAMES, GLIDER_PREFIX, LETTER_RANKS, loot_rarity, LOOT_TYPES, OUTFIT_KNOWN,
    OUTFIT_NAMES, OUTFIT_PREFIX, OUTFIT_RANK, rank_letter, RARITIES, REWARD_KINDS, ROSTER_KNOWN,
)
from ..config import QT_DATE_FMT
from ..labels import default_reward_name
from ..paths import search_roots
from .dates import _normalize_date, DATE_RE, find_valid_date_match, KEYWORD_SET


# Значок кубика (🎲, ⚀–⚅). Это ЗАПАСНОЙ признак: тип в первую очередь берётся из текста.
DICE_RE = re.compile("[\U0001F3B2\u2680-\u2685\uFE0F]+")



def _cube_qty(low: str) -> str:
    """Количество кубиков в строке: «5» для «×5» / «5 шт», иначе «1»."""
    return "5" if re.search(r"[x×х]\s*5\b|\b5\s*(?:шт|pcs)", low) else "1"



def split_fused_item_label(text: str) -> str:
    """OCR-ФИКС: разделяет слово «Предмет», слипшееся с названием.

    Tesseract читает «Предмет - Потерянный фрагмент» как «предметтолерянны Фравмени»: дефис и
    пробел потеряны, а «Предмет» приклеено к первому слову названия. Если первое слово строки
    длинное (9+ букв) и его начало похоже на «предмет» (допускаются ошибки OCR), оно
    разделяется: «предметтолерянны Фравмени» -> «Предмет - толерянны Фравмени».
    Обычные строки (в том числе имена персонажей) не меняются."""
    t = (text or "").lstrip(" |¦")
    m = re.match(r"([^\W\d_]{9,})(?=\s|$)", t)
    if not m:
        return text
    word = m.group(1)
    target = fold_name("предмет")
    best_k, best_score = 0, 0.0
    for k in (6, 7, 8):                       # «предмет» OCR мог потерять или добавить букву
        score = difflib.SequenceMatcher(None, fold_name(word[:k]), target).ratio()
        if score > best_score:
            best_k, best_score = k, score
    if best_score >= 0.80 and len(word) - best_k >= 4:
        return f"Предмет - {word[best_k:]}{t[m.end():]}"
    return text



# OCR-ФИКС 2: словарь известных искажений названий предметов. Из-за шрифта игры
# «Потерянный фрагмент» иногда читается как «Прут Фочеарякитый Фрезия». Слово из словаря
# (с допуском на одну-две опечатки OCR) делает строку предметом этого вида. Словарь МОЖНО
# ДОПОЛНЯТЬ: добавьте новое искажение в кортеж нужного вида.
GARBLED_ITEM_ALIASES = {
    # OCR-ФИКС 3: добавлены искажения «Потерянный фрагмент», которые Tesseract выдаёт из-за
    # шрифта игры («eB Tpamher Tlorepanneal реки», «толерянны Фравмени» и т. п.).
    "lost_fragment": ("Прут", "Фочеарякитый", "Фрезия",
                      "Tpamher", "Tlorepanneal", "Tlorepannei", "Tlorepaннeal",
                      "Фравмени", "Фрагмеит", "Фрагмени", "Потеряный", "Толерянны",
                      "Потерянныи", "Потерянныйфрагмент"),
}



GARBLED_MATCH_CUTOFF = 0.80   # минимальное сходство слова с искажением из словаря



GARBLED_MIN_LEN = 4           # короче 4 букв — только точное совпадение



# Количество, начиная с которого строка таблицы без префикса и без известного имени —
# предмет (потерянный фрагмент 30 / 50, фрагмент искривления 30), а не персонаж или дуга
LARGE_QTY_MIN = 30



# Символы-мусор в НАЧАЛЕ строки: всё, кроме букв, цифр и звёзд ранга ★ / ☆
_LEADING_JUNK_RE = re.compile(r"^(?:(?![★☆])[\W_])+")



_LOOKUP_SYMBOLS_RE = re.compile(r"[\[\]{}<>«»|¦\\/_~^`©®™•·°§=*#@]+")



_LOOKUP_LONE_RE = re.compile(r"(?<=\s)[^\w\s()\-–—:×★☆](?=\s)")



_TRAILING_JUNK_RE = re.compile(r"[\s.,;:!?\-–—'\"‘’“”]+$")



def clean_lookup_text(text: str) -> str:
    """Очистка строки ПЕРЕД поиском в мастер-справочнике: скобки, рамки, значки и одиночные
    знаки между словами заменяются пробелами; мусор в начале и конце срезается; повторы
    пробелов и точек схлопываются. Дефис, двоеточие, скобки-скобки «( )», «×» и «★» остаются."""
    t = _LOOKUP_SYMBOLS_RE.sub(" ", text or "")
    t = re.sub(r"\.{2,}", " ", t)
    t = re.sub(r"\s+", " ", t)
    t = _LOOKUP_LONE_RE.sub(" ", t)
    t = _TRAILING_JUNK_RE.sub("", t.strip())
    return re.sub(r"\s+", " ", strip_leading_junk(t)).strip()



def strip_leading_junk(text: str) -> str:
    """OCR-ФИКС 2: срезает с начала строки мусор до первой буквы или цифры: одиночные
    двоеточия, точки с запятой, дефисы, скобки, «|» и одиночные символы-мусор OCR
    («l», «I», «1») перед ними. «: Прут Фочеарякитый» -> «Прут Фочеарякитый»,
    «; Дуга - Клинок» -> «Дуга - Клинок». Звёзды ранга ★ / ☆ остаются."""
    t = (text or "").strip()
    for _ in range(4):                       # мусор мог идти вперемешку: «l : | Дуга»
        before = t
        t = _LEADING_JUNK_RE.sub("", t).strip()
        t = _trim_edge_junk(t)
        if t == before:
            break
    return t



def garbled_item_key(text: str):
    """OCR-ФИКС 2: ключ вида предмета (например, «lost_fragment»), если в тексте есть слово
    из словаря искажений GARBLED_ITEM_ALIASES, иначе None. Сравнение нечёткое: регистр,
    «ё/е» и похожие буквы (fold_name) не важны."""
    tokens = [t for t in re.findall(r"[^\W\d_]+", text or "") if len(t) >= GARBLED_MIN_LEN]
    for key, aliases in GARBLED_ITEM_ALIASES.items():
        for alias in aliases:
            target = fold_name(alias)
            for tok in tokens:
                folded = fold_name(tok)
                if folded == target or (
                        abs(len(folded) - len(target)) <= 2 and difflib.SequenceMatcher(
                            None, folded, target).ratio() >= GARBLED_MATCH_CUTOFF):
                    return key
    return None



# ---------------------------------------------------------------------------
# OCR-ФИКС 3: СТРОГОЕ правило «Потерянный фрагмент» (материал) — резерв для строк, которые
# из-за шрифта игры превращаются в мусор («eB Tpamher Tlorepanneal реки» и т. п.)
# ---------------------------------------------------------------------------
FRAGMENT_QTYS = ("30", "50")      # у потерянного фрагмента бывает только 30 или 50 шт



# Ключевые слова материала/фрагмента, включая типичные искажения OCR (кириллица + латиница):
# «фраг…», «фрагм…», «fragm…», «потер…» (потерянный), «tlor…» / «tpam…» (латинские
# двойники слов «Потерянный» / «Фрагмент»), «lost fr…».
FRAGMENT_KEYWORD_RE = re.compile(
    r"ф[рp][аa][гrвv]|фрагм|fragm|потер|tlor|tpam|lost\s*fr", re.I)



# Количество в сыром тексте после разбора строки: «×30», «x 50»
_RAW_QTY_RE = re.compile(r"[x×х]\s*(\d{1,3})(?!\d)", re.I)



# Порог «настоящего» имени: известное имя (история / состав / эталон дуги) не трогаем
FRAGMENT_KNOWN_CUTOFF = 0.80



def _qty_from_raw(text: str) -> str:
    """OCR-ФИКС 3: количество из хвоста «×N» сырого текста (или пустая строка)."""
    m = _RAW_QTY_RE.search(text or "")
    return m.group(1) if m else ""



def fragment_qty(qty, text: str = "") -> str:
    """OCR-ФИКС 3: количество потерянного фрагмента — строго «30» или «50».
    Цифры берутся из qty, а если их нет — из текста строки (отдельное 30 / 50). Любое
    значение, начинающееся на 5 («5», «50», «5О»), даёт 50, остальное — 30."""
    digits = re.sub(r"\D", "", str(qty or ""))
    if not digits:
        m = re.search(r"(?<!\d)(30|50)(?!\d)", text or "")
        digits = m.group(1) if m else ""
    return "50" if digits.startswith("5") else "30"



def warp_qty(qty, text: str = "") -> str:
    """Количество «Фрагмента искривления»: любое число 1…999 с экрана (в игре бывает 4, 16,
    30 …). Если цифр нет — 30."""
    digits = re.sub(r"\D", "", str(qty or ""))
    if not digits:
        m = re.search(r"(?<!\d)(\d{1,3})\s*(?:шт\.?)?\s*$", (text or "").strip())
        digits = m.group(1) if m else ""
    return str(int(digits)) if digits and 0 < int(digits) <= 999 else "30"



def _is_real_name(name: str, known: dict = None) -> bool:
    """OCR-ФИКС 3: настоящее (не мусорное) имя персонажа / дуги: есть в истории, в составе
    персонажей или похоже на эталонное название дуги. Нужна высокая точность совпадения,
    чтобы мусорная строка случайно не «прилипла» к имени."""
    name = (name or "").strip()
    if not name:
        return False
    index = {strip_labels(k, ("arc",)).lower(): k for k in (known or {})}
    if (name.lower() in index
            or difflib.get_close_matches(name.lower(), list(index), n=1,
                                         cutoff=FRAGMENT_KNOWN_CUTOFF)):
        return True
    if match_roster_name(name, cutoff=FRAGMENT_KNOWN_CUTOFF):
        return True
    snap = snap_known_phrase(name)
    return bool(snap and snap[1] not in ITEM_PHRASE_KEYS)      # эталон дуги («Забытое»…)



def strict_fragment_key(body: str, qty=None, known: dict = None):
    """OCR-ФИКС 3: «lost_fragment» / «warp_fragment» или None.

    Жёсткое правило «это материал, а не персонаж и не дуга». Срабатывает для строки без
    явного префикса «Дуга» / «Персонаж», которая НЕ является бонусом «Подарок за очки»
    и не содержит настоящего имени (история, состав, эталон дуги), если выполняется
    любое из условий:
      * есть ключевое слово фрагмента / материала (FRAGMENT_KEYWORD_RE), слово из словаря
        искажений (GARBLED_ITEM_ALIASES) или слово, похожее на «фрагмент»;
      * количество — 30 или 50 (у персонажей и дуг в таблице оно всегда 1), а название
        испорчено OCR и ни на какое известное имя не похоже.
    Вид «Фрагмент искривления» выбирается только при слове «искр» / «warp»."""
    if BONUS_MARK_RE.search(body or ""):
        return None                                    # бонусная добыча — не материал
    clean = strip_leading_junk(body or "")
    if leading_type(clean) in ("arc", "character"):
        return None                                    # явный префикс важнее догадок
    name = strip_labels(clean_name(clean), ("rank", "item"))
    if _is_real_name(name, known):
        return None
    low = clean.lower().replace("ё", "е")
    kind = "warp_fragment" if re.search(r"искр|warp", low) else "lost_fragment"
    if (FRAGMENT_KEYWORD_RE.search(clean) or garbled_item_key(clean)
            or _fragment_like_word(clean) or fragment_stem_hint(clean)):
        return kind
    digits = re.sub(r"\D", "", str(qty or ""))
    if not digits:
        m = re.search(r"(?<!\d)(30|50)(?!\d)", clean)
        digits = m.group(1) if m else ""
    if digits in FRAGMENT_QTYS or (digits and int(digits) >= LARGE_QTY_MIN):
        return kind
    return None



def forced_item_label(body: str, qty, known: dict = None):
    """OCR-ФИКС 2/3: жёсткое правило «это предмет, а не персонаж». Возвращает подпись вида
    «Предмет - Потерянный фрагмент» или None (тогда строка разбирается как обычно).

    Если обычный разбор (_loot_from_text) предмет сам не нашёл — решает строгое правило
    strict_fragment_key (ключевые слова, словарь искажений, количество 30 / 50)."""
    clean = strip_leading_junk(body)
    if leading_type(clean) in ("arc", "character"):
        return None                          # явный префикс важнее любых догадок
    if _loot_from_text(clean):
        return None                          # вид предмета нашёлся обычным способом
    key = strict_fragment_key(body, qty, known)
    return f"Предмет - {REWARD_KINDS[key]}" if key else None



def _fragment_like_word(text: str) -> bool:
    """OCR-ФИКС: есть ли в тексте слово, похожее на «фрагмент» («Фравмени», «фраг мент»)."""
    target = _phrase_form("фрагмент")
    tokens = re.findall(r"[^\W\d_]+", text or "")
    variants = tokens + [a + b for a, b in zip(tokens, tokens[1:])]
    return any(len(v) >= 5 and difflib.SequenceMatcher(None, _phrase_form(v), target).ratio() >= 0.70
               for v in variants)



def _item_key_from_snap(snap, low: str) -> str:
    """Ключ LOOT_TYPES по результату snap_known_phrase для предметов (кубики — с количеством)."""
    key = snap[1]
    return key + _cube_qty(low) if key in ("solid", "trick") else key



def recover_item_loot(body: str):
    """OCR-ФИКС («страховка»): пытается узнать предмет в строке, которую обычный разбор не
    смог определить. Вызывается только для строк с датой и количеством (то есть это
    точно запись таблицы). Возвращает эталонную подпись («Предмет - Потерянный фрагмент»)
    или None. Дуги и персонажи здесь не угадываются — только предметы."""
    rest = strip_labels(clean_name(split_fused_item_label(body)), ("rank", "item"))
    snap = snap_known_phrase(rest, PHRASE_RECOVER_CUTOFF, ITEM_PHRASE_KEYS)
    if snap:
        return f"Предмет - {snap[0]}"
    if _fragment_like_word(rest):             # искажённое «фрагмент»; «искр» — искривления
        return ("Предмет - Фрагмент искривления" if re.search(r"искр|warp", rest.lower())
                else "Предмет - Потерянный фрагмент")
    return None



def _loot_from_text(text: str, dice: bool = False):
    """Ключ LOOT_TYPES по тексту строки или None.

    ИСПРАВЛЕНО: порядок признаков (от надёжного к слабому):
      1) эталонное название с исправлением опечаток OCR (snap_known_phrase);
      2) ключевые слова: «кубик», «фрагмент», «костюм», «планер», «окраска», «скин», «кешбэк»;
      3) значок кубика 🎲 — только если в строке нет вообще никакого названия
         (раньше значок перебивал текст, и «🎲 Обнаженный клинок» становился кубиком).
    dice — значок кубика был в строке, но убран на этапе предобработки (prepare_ocr_row)."""
    low = text.lower().replace("ё", "е")
    snap = snap_known_phrase(text)
    if snap:
        key = snap[1]
        return key + _cube_qty(low) if key in ("solid", "trick") else key
    if "кубик" in low or "cube" in low:
        return ("trick" if re.search(r"шулер|trick", low) else "solid") + _cube_qty(low)
    if "фрагмент" in low or "fragment" in low:
        # «Фрагмент искривления» отличаем по корню «искр»; любой другой фрагмент считаем
        # потерянным — искажённое OCR слово «Потерянный» больше не теряет тип
        return "warp_fragment" if re.search(r"искр|warp", low) else "lost_fragment"
    for words, key in ((("окраск", "модификац"), "paint"), (("костюм", "outfit"), "outfit"),
                       (("планер", "glider"), "glider"), (("скин", "skin"), "car_skin")):
        if any(w in low for w in words):
            return key
    if any(w in low for w in ("кешб", "кэшб", "cashback")):
        return "cb_premium" if re.search(r"премиум|премиал|premium", low) else "cb_regular"
    # OCR-ФИКС: строка с префиксом «Предмет - …», название которой сильно искажено
    # («Предмет - толерянны Фравмени»). Раз это точно предмет, сравниваем с эталонами с
    # пониженным порогом и ищем искажённое слово «фрагмент»; дуги и персонажи не угадываются.
    # OCR-ФИКС 2: слово из словаря искажений («Прут», «Фочеарякитый», «Фрезия»)
    garbled = garbled_item_key(text)
    if garbled:
        return garbled
    if leading_type(text) == "item":
        rest = strip_labels(clean_name(text), ("rank", "item"))
        snap = snap_known_phrase(rest, PHRASE_ITEM_CUTOFF, ITEM_PHRASE_KEYS)
        if snap:
            return _item_key_from_snap(snap, low)
        if _fragment_like_word(rest):
            return "warp_fragment" if re.search(r"искр|warp", low) else "lost_fragment"
    if dice or DICE_RE.search(text):
        rest = strip_labels(clean_name(text), ("rank", "arc", "char", "item"))
        if not re.search(r"[^\W\d_]{3,}", rest):     # названия нет — остался только значок
            return "solid" + _cube_qty(low)
    return None



def _rarity_from_text(text: str):
    """Ранг, написанный в тексте: «ранг S», «rank A» или «5★» / ряд звёзд (старый вид).
    Возвращает 5/4/3 или None."""
    up = text.upper().translate(CYR_TO_LAT)
    m = re.search(r"(?:Р[АA]НГ|RANK)\W{0,3}([SAB])\b", up)
    if m:
        return LETTER_RANKS[m.group(1)]
    m = re.search(r"([345])\s*[★☆*]", text)
    if m:
        return int(m.group(1))
    m = re.search(r"[★☆*]{3,5}", text)
    return len(m.group()) if m else None



# ---------------------------------------------------------------------------
# НОВОЕ: очистка названий (персонаж / дуга)
# ---------------------------------------------------------------------------
JUNK_RE = re.compile(r"[|\[\]{}<>_~`\\^=]+")  # типичный мусор OCR



# Обозначения ранга внутри строки, которые не должны попасть в название
STAR_TOKEN_RE = re.compile(r"\(?\s*[345]\s*[★☆*]\s*\)?|[★☆*]{2,}|\b(?:ранг|rank)\W{0,3}[SAB]\b",
                           re.I)



# НОВОЕ: ранг в скобках — «(S)», «[A]»
RANK_PAREN_RE = re.compile(r"[(\[]\s*[SAB]\s*[)\]]")



# НОВОЕ: слова, по которым строка распознаётся как дуга
ARC_WORD_RE = re.compile(r"дуг|\barcs?\b|weapon|оружи", re.I)



# Префиксы, которые снимаются с начала названия:
#   ранг: «S », «Ранг A:», «Rank B -» (одиночная латинская S/A/B или кириллическая А/В);
#   тип дуги: «Дуга -», «Дуги:», «Arc», «Weapon»;
#   тип персонажа: «Персонаж:», «Character».
_RANK_PREFIX_RE = re.compile(r"^(?:(?i:ранг|rank)\W{0,3})?(?:[SAB]|[АВ])(?!\w)[\s:.\-–—)\]|]*")



_ARC_PREFIX_RE = re.compile(r"^(?i:[дл][уy][гrт][аиуеойa]*|arcs?|weapons?|оружие)(?!\w)[\s:.\-–—]*")



_CHAR_PREFIX_RE = re.compile(r"^(?i:персонаж\w*|character)(?!\w)[\s:.\-–—]*")



_QTY_SUFFIX_RE = re.compile(r"[\s(]*[x×х]\s*\d+\)?$", re.I)  # хвост «×1», «x 5»



# НОВОЕ: общий префикс предмета «Предмет - Твердый кубик» (с допусками на ошибки OCR).
# Он снимается из названия и сам по себе НЕ делает строку персонажем.
_ITEM_LABEL_RE = re.compile(r"^(?i:пр[еe]дм[еe][тn]\w*|items?)(?!\w)[\s:.\-–—]*")



_LABEL_PATTERNS = {"rank": _RANK_PREFIX_RE, "arc": _ARC_PREFIX_RE, "char": _CHAR_PREFIX_RE,
                   "item": _ITEM_LABEL_RE}



ALL_LABELS = ("rank", "arc", "char", "item")



EDGE_JUNK_TOKENS = {"l", "I", "i", "1", "|", "!"}  # одиночные символы-мусор по краям



def clean_name(text: str) -> str:
    """Чистое название: без даты, обозначений ранга, мусорных символов OCR,
    непечатаемых символов и двойных пробелов."""
    # ИЗМЕНЕНО: дополнительно убирается ранг в скобках «(S)», «[A]»
    text = RANK_PAREN_RE.sub(" ", STAR_TOKEN_RE.sub(" ", DATE_RE.sub(" ", text)))
    text = JUNK_RE.sub(" ", EMOJI_RE.sub(" ", text))
    text = "".join(ch if ch.isprintable() else " " for ch in text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^[\W_]+|[\W_]+$", "", text)



# ИСПРАВЛЕНО: лишнее число между повторяющимися префиксами. OCR читает значок ранга или номер
# строки как цифру: «Дуга - 8 Дуга - Настоящая музыка». Одно-двузначное число в начале
# снимается, только если сразу за ним идёт служебный префикс (название с цифры не страдает).
_LEAD_NUM_RE = re.compile(r"^\d{1,2}(?!\d)[\s.):\-–—]*")



def _peel_labels(text: str, kinds=ALL_LABELS):
    """НОВОЕ: снимает с начала строки служебные префиксы (ранг, «Дуга -», «Персонаж:»),
    повторяющиеся префиксы, лишнее число между ними и хвост «×N».
    Возвращает (очищенный текст, список снятых префиксов: «rank» / «arc» / «char»).
    Префикс не снимается, если после него ничего не останется."""
    text = (text or "").strip()
    found = []
    for _ in range(6):  # несколько проходов: «Дуга - 8 Дуга - Имя» -> «Имя»
        before = text
        for kind in kinds:
            m = _LABEL_PATTERNS[kind].match(text)
            if m and text[m.end():].strip():
                text = text[m.end():].strip()
                found.append(kind)
        m = _LEAD_NUM_RE.match(text)
        if m:
            rest = text[m.end():].strip()
            if rest and any(_LABEL_PATTERNS[k].match(rest) for k in kinds):
                text = rest
        no_qty = _QTY_SUFFIX_RE.sub("", text).strip()
        if no_qty:
            text = no_qty
        if text == before:
            break
    return text, found



def strip_labels(text: str, kinds=ALL_LABELS) -> str:
    """Название без служебных префиксов и хвоста «×N» (см. _peel_labels)."""
    return _peel_labels(text, kinds)[0]



def leading_type(text: str):
    """Тип по ПРЕФИКСУ строки: «arc» («Дуга - …»), «character» («Персонаж: …»),
    «item» («Предмет - …») или None.

    OCR-ФИКС 2: строка сначала очищается от мусора в начале («: Дуга - …»), затем
    пропускаются ранг («S», «Ранг A») и лишнее число перед префиксом, и тип определяется
    по ПЕРВОМУ служебному префиксу. Префикс важнее слов внутри названия и всего, что
    осталось от OCR. «Предмет - …» — это предмет, а не персонаж. Префикс, после которого
    ничего не остаётся, не считается."""
    t = strip_leading_junk(clean_name(text))
    kinds = (("arc", "arc"), ("char", "character"), ("item", "item"))
    for _ in range(6):
        before = t
        for label, result in kinds:
            m = _LABEL_PATTERNS[label].match(t)
            if m and t[m.end():].strip():
                return result
        for rx in (_RANK_PREFIX_RE, _LEAD_NUM_RE):   # ранг / номер перед префиксом
            m = rx.match(t)
            if m and t[m.end():].strip():
                t = strip_leading_junk(t[m.end():])
        if t == before:
            break
    return None



# ---------------------------------------------------------------------------
# НОВОЕ: «Подарок за очки» — бонусная (дополнительная) добыча
# ---------------------------------------------------------------------------
# Строка вида «Подарки за очки: Дуга - Забытое» или «Подарок за очки дуга Забытое» — это
# бонусная добыча за каждые 10 круток, а не обычная крутка. Допуски на ошибки OCR:
# латинские «o»/«a» вместо кириллических, окончание слов, любые разделители после фразы.
# Также распознаётся подпись самой механики: «Дополнительная добыча», «Бонусная добыча»
# и хвост «(бонус 10 круток)». Фраза вырезается из текста — остаётся чистое название.
# ИСПРАВЛЕНО (СТРОГИЙ фильтр): бонусом считается ТОЛЬКО строка с фразой «Подарок за очки».
# Раньше сюда же попадали «Дополнительная добыча» / «(бонус 10 круток)» — из-за этого обычные
# предметы (кубики, планеры, костюмы) могли ошибочно стать бонусными.
# OCR-ФИКС 3: допуски расширены — «Подарок», «Подарки», «Подаро», «Пoдapок» (латиница/цифра 0
# вместо кириллицы), слитное «заочки», окончание слова «очки» любое.
BONUS_MARK_RE = re.compile(
    r"\bп[оo0]д[аa][рp]\w{0,4}\s*[зз3][аa]\s*[оo0]ч\w*[\s:.\-–—]*", re.I)



# Подписи механики бонуса из интерфейса игры: из названия вырезаются, но бонусом строку НЕ делают.
BONUS_NOISE_RE = re.compile(
    r"\b(?:доп\w*\.?|бонусн\w*)\s*добыч\w*[\s:.\-–—]*|\(\s*бонус[^)]*\)?", re.I)



# ---------------------------------------------------------------------------
# OCR-ФИКС 3: словарь исправлений названий БОНУСНЫХ наград («Подарок за очки»).
# Ключ — эталонное слово названия, значение — (итоговое название, ключ типа LOOT_TYPES).
# OCR читает «Дуга» как «Муга», «Мута» и т. п., а название — с опечатками
# («Забытое» -> «Забытоe», «Забытов»). Словарь МОЖНО ДОПОЛНЯТЬ новыми бонусными дугами.
# ---------------------------------------------------------------------------
BONUS_ITEM_CORRECTIONS = {
    "Забытое": ("Дуга - Забытое", "arc"),
}



BONUS_WORD_CUTOFF = 0.72       # минимальное сходство слова названия с эталоном



BONUS_ARC_WORD_CUTOFF = 0.70   # минимальное сходство «Муга» / «Дуг» со словом «Дуга»



def _arc_word_like(token: str) -> bool:
    """OCR-ФИКС 3: слово похоже на «Дуга» («Муга», «Дуг», «Дyгa»): 3–5 букв и сходство
    со словом «Дуга» не ниже BONUS_ARC_WORD_CUTOFF. Имена персонажей из состава — нет."""
    if not 3 <= len(token) <= 5 or fold_name(token) in ROSTER_FOLDED:
        return False
    return difflib.SequenceMatcher(None, fold_name(token), fold_name("дуга")).ratio() \
        >= BONUS_ARC_WORD_CUTOFF



def fix_bonus_item_text(text: str) -> str:
    """OCR-ФИКС 3: исправляет искажённое название бонусной награды (текст УЖЕ без фразы
    «Подарок за очки»). Слово из BONUS_ITEM_CORRECTIONS (с опечатками OCR) вместе со всеми
    стоящими перед ним словами, похожими на «Дуга» («Муга Забытое»), заменяется итоговым
    названием («Дуга - Забытое»). Если известного названия нет, а первое слово похоже на
    «Дуга», оно заменяется на «Дуга» («Муга Клинок» -> «Дуга Клинок»), чтобы бонус никогда
    не стал персонажем. Остальной текст (ранг, ×N, дата) не меняется."""
    tokens = list(re.finditer(r"[^\W\d_]+", text or ""))
    for word, (canon, _key) in BONUS_ITEM_CORRECTIONS.items():
        target = fold_name(word)
        for i, tok in enumerate(tokens):
            folded = fold_name(tok.group())
            if len(folded) < 5 or abs(len(folded) - len(target)) > 2:
                continue
            if folded != target and difflib.SequenceMatcher(
                    None, folded, target).ratio() < BONUS_WORD_CUTOFF:
                continue
            start, j = tok.start(), i - 1
            while j >= 0 and _arc_word_like(tokens[j].group()):   # «Дуга - Муга Забытое»
                start, j = tokens[j].start(), j - 1
            return f"{text[:start]}{canon}{text[tok.end():]}"
    if len(tokens) > 1 and _arc_word_like(tokens[0].group()):
        return f"{text[:tokens[0].start()]}Дуга{text[tokens[0].end():]}"
    return text



# Значки и эмодзи (🎲 и т. п.), которые OCR/копирование может оставить в строке
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]+")



def _trim_edge_junk(text: str) -> str:
    """НОВОЕ: убирает одиночные символы-мусор OCR («l», «|», «1»…) по краям названия."""
    words = text.split()
    while len(words) > 1 and words[0] in EDGE_JUNK_TOKENS:
        words.pop(0)
    while len(words) > 1 and words[-1] in EDGE_JUNK_TOKENS:
        words.pop()
    return " ".join(words)



# ---------------------------------------------------------------------------
# OCR-ФИКС 5: СТРОГИЕ правила для «Занку» и «Ирой» (одни и те же на всех трёх вкладках со
# скриншотами: «Скриншот», «Скриншот оптом», «Скриншоты разом» — все они разбирают текст через
# ocr_extract_pulls_ex -> prepare_ocr_row / master_match / parse_ocr_result)
# ---------------------------------------------------------------------------
# OCR-ФИКС 7: ТОЛЬКО строки с точным текстом «Страна сна» или «Подарок за очки» вне гаранта
# (сохраняются в историю, но не прибавляют крутку и не двигают гарант). Остальное — как обычно.
NON_PITY_RE = re.compile(r"страна\s*сна|подарок\s*за\s*очки", re.I)



STRANA_SNA_RE = re.compile(r"страна\s*сна", re.I)



# 1) Строка с ключевым словом предмета / ресурса («кубик», «фрагмент», «passer» …) — ВСЕГДА
#    предмет или ресурс и НИКОГДА не персонаж (мусор вроде «:: passer THepaEAn кубик» раньше
#    нечётким поиском превращался в «Занку»). Ключевые слова МОЖНО ДОПОЛНЯТЬ.
RESOURCE_KEYWORD_RE = re.compile(
    r"к[уyu][б6b][иuinн]?[кk]|\bcubes?\b|ф[рp][аa][гrвv]м|фрагм|fragm|passer|"
    r"т[вb]ерд(?:ый|ыи|ы|ое)?(?!\w)|шулер\w*|потер\w*\s*фр|lost\s*fr|искривл|"
    r"reamnear|tespep|fipas\w*|gpami\w*|зетавя\w*", re.I)



_RESOURCE_SQUASHED_RE = re.compile(
    r"кубик|фрагмент|fragment|passer|reamnear|fipasere|gpamicer|искривлен", re.I)



_CUBE_WORD_RE = re.compile(
    r"к[уyu][б6b][иuinн]?[кk]|\bcubes?\b|passer|reamnear|tespep|т[вb]ерд(?:ый|ыи|ы|ое)?(?!\w)",
    re.I)



# OCR-ФИКС 6: признаки «Фрагмента искривления» (в т. ч. искажения «fipasere Gpamicer»)
_WARP_WORD_RE = re.compile(r"искр|warp|fipas|gpami|зетавя", re.I)



def is_resource_text(text: str) -> bool:
    """OCR-ФИКС 5: в строке есть ключевое слово предмета / ресурса (кубик, фрагмент, passer …).
    Такая строка никогда не сопоставляется с персонажем. «Подарок за очки» сюда не входит:
    бонус может выдать и настоящего персонажа — для него запрещены только нечёткие догадки
    (см. master_match)."""
    t = text or ""
    return bool(RESOURCE_KEYWORD_RE.search(t)
                or _RESOURCE_SQUASHED_RE.search(re.sub(r"\s+", "", t)))



def hard_item_kind(text: str):
    """OCR-ФИКС 6: ЖЁСТКОЕ правило предметов. Строка с ключевым словом («кубик», «твердый»,
    «фрагмент», «искривления», «passer», «reamnear», «fipasere» …) — ВСЕГДА предмет и никогда не
    персонаж. Возвращает вид («solid_cube», «trick_cube», «warp_fragment», «lost_fragment») или
    None. Явная «Дуга - …» исключена. «Подарок за очки» сам по себе ключевым словом не
    является (бонус бывает и дугой/персонажем): для него запрещён только нечёткий подбор."""
    if not is_resource_text(text):
        return None
    if leading_type(strip_leading_junk(text)) == "arc":
        return None
    low = (text or "").lower().replace("ё", "е")
    if _CUBE_WORD_RE.search(low):
        return "trick_cube" if re.search(r"шулер|trick", low) else "solid_cube"
    return "warp_fragment" if _WARP_WORD_RE.search(low) else "lost_fragment"



# 2) «Ирой» с приставшей подписью интерфейса: «персонажиИрой», «персонажИрой»,
#    «8 персонажеиИрой», «персонаженИрой», «Nepconark Hpou» …. Слово «Персонаж» (с любыми
#    искажениями и до 4 лишних букв после него) + имя «Ирой» (с «двойниками» букв).
_IROY_LABEL = r"[пnmм][еeё][рp][сc][оo0][нnh][аa][жxk]"



IROY_UI_RE = re.compile(
    rf"{_IROY_LABEL}[^\W\d_]{{0,4}}?[\s:.\-–—|]*"
    r"[иuiнhnm1l][рpп][оo0][йиiuлn]{1,2}(?![^\W\d_])", re.I | re.U)



IROY_NAME = "Ирой"



IROY_PLAIN_RE = re.compile(r"ирой(?![^\W\d_])", re.I)



_IROY_PREFIX_RE = re.compile(r"персонаж\w*|nepconar\w*|mepconax\w*", re.I)



def strip_iroy_ui_prefix(text: str):
    """OCR-ФИКС 6: (новый текст, найдено ли). Если в строке есть «ирой», ВСЕ приставшие подписи
    интерфейса слева («персонажи», «персонаж», «персонажен», «персонажеи», ведущие цифры,
    знаки) срезаются, остаток — строго «Персонаж: Ирой» + хвост (количество, дата). Если слева
    остались настоящие слова (не подпись), строка не меняется. Работает ДО нечёткого поиска."""
    t = text or ""
    m = IROY_PLAIN_RE.search(t)
    if not m:
        return t, False
    left = t[:m.start()]
    if re.search(r"[^\W\d_]{2,}", _IROY_PREFIX_RE.sub(" ", left)):
        return t, False
    keep = "".join(re.findall(r"[★☆]", left))
    head = f"{keep} " if keep else ""
    return re.sub(r"\s+", " ", f"{head}{CHARACTER_LABEL_WORD}: {IROY_NAME}{t[m.end():]}").strip(), True



def normalize_iroy_text(text: str):
    """OCR-ФИКС 5: (новый текст, найдено ли). Если в тексте есть «Ирой» вместе со словом
    интерфейса «Персонаж» (в любом искажении), мусор слева и приставшая подпись срезаются, а
    остаток становится строго «Персонаж: Ирой» (хвост — количество, дата — не трогается).
    Звёзды ранга слева сохраняются."""
    t = text or ""
    m = IROY_UI_RE.search(t)
    if not m:
        return strip_iroy_ui_prefix(t)         # OCR-ФИКС 6: «8 персонажеиирой» и т. п.
    left = t[:m.start()]
    keep = "".join(re.findall(r"[★☆]", left))
    if re.search(r"[^\W\d_]{2,}", left):              # слева настоящие слова — оставляем их
        keep = left.rstrip()
    head = f"{keep} " if keep else ""
    fixed = f"{head}{CHARACTER_LABEL_WORD}: {IROY_NAME}{t[m.end():]}"
    return re.sub(r"\s+", " ", fixed).strip(), True



# OCR-ФИКС 7: «Занку». Tesseract превращает жёлтый/оранжевый текст «Персонаж - Занку» в мусор вроде
# «Мереспепх - Sexxy». Любая из частей (мереспепх / sexxy / занку и их «двойники» букв), даже
# несколько подряд, превращается в «Персонаж: Занку». Строки с ключевыми словами предметов
# («кубик», «фрагмент» …) не затрагиваются — предметы никогда не становятся персонажем.
ZANKU_NAME = "Занку"



_ZANKU_PART = (r"[mм][еe][рp][еe][сc][пn][еe][пn][xх]|[sS][еe][xх]{1,3}[yу]|"
               r"[зzs3][аa][нh][кk][уy]")



ZANKU_UI_RE = re.compile(
    rf"(?:{_ZANKU_PART})(?:[\s:.\-–—|]*(?:{_ZANKU_PART}))*(?![^\W\d_])", re.I | re.U)



def normalize_zanku_text(text: str):
    """OCR-ФИКС 7: (новый текст, найдено ли). Слева допускаются только подпись «Персонаж»
    (любой вариант), цифры и знаки; результат — «Персонаж: Занку» + хвост (количество, дата).
    В бонусной строке («Подарок за очки») срабатывает только точное имя «Занку»."""
    t = text or ""
    m = ZANKU_UI_RE.search(t)
    if not m or is_resource_text(t):
        return t, False
    if BONUS_MARK_RE.search(t) and not re.fullmatch(r"(?i)занку", m.group().strip()):
        return t, False
    left = t[:m.start()]
    if re.search(r"[^\W\d_]{2,}", _IROY_PREFIX_RE.sub(" ", left)):
        return t, False
    keep = "".join(re.findall(r"[★☆]", left))
    head = f"{keep} " if keep else ""
    return re.sub(r"\s+", " ", f"{head}{CHARACTER_LABEL_WORD}: {ZANKU_NAME}{t[m.end():]}").strip(), True



def clean_character_name(text: str) -> str:
    """НОВОЕ: оставляет ТОЛЬКО чистое имя персонажа: без даты, ранга («S», «Ранг A»,
    «(S)», «5★»), слова «Персонаж», мусора OCR и лишних пробелов.
    OCR-ФИКС 5: «персонажиИрой» / «персонажИрой» -> «Ирой» (подпись интерфейса срезается)."""
    if normalize_iroy_text(text)[1]:
        return IROY_NAME
    if normalize_zanku_text(text)[1]:
        return ZANKU_NAME
    name = strip_labels(clean_name(text), ("rank", "char", "item"))
    name = clean_name(_trim_edge_junk(name))
    return "" if re.fullmatch(r"[x×х]?\s*\d+", name, re.I) else name  # одно число — не имя



def format_duga_name(text: str) -> str:
    """НОВОЕ: приводит название дуги к виду «Дуга - Название». Всё лишнее (дата, ранг,
    слова «Дуга»/«Weapon», мусор OCR) убирается; повторный вызов результат не меняет.
    Если названия нет — возвращает пустую строку (в форме подставится «Дуга»)."""
    name = strip_labels(clean_name(text), ("rank", "arc", "char", "item"))
    name = clean_name(_trim_edge_junk(name))
    snap = snap_known_phrase(name)           # НОВОЕ: «Обнажённый клинок» + мусор -> эталон
    if snap and snap[1] == "arc":
        name = snap[0]
    if (name.lower() in ("дуга", "дуги", "arc", "arcs", "weapon")  # одно слово-тип без названия
            or re.fullmatch(r"[x×х]?\s*\d+", name, re.I)):          # остался только «×1» / число
        name = ""
    return f"{DUGA_PREFIX}{name}" if name else ""



# НОВОЕ: слово-тип в начале названия предмета («Планер Ветер», «Костюм - Алый») — это тип,
# а не часть названия: он показывается в колонке «Тип», поэтому из названия убирается.
_ITEM_PREFIX_RE = re.compile(
    r"^(?i:детали\s+модификации\W*окраска|окраска|планер|костюм|скин(?:\s+на\s+авто)?|"
    r"glider|outfit|skin)(?!\w)[\s:.\-–—]*")



def strip_item_prefix(key, name: str) -> str:
    """Название предмета (костюм, планер, окраска, скин) без слова-типа в начале.
    Если после снятия ничего не остаётся — возвращается пустая строка (подставится
    название типа по умолчанию)."""
    if key not in ("outfit", "glider", "paint", "car_skin"):
        return name
    return clean_name(_ITEM_PREFIX_RE.sub("", name or "", count=1))



def format_glider_name(text: str) -> str:
    """НОВОЕ: приводит название планера к виду «Планер - Название». Слово «Планер», ранг и
    мусор OCR убираются, опечатки исправляются по справочнику GLIDER_NAMES; повторный вызов
    результат не меняет. Названия нет — пустая строка (подставится «Планер»)."""
    name = strip_item_prefix("glider", strip_labels(clean_name(text), ("rank", "item")))
    name = clean_name(_trim_edge_junk(name))
    snap = snap_known_phrase(name, keys=("glider",))
    if snap:
        name = snap[0]
    if name.lower() in ("планер", "glider") or re.fullmatch(r"[x×х]?\s*\d+", name, re.I):
        name = ""
    return f"{GLIDER_PREFIX}{name}" if name else ""



# ИСПРАВЛЕНО (костюмы): слово «Костюм» в НАЧАЛЕ строки (в т.ч. с ошибками OCR: «Kocmom…»)
_OUTFIT_LEAD_RE = re.compile(r"^(?:[кk][оo0][сc][тtm][a-zа-яё0-9|]{0,3}[мm]|outfit)(?![a-zа-яё])", re.I)



def format_outfit_name(text: str) -> str:
    """ИСПРАВЛЕНО (костюмы): приводит название костюма к виду «Костюм - Название». Слово
    «Костюм», ранг и мусор OCR убираются, опечатки исправляются по справочнику OUTFIT_NAMES;
    повторный вызов результат не меняет. Названия нет — пустая строка (подставится «Костюм»)."""
    forced = forced_name_rule(strip_leading_junk(text or ""))   # жёсткое правило искажений OCR
    if forced and forced["category"] == "outfit":
        return forced["label"]
    name = strip_item_prefix("outfit", strip_labels(clean_name(text), ("rank", "item")))
    name = clean_name(_trim_edge_junk(name))
    form = _phrase_form(name) if name else ""
    for known in OUTFIT_NAMES:                      # опечатки по справочнику костюмов
        target = _phrase_form(known)
        if form and (form == target or (abs(len(form) - len(target)) <= 3 and difflib.SequenceMatcher(
                None, form, target).ratio() >= PHRASE_MATCH_CUTOFF)):
            name = known
            break
    if name.lower() in ("костюм", "outfit") or re.fullmatch(r"[x×х]?\s*\d+", name, re.I):
        name = ""
    return f"{OUTFIT_PREFIX}{name}" if name else ""



def finalize_loot_name(key, raw_name: str) -> str:
    """НОВОЕ: итоговое название для формы «Ручная» при переносе из скриншота:
    персонаж — чистое имя; дуга — «Дуга - Название»; у кубиков и фрагментов названия
    нет; у остальных предметов — очищенный текст без ранга."""
    info = LOOT_TYPES.get(key)
    if info is None:
        return clean_name(raw_name)
    if info.get("hide_name"):
        return ""
    if key == "arc":
        return format_duga_name(raw_name)
    if key == "character":
        return clean_character_name(raw_name)
    if key == "glider":
        return format_glider_name(raw_name)           # «Планер - Название»
    if key == "outfit":
        return format_outfit_name(raw_name)           # «Костюм - Название»
    return strip_item_prefix(key, strip_labels(clean_name(raw_name), ("rank", "item")))



def _find_timestamp(text: str):
    """Первая дата в тексте в формате DATE_FMT или None."""
    m = find_valid_date_match(text)
    if m:
        try:
            return _normalize_date(m.group())
        except ValueError:
            pass
    return None



def _only(values):
    """Единственное различное значение из списка (иначе None)."""
    uniq = set(v for v in values if v is not None)
    return next(iter(uniq)) if len(uniq) == 1 else None



# ----------------------------------------------------------------------------
# НОВОЕ: сопоставление распознанного текста с составом персонажей (ROSTER_*)
# ----------------------------------------------------------------------------
# Перед сравнением обе стороны «сворачиваются» в одну форму: кириллические буквы,
# похожие на латинские, заменяются латиницей (поэтому «ЕХЕ» = «EXE», «Xaoc» = «Хаос»),
# а типичные путаницы OCR сводятся к одной букве: ё/э -> е, й -> и, ъ -> ь, щ -> ш, 0 -> о.
OCR_FOLD = str.maketrans({
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p",
    "с": "c", "т": "t", "у": "y", "х": "x",
    "ё": "e", "э": "e", "й": "и", "ъ": "ь", "щ": "ш", "0": "o",
})



ROSTER_MATCH_CUTOFF = 0.75   # минимальное сходство (difflib) для «прилипания» к имени



ROSTER_AMBIGUITY_GAP = 0.10  # если два имени почти одинаково похожи — не угадываем



ROSTER_MIN_FUZZY_LEN = 4     # короче 4 букв — только точное совпадение (после сворачивания)



def fold_name(text) -> str:
    """Форма имени для нечёткого сравнения (регистр, ё/е, похожие буквы)."""
    return str(text or "").lower().translate(OCR_FOLD)



# {свёрнутое имя: (имя, ранг 5/4)} — строится из ROSTER_KNOWN один раз при запуске
ROSTER_FOLDED = {fold_name(v[0]): (v[0], v[1]) for v in ROSTER_KNOWN.values()}



# ----------------------------------------------------------------------------
# НОВОЕ: эталонные названия дуг и предметов (нечёткий поиск в строке OCR)
# ----------------------------------------------------------------------------
# {название: ключ типа}. Ключ: «arc» — дуга; «solid» / «trick» — кубик (количество 1/5
# определяется отдельно, см. _cube_qty); «lost_fragment» / «warp_fragment» — фрагменты.
# Список МОЖНО ДОПОЛНЯТЬ: добавьте строку «"Название дуги": "arc"» — и OCR будет исправлять
# опечатки именно в этом названии и всегда считать его дугой.
KNOWN_PHRASES = {
    "Обнаженный клинок": "arc",
    # OCR-ФИКС 3: «Дуга - Забытое» (часто выпадает как «Подарок за очки»; OCR читает
    # «Дуга» как «Муга»). Эталон исправляет опечатки и всегда делает строку ДУГОЙ.
    "Забытое": "arc",
    # «дуга Чиетое небо» -> «Дуга - Чистое небо» (опечатки исправляет snap_known_phrase)
    "Чистое небо": "arc",
    "Твердый кубик": "solid",
    "Шулерский кубик": "trick",
    "Потерянный фрагмент": "lost_fragment",
    "Фрагмент искривления": "warp_fragment",
}



# НОВОЕ: мастер-справочники (дуги A ранга и планеры) — те же нечёткие эталоны, что и выше.
# setdefault: уже заданные вручную эталоны («Забытое», «Чистое небо», «Обнаженный клинок»)
# остаются как есть.
for _n in ARC_S_NAMES + ARC_A_NAMES + ARC_B_NAMES:
    KNOWN_PHRASES.setdefault(_n, "arc")



for _n in GLIDER_NAMES:
    KNOWN_PHRASES.setdefault(_n, "glider")



PHRASE_MATCH_CUTOFF = 0.78   # минимальное сходство (difflib) для «прилипания» к эталону



PHRASE_AMBIGUITY_GAP = 0.08  # два эталона почти одинаково похожи — не угадываем



def _phrase_form(text: str) -> str:
    """Форма для сравнения: свёрнутые буквы (fold_name) без пробелов — OCR часто теряет или
    добавляет пробелы («Твердыйкубик», «Потеряный фраг мент»)."""
    return re.sub(r"[\W_]+", "", fold_name(text))



_PHRASE_FOLDED = {_phrase_form(p): (p, key, len(p.split())) for p, key in KNOWN_PHRASES.items()}



# OCR-ФИКС: ключи KNOWN_PHRASES, которые являются ПРЕДМЕТАМИ (не дугами), и более мягкие
# пороги для строк с префиксом «Предмет» (PHRASE_ITEM_CUTOFF) и для «страховки» строк, у
# которых есть дата и количество, но название не распозналось (PHRASE_RECOVER_CUTOFF).
ITEM_PHRASE_KEYS = ("solid", "trick", "lost_fragment", "warp_fragment", "glider")



PHRASE_ITEM_CUTOFF = 0.62



PHRASE_RECOVER_CUTOFF = 0.55



def snap_known_phrase(text: str, cutoff: float = PHRASE_MATCH_CUTOFF, keys=None):
    """Ищет в строке эталонное название из KNOWN_PHRASES, исправляя опечатки OCR.
    Возвращает (эталонное название, ключ типа, сходство) или None.

    Сравниваются «окна» из соседних слов (длиной от n-1 до n+1 слов, где n — число слов в
    эталоне), поэтому лишние слова и мусор вокруг названия («l Твердый кубнк ×1 ¦»)
    отбрасываются, а название берётся чистым. Неоднозначные совпадения не засчитываются.
    keys — необязательный список ключей эталонов, среди которых искать (например,
    ITEM_PHRASE_KEYS — только предметы, без дуг)."""
    tokens = re.findall(r"[^\W_]+", text or "")
    if not tokens:
        return None
    best = {}   # эталон -> (сходство, ключ)
    for folded, (phrase, key, n) in _PHRASE_FOLDED.items():
        if keys is not None and key not in keys:
            continue
        for size in range(max(1, n - 1), n + 2):
            for i in range(0, len(tokens) - size + 1):
                window = _phrase_form(" ".join(tokens[i:i + size]))
                if abs(len(window) - len(folded)) > max(3, len(folded) // 4):
                    continue
                if len(folded) < MASTER_MIN_FUZZY_LEN and (
                        window != folded or folded != _phrase_form(split_garbled_type(text)[1])):
                    continue     # ИСПРАВЛЕНО: короткий эталон («Мы.») — только если это ВСЁ название
                score = 1.0 if window == folded else difflib.SequenceMatcher(
                    None, window, folded).ratio()
                if score >= cutoff and score > best.get(phrase, (0.0, None))[0]:
                    best[phrase] = (score, key)
    if not best:
        return None
    ranked = sorted(best.items(), key=lambda kv: -kv[1][0])
    if len(ranked) > 1 and ranked[0][1][0] - ranked[1][1][0] < PHRASE_AMBIGUITY_GAP:
        return None
    phrase, (score, key) = ranked[0]
    return phrase, key, score



def _roster_variants(text: str) -> list:
    """Что сравнивать с составом: каждое слово строки и склейки соседних слов
    («Блэк бёрд» -> «Блэкбёрд»). Числа, слова-типы и обрывки короче 3 букв пропускаются."""
    tokens = [t for t in re.findall(r"[^\W_]+", text or "")
              if not t.isdigit() and t.lower() not in KEYWORD_SET]
    variants = tokens + [a + b for a, b in zip(tokens, tokens[1:])]
    return [v for v in dict.fromkeys(variants) if len(v) >= 3]



def match_roster_name(text: str, cutoff: float = ROSTER_MATCH_CUTOFF):
    """Ищет в строке имя из состава персонажей (ROSTER_*), исправляя опечатки OCR.
    Возвращает (точное имя, ранг 5/4, сходство) или None. Осторожность против ошибок:
      * сходство ниже cutoff — не засчитывается;
      * у слов короче ROSTER_MIN_FUZZY_LEN допустимо только точное совпадение;
      * если подходят два разных имени с разницей меньше ROSTER_AMBIGUITY_GAP —
        результат неоднозначен, имя не меняется (пользователь выберет сам)."""
    best = {}  # имя -> (лучшее сходство, ранг)
    for variant in _roster_variants(text):
        folded = fold_name(variant)
        for roster_folded, (name, rank) in ROSTER_FOLDED.items():
            if abs(len(folded) - len(roster_folded)) > 2:
                continue
            if folded == roster_folded:
                score = 1.0
            elif min(len(folded), len(roster_folded)) < ROSTER_MIN_FUZZY_LEN:
                continue
            else:
                score = difflib.SequenceMatcher(None, folded, roster_folded).ratio()
            if score >= cutoff and score > best.get(name, (0.0, 0))[0]:
                best[name] = (score, rank)
    if not best:
        return None
    ranked = sorted(best.items(), key=lambda kv: -kv[1][0])
    if len(ranked) > 1 and ranked[0][1][0] - ranked[1][1][0] < ROSTER_AMBIGUITY_GAP:
        return None
    name, (score, rank) = ranked[0]
    return name, rank, score



def parse_ocr_result(raw_text: str, known: dict = None, context: str = None,
                     color_rank: int = None, guess_wish: bool = True,
                     bonus: bool = False, default_loot: str = "character",
                     dice_icon: bool = False) -> dict:
    """Разбирает одну распознанную строку на название, ранг/тип и время.

    known      — {имя в нижнем регистре: (имя, ранг, баннер)} для исправления опечаток
                 OCR и определения типа (персонаж / дуга) по истории;
    context    — полный текст скриншота: из него берётся значение, которого нет в самой
                 строке, но только если оно на скриншоте единственное;
    color_rank — ранг (5/4/3), определённый по цвету рамки/фона (classify_rarity_color);
    guess_wish — определять ли тип «Персонаж» / «Дуга» для строк без типа предмета;
    bonus      — строка уже помечена как бонусная;
    default_loot — тип для строк без префикса и без известного имени: «character» или
                 «arc» (на баннере «Дуга» безымянные строки — это дуги);
    dice_icon  — в строке был значок кубика 🎲 (убран prepare_ocr_row); учитывается только
                 как запасной признак, когда в строке нет никакого названия.

    ИСПРАВЛЕНО (тип и название): тип определяется по ПРЕФИКСУ строки («Дуга - …»,
    «Персонаж: …») раньше, чем по словам внутри названия; повторяющиеся префиксы и лишние
    цифры между ними убираются («Дуга - 8 Дуга - Настоящая музыка» -> «Дуга - Настоящая
    музыка»). НОВОЕ (бонус): фраза «Подарок за очки» (и «Дополнительная добыча») помечает
    запись как бонусную — is_bonus=True, ранг A; сама фраза из названия вырезается.

    Ранг выбирается по приоритету (OCR-ФИКС): бонус («Подарок за очки» — всегда A) -> ЦВЕТ
    ТЕКСТА названия на скриншоте (жёлтый S / фиолетовый A / серый, белый, тёмный B) ->
    ранг, написанный в тексте строки -> фиксированный у вида предмета -> известное имя из
    истории -> состав персонажей -> единственный ранг на скриншоте -> B по умолчанию.
    Цвет строго определяет колонку «Ранг» и цвет строки (кроме кешбэка: у него ранг жёсткий).
    Возвращает {"name", "rarity_type", "rarity", "rarity_src", "loot", "qty",
                "timestamp", "has_time"}:
      name        — ОЧИЩЕННОЕ название (персонаж — чистое имя, дуга — «Дуга - Название»);
      rarity_type — буква «S/A/B» или название типа («Костюм», «Кешбэк (Обычный)»…);
      rarity      — число 5/4/3 (S/A/B);
      rarity_src  — чем определён ранг («текст», «цвет», «история»…);
      loot        — ключ LOOT_TYPES («character», «arc», «outfit»…) или None;
      qty         — «30»/«50» для потерянного фрагмента, иначе None;
      timestamp   — QDateTime найденного времени (если не найдено — текущее системное);
      has_time    — найдено ли время в тексте (False — форму лучше не трогать);
      is_bonus    — бонусная добыча («Подарок за очки»): не расходует гарант;
      type_text   — текст колонки «Тип»: «Дуга», «Персонаж», «Планер», «Бонус (10 круток) - Дуга»…
    """
    known = known or {}
    raw_text = normalize_iroy_text(raw_text)[0]       # OCR-ФИКС 5: чистое «Персонаж: Ирой»
    raw_text = normalize_zanku_text(raw_text)[0]      # OCR-ФИКС 7: чистое «Персонаж: Занку»
    # НОВОЕ: бонусная добыча — признак снимается ДО разбора, чтобы фраза не попала в название
    is_bonus = bonus or bool(BONUS_MARK_RE.search(raw_text))
    if is_bonus:
        raw_text = BONUS_MARK_RE.sub(" ", raw_text)
        # OCR-ФИКС 3: «Муга Забытое» -> «Дуга - Забытое» (словарь BONUS_ITEM_CORRECTIONS)
        raw_text = re.sub(r"\s+", " ", fix_bonus_item_text(raw_text)).strip()
    # подписи вроде «Дополнительная добыча» / «(бонус 10 круток)» убираем, но бонусом не считаем
    raw_text = re.sub(r"\s+", " ", BONUS_NOISE_RE.sub(" ", raw_text)).strip()
    name = clean_name(raw_text)
    # НОВОЕ: эталонное название («Обнаженный клинок», «Твердый кубик»…) вытесняет искажённый
    # текст: мусор OCR вокруг и опечатки исчезают, остаётся чистое название
    snap = snap_known_phrase(strip_labels(name))
    if snap:
        name = snap[0]
    low = name.lower()
    # ИЗМЕНЕНО: сравнение с историей идёт без префиксов («Дуга - », ранг), чтобы
    # «S Хаотика» и «Дуга Клинок» находили «Хаотика» и «Дуга - Клинок»
    base = strip_labels(name).lower()
    index = {strip_labels(k, ("arc",)).lower(): k for k in known}
    hit = difflib.get_close_matches(base, list(index), n=1, cutoff=0.75) if base else []
    hit_key = index[hit[0]] if hit else None
    # ИСПРАВЛЕНО: серая строка (ранг B по цвету текста) не может быть персонажем A/S — они
    # всегда фиолетовые / золотые. Иначе короткая дуга («Мы.») «прилипала» к похожему
    # персонажу из истории (например, «Минт»).
    if (hit_key and color_rank == 3 and known[hit_key][1] in (4, 5)
            and leading_type(raw_text) != "character"):
        hit_key = None
    if hit_key:
        name = known[hit_key][0]
    elif low in KEYWORD_SET:  # в строке только слово-тип, не название
        name = ""

    loot = _loot_from_text(raw_text, dice=dice_icon)
    # ИСПРАВЛЕНО: префикс «Дуга - …» / «Персонаж: …» определяет тип сам и имеет приоритет
    lead = leading_type(raw_text)
    # OCR-ФИКС 5: ключевое слово предмета / ресурса («кубик», «фрагмент», «passer» …) — строка
    # НИКОГДА не персонаж, даже если OCR-мусор похож на имя (например, на «Занку»)
    res_hard = is_resource_text(raw_text) and lead != "arc"
    if lead in ("arc", "character") and not (res_hard and lead == "character"):
        loot = lead
    # ИСПРАВЛЕНО (костюмы): строка, начинающаяся со слова «Костюм» (в т.ч. «Kocmom…»), — ВСЕГДА
    # костюм (тип «Костюм», ранг S), а не персонаж, дуга или планер; то же — эталонное название
    # костюма из справочника OUTFIT_NAMES, даже если префикса в строке нет
    if lead not in ("arc", "character") and (
            _OUTFIT_LEAD_RE.match(strip_leading_junk(clean_name(raw_text)))
            or f"{OUTFIT_PREFIX}{strip_labels(name, ('rank', 'item'))}".lower() in OUTFIT_KNOWN):
        loot = "outfit"
    # НОВОЕ: «Предмет - …» — это предмет. Если вид предмета не распознан, строка НЕ должна
    # становиться персонажем: ниже она пропускается (loot=None)
    item_line = lead == "item" and loot not in ("arc", "character")
    if res_hard and loot in (None, "character"):
        low_r = raw_text.lower().replace("ё", "е")
        if _CUBE_WORD_RE.search(low_r):
            loot = ("trick" if re.search(r"шулер|trick", low_r) else "solid") + _cube_qty(low_r)
        elif (FRAGMENT_KEYWORD_RE.search(raw_text) or _fragment_like_word(raw_text)
              or fragment_stem_hint(raw_text) or _WARP_WORD_RE.search(low_r)):
            loot = "warp_fragment" if _WARP_WORD_RE.search(low_r) else "lost_fragment"
        else:
            loot, item_line = None, True              # предмет с неизвестным видом — не персонаж
    # OCR-ФИКС 3: строгий резерв «Потерянный фрагмент»: испорченная OCR строка с ключевым
    # словом фрагмента или количеством 30 / 50 — это материал, а не персонаж и не дуга
    if loot is None and lead is None and not is_bonus:
        loot = strict_fragment_key(raw_text, _qty_from_raw(raw_text), known)
    stamp = _find_timestamp(raw_text)
    ctx_rank = None
    if context is not None:
        lines = context.splitlines()
        loot = loot or _only(_loot_from_text(l) for l in lines)
        ctx_rank = _only(_rarity_from_text(l) for l in lines)
        # ИЗМЕНЕНО: finditer вместо findall — у DATE_RE теперь именованные группы
        stamp = stamp or _only(_find_timestamp(m.group()) for m in DATE_RE.finditer(context))
    if loot in ("cb_regular", "cb_premium") and re.fullmatch(
            r"(?:(?:кешб\w*|кэшб\w*|cashback|обычн\w*|премиум\w*|премиал\w*|regular|premium)\s*)+",
            name.lower()):
        name = ""  # в строке только описание кешбэка, а не название
    info = LOOT_TYPES.get(loot)
    if info and info.get("hide_name"):  # у кубиков и фрагментов названия нет
        name = ""

    # НОВОЕ: привязка к составу персонажей. Только для строк-персонажей: дуги (слово
    # «дуга»/«weapon») и предметы («Костюм …») пропускаются. Состав важнее истории:
    # опечатка, когда-то сохранённая в истории, не должна «прилипать» повторно.
    roster_hit = None
    if (loot in (None, "character") and not item_line and not snap
            and not ARC_WORD_RE.search(raw_text)):
        roster_hit = match_roster_name(strip_labels(clean_name(raw_text)))
        if roster_hit and color_rank == 3 and lead != "character" and roster_hit[2] < 1.0:
            roster_hit = None     # серая строка не бывает персонажем A/S: нечёткое совпадение не считаем
        if roster_hit:
            name, hit_key = roster_hit[0], None

    # НОВОЕ: строка без типа предмета — это персонаж или дуга. Дугой считаем строку
    # со словом «дуга»/«weapon» либо название, которое в истории лежит на баннере «Дуга».
    if loot is None and guess_wish and name and not item_line:
        is_arc = bool(ARC_WORD_RE.search(raw_text)) or (
            hit_key is not None and known[hit_key][2:3] == (ARC_BANNER,)) or (
            color_rank == 3 and not roster_hit and hit_key is None)   # серый текст — дуга, не персонаж
        if is_arc:
            loot = "arc"
        elif roster_hit or hit_key is not None:   # имя персонажа из состава / истории
            loot = "character"
        elif is_bonus:                            # OCR-ФИКС 3: бонус «Подарок за очки» — дуга,
            loot = "arc"                          # но никогда не персонаж
        else:                                     # иначе — по баннеру, выбранному в списке
            loot = default_loot if default_loot in ("arc", "character") else "character"
        info = LOOT_TYPES[loot]
    # НОВОЕ: очистка названия под определённый тип
    if loot == "arc":
        name = format_duga_name(name)
    elif loot == "character":
        name = clean_character_name(name)
    elif loot == "glider":
        name = format_glider_name(name)          # «Планер - Предвестник»
    elif loot == "outfit":
        name = format_outfit_name(name)          # «Костюм - Бесценная орхидея»
    elif loot and name:
        name = strip_item_prefix(loot, strip_labels(name, ("rank", "item")))
    if item_line and loot is None:
        name = ""                                # неизвестный предмет: не крутка
    if loot in ("arc", "character") and not name:  # после очистки ничего не осталось
        loot, info = None, None

    qty = None
    if loot == "lost_fragment":  # количество потерянных фрагментов: строго 30 или 50
        qty = fragment_qty(_qty_from_raw(raw_text), raw_text)      # OCR-ФИКС 3
    elif loot == "warp_fragment":
        qty = warp_qty(_qty_from_raw(raw_text), raw_text)

    fixed = loot_rarity(info) if info and info["mode"] != "wish" else None
    # бонусная добыча по правилам программы — всегда ранг A (как в форме «Ручная»)
    bonus_rank = 4 if is_bonus and info and info["mode"] == "wish" else None
    # OCR-ФИКС: цвет текста на скриншоте — главный источник ранга (и у круток, и у предметов).
    # Исключения: бонусная добыча (всегда A по правилам игры) и кешбэк (жёсткий ранг).
    color_ok = color_rank in (3, 4, 5) and not (info and info["mode"] == "cashback")
    # НОВОЕ: дуга из справочника A ранга. Цвет может только повысить ранг: «серый» результат
    # цветового анализа (3) у известной дуги считается неопределённым и справочник важнее.
    dict_rank = ARC_KNOWN[name.lower()][1] if loot == "arc" and name.lower() in ARC_KNOWN else None
    if dict_rank and color_rank == 3:
        color_ok = False
    candidates = ((bonus_rank, "бонусная добыча"),
                  (color_rank if color_ok else None, "цвет"),
                  (_rarity_from_text(raw_text), "текст"),
                  (dict_rank, "справочник дуг"),
                  (fixed, "тип предмета"),
                  (known[hit_key][1] if hit_key else None, "история"),
                  (roster_hit[1] if roster_hit else None, "состав персонажей"),
                  (ctx_rank, "скриншот"), (3, "по умолчанию"))
    rarity, rarity_src = next((r, src) for r, src in candidates if r)
    # НОВОЕ: текст колонки «Тип» — по распознанному типу (у предметов — название вида)
    type_text = ""
    if info:
        type_text = (REWARD_KINDS[info["kind"]] if info["mode"] == "reward"
                     and info.get("kind") in REWARD_KINDS else info["label"])
        if is_bonus and info["mode"] != "cashback":
            type_text = f"{BONUS_TYPE_PREFIX} - {type_text}"       # «Бонус (10 круток) - Дуга»
    return {
        # бонус у предметов тоже запоминается (в базе они получают флаг «вне гаранта»)
        "is_bonus": bool(is_bonus and info and info["mode"] != "cashback"),
        "type_text": type_text,
        "name": name,
        # OCR-ФИКС 3: итоговое название записи: «Потерянный фрагмент (30 шт)», «Дуга - Забытое»
        "display_name": (default_reward_name(info["kind"], qty or info.get("detail", ""))
                         if info and info["mode"] == "reward" and not name else name),
        "rarity_type": info["label"] if info and info["mode"] != "wish" else rank_letter(rarity),
        "rarity": rarity,
        "rarity_src": rarity_src,
        "loot": loot,
        "item_label": info["label"] if info and info["mode"] == "reward" else "",  # OCR-ФИКС
        # OCR-ФИКС 2: общий тип записи: «Предмет» / «Дуга» / «Персонаж» (кешбэк — «Кешбэк»)
        "item_type": ("Предмет" if info and info["mode"] == "reward" else
                      "Кешбэк" if info and info["mode"] == "cashback" else
                      info["label"] if info else ""),
        "qty": qty,
        "timestamp": (QDateTime.fromString(stamp, QT_DATE_FMT) if stamp
                      else QDateTime.currentDateTime()),
        "has_time": bool(stamp),
    }



# ---------------------------------------------------------------------------
# НОВОЕ: СЛОВАРИ ИСПРАВЛЕНИЙ OCR (фрагменты, персонажи) — единое место для дополнений
# ---------------------------------------------------------------------------
# Склеенные и искажённые написания слов «Потерянный» / «Фрагмент»: «подерянныФравмени»,
# «олерянны Фрапмента», «Фрапмента», «Фравмени» и т. п. Ищутся КАК ПОДСТРОКА (пробелы и
# регистр не важны, допускается одна-две опечатки), поэтому слитное написание тоже находится.
FRAGMENT_STEMS = ("фрагмент", "фрагмен", "фрапмент", "фравмен", "потерян", "подерян",
                  "олерянн", "толерян")



FRAGMENT_STEM_CUTOFF = 0.74



# Мусор OCR, который на самом деле — имя персонажа. Ключ — точное имя из состава, значение —
# известные искажения (регистр и пробелы не важны). Например «Mepconax Sarap» — это
# «Персонаж Эдгар», прочитанный с латинскими «двойниками» букв. ДОПОЛНЯЙТЕ по мере появления.
CHARACTER_OCR_ALIASES = {
    # ИЗМЕНЕНО: «Плане ладшии младшего босса» / «младшего босса» — это искажённый планер
    # «Младший босс младшего босса» (см. FORCED_NAME_RULES), а не Эдгар: из алиасов убраны.
    "Эдгар": ("Mepconax Sarap", "Sarap"),
    # ИСПРАВЛЕНО (персонажи): «Персонаж Занку» читается как «NepconarkKgrsanky»
    "Занку": ("NepconarkKgrsanky", "Nepconark Kgrsanky", "Kgrsanky", "Zanky", "Sanky"),
    # «Ирой» — искажения со слитной подписью «Персонаж» (Nepconark / Mepconax + имя)
    "Ирой": ("NepconarkIpoii", "NepconarkHpou", "Mepconax Hpou", "Nepconark Ipoii"),
}



CHARACTER_ALIAS_CUTOFF = 0.84    # строгий порог: короткие алиасы почти не допускают опечаток



CHARACTER_LABEL_CUTOFF = 0.60    # сходство слова с «Персонаж» (искажённая подпись типа)



CHARACTER_LABEL_WORD = "Персонаж"



def _letters_form(text: str) -> str:
    """Только буквы в «свёрнутом» виде (fold_name): без пробелов, цифр и знаков."""
    return re.sub(r"[\W\d_]+", "", fold_name(text))



def _fuzzy_contains(hay: str, needle: str, cutoff: float) -> bool:
    """needle встречается в hay точно или с опечатками (скользящее окно длиной n-1…n+1)."""
    if not hay or not needle:
        return False
    if needle in hay:
        return True
    n = len(needle)
    for size in sorted({max(3, n - 1), n, n + 1}):
        for i in range(0, len(hay) - size + 1):
            if difflib.SequenceMatcher(None, hay[i:i + size], needle).ratio() >= cutoff:
                return True
    return False



def fragment_stem_hint(text: str) -> bool:
    """В тексте есть искажённое «Потерянный» / «Фрагмент» (в том числе слитно)."""
    hay = _letters_form(text)
    return any(_fuzzy_contains(hay, _letters_form(s), FRAGMENT_STEM_CUTOFF)
               for s in FRAGMENT_STEMS)



# ---------------------------------------------------------------------------
# НОВОЕ: МАСТЕР-СПРАВОЧНИК названий и поиск эталонного названия ВНУТРИ строки OCR
# ---------------------------------------------------------------------------
# Единый словарь канонических названий: персонажи S/A (ROSTER_*), дуги S/A (ARC_*_NAMES),
# планеры (GLIDER_NAMES), костюмы (OUTFIT_NAMES), предметы («Потерянный фрагмент»,
# «Твердый кубик» …). Дополнительные названия берутся из двух мест:
#   * файл master_names.json (рядом с main.py или в assets/) — см. формат ниже;
#   * база данных: названия костюмов / планеров / окрасок / скинов из таблицы rewards
#     (названия персонажей и дуг из истории НЕ берутся: опечатка, когда-то сохранённая
#     в истории, не должна «прилипать» повторно).
# Формат master_names.json (все ключи необязательны; элемент — строка или {"name", "rank"}):
#   {"characters": [{"name": "Адлер", "rank": "A"}], "arcs": ["Забытое"], "gliders": [],
#    "outfits": [], "paints": [], "skins": [], "items": []}
# Если в строке OCR найдено эталонное название (точно или с опечатками, среди мусора,
# номеров и лишних символов), ВСЯ строка заменяется чистым каноническим названием с
# префиксом типа («Персонаж: Адлер», «Дуга - Забытое», «Планер - Предвестник»,
# «Костюм - …», «Предмет - Потерянный фрагмент»). Тип, ранг и количество затем
# определяются обычным разбором (parse_ocr_result) уже по чистому названию.
# Конвейер один на все три вкладки («Скриншот», «Скриншот оптом», «Скриншоты разом»):
# все они разбирают текст через ocr_extract_pulls_ex.
MASTER_JSON_NAME = "master_names.json"



MASTER_ITEM_KINDS = ("solid_cube", "trick_cube", "lost_fragment", "warp_fragment")



# Виды предметов из базы, чьи названия пополняют справочник: вид -> слово-префикс
MASTER_DB_KINDS = {"outfit": "Костюм", "glider": "Планер", "paint": "Окраска",
                   "car_skin": "Скин на авто"}



MASTER_JSON_KEYS = {"characters": "character", "arcs": "arc", "gliders": "glider",
                    "outfits": "outfit", "paints": "paint", "skins": "car_skin", "items": "item"}



MASTER_MIN_FUZZY_LEN = 4     # название короче 4 букв — только точное совпадение



MASTER_MIN_GLUED_LEN = 5     # слитный поиск («ПодарокзаочкиАдлер») — только для названий от 5 букв



# слова-подписи типов: помогают выбрать между одинаковыми названиями разных типов
MASTER_CATEGORY_WORDS = {"character": "персонаж", "arc": "дуга", "glider": "планер",
                         "outfit": "костюм", "paint": "окраска", "car_skin": "скин"}



_MASTER_STATE = {"json": [], "db": [], "index": None}



def _master_label(category: str, name: str) -> str:
    """Каноническая строка для разбора: префикс типа + чистое название."""
    if category == "character":
        return f"{CHARACTER_LABEL_WORD}: {name}"
    if category == "arc":
        return f"{DUGA_PREFIX}{name}"
    if category == "glider":
        return f"{GLIDER_PREFIX}{name}"
    if category == "item":
        return f"Предмет - {name}"
    return f"{MASTER_DB_KINDS[category]} - {name}"          # костюм / окраска / скин



def _master_rank(value):
    """Ранг из JSON («S», «A», «B», 5, 4, 3) -> 5 / 4 / 3 или None."""
    if isinstance(value, str):
        value = LETTER_RANKS.get(value.strip().upper().translate(CYR_TO_LAT), value)
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value in RARITIES else None



def _load_master_json() -> list:
    """Читает master_names.json (если есть). Любая ошибка файла игнорируется — программа
    работает по встроенным спискам."""
    roots = search_roots()
    for root in roots:
        for path in (root / MASTER_JSON_NAME, root / "assets" / MASTER_JSON_NAME):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            out = []
            for key, category in MASTER_JSON_KEYS.items():
                for item in data.get(key) or ():
                    name = item.get("name") if isinstance(item, dict) else item
                    rank = _master_rank(item.get("rank")) if isinstance(item, dict) else None
                    name = clean_name(str(name or ""))
                    if category == "arc":
                        name = strip_labels(name, ("arc",))
                    elif category in MASTER_DB_KINDS:
                        name = strip_item_prefix(category, name)
                    if len(name) >= 2:
                        out.append((category, name, rank))
            return out
    return []



def refresh_master_names(rewards=None) -> None:
    """Перечитывает дополнительные названия: master_names.json и названия костюмов /
    планеров / окрасок / скинов из базы (rewards). Вызывается при запуске и при каждом
    обновлении данных окна."""
    db, seen = [], set()
    for r in rewards or ():
        kind = r.get("kind")
        if kind not in MASTER_DB_KINDS:
            continue
        name = strip_item_prefix(kind, clean_name(r.get("name") or ""))
        if (len(name) < 3 or name.lower() == REWARD_KINDS.get(kind, "").lower()
                or (kind, name.lower()) in seen):
            continue
        seen.add((kind, name.lower()))
        db.append((kind, name, None))
    _MASTER_STATE.update({"json": _load_master_json(), "db": db, "index": None})
    _MASTER_CACHE.clear()



def master_index() -> list:
    """Список эталонов {category, name, label, form, ntok, rank_hint}; строится один раз и
    перестраивается после refresh_master_names."""
    if _MASTER_STATE["index"] is not None:
        return _MASTER_STATE["index"]
    index, seen = [], set()

    def add(category, name, rank_hint=None):
        form = _phrase_form(name)
        if not form or (category, form) in seen:
            return
        seen.add((category, form))
        index.append({"category": category, "name": name, "form": form,
                      "label": _master_label(category, name),
                      "ntok": len(name.split()), "rank_hint": rank_hint})

    for name, _rank, _banner in ROSTER_KNOWN.values():          # персонажи S и A
        add("character", name)
    for full, _rank, _banner in ARC_KNOWN.values():             # дуги S и A
        add("arc", full[len(DUGA_PREFIX):])
    for name in GLIDER_NAMES:
        add("glider", name)
    for phrase, key in KNOWN_PHRASES.items():                   # вручную добавленные эталоны
        if key in ("arc", "glider"):                            # («Забытое», «Чистое небо» …)
            add(key, phrase)
    for name in OUTFIT_NAMES:                                   # костюмы: тип «Костюм», ранг S
        add("outfit", name, OUTFIT_RANK)
    for kind in MASTER_ITEM_KINDS:                              # предметы и ресурсы
        add("item", REWARD_KINDS[kind])
    for category, name, rank in _MASTER_STATE["json"] + _MASTER_STATE["db"]:
        static_rank = None
        if category == "character" and name.lower() in ROSTER_KNOWN:
            static_rank = True
        elif category == "arc" and f"{DUGA_PREFIX}{name}".lower() in ARC_KNOWN:
            static_rank = True
        add(category, name, None if static_rank else rank)
    _MASTER_STATE["index"] = index
    return index



# ---------------------------------------------------------------------------
# НОВОЕ: ЖЁСТКИЕ ПРАВИЛА для названий, которые OCR искажает до неузнаваемости
# ---------------------------------------------------------------------------
# Каждое правило: эталон (category + name из мастер-справочника) и признаки в строке OCR:
#   strong    — [(слово, порог сходства)]: достаточно ОДНОГО похожего слова строки
#               (сравнение через fold_name: латинские «двойники» букв, ё/е, й/и не мешают;
#               слова склеиваются с соседними, поэтому «На стоящая» тоже находится);
#   strong_re — регулярные выражения: достаточно одного совпадения;
#   weak / weak_re — слабые признаки: срабатывают, только если совпали минимум ДВА из них;
#   rank      — если задан, ранг принудительный (цвет на скриншоте игнорируется).
# Правило срабатывает безусловно: строка целиком заменяется эталонным названием.
# ДОПОЛНЯЙТЕ по мере появления новых искажений.
FORCED_NAME_RULES = (
    {   # «Забетонированное» (искажение OCR) -> «Дуга - Забытое»; «Забытые» (другая дуга) не трогаем
        "category": "arc", "name": "Забытое",
        "strong_re": (r"(?i)(?<!\w)заб[еёe]тон\w*",),
    },
    {   # «Младний Gees», «иладнюго Geese», «Пленер - Младний…» -> планер A ранга
        "category": "glider", "name": "Младший босс младшего босса", "rank": 4,
        "strong": (("младший", 0.62), ("младшего", 0.62), ("босс", 0.74), ("босса", 0.74)),
        "strong_re": (r"(?i)(?<!\w)[мmи]\s?л[аa]\s?д[нhшщ]\w*", r"(?i)(?<!\w)и?л[аa]дш\w*",
                      r"(?i)(?<!\w)[бb6][оo0][сc]{2}[аa]?(?!\w)"),
        "weak_re": (r"(?i)(?<![a-z])g[e3]{1,2}s[e3]?s?(?![a-z])",
                    r"(?i)(?<!\w)(?:пл[еёe]н[еe]р\w*|plane\w*)"),
    },
    {   # «олори», «овори», «Хотори» (Tesseract теряет «Х» и путает «т» с «л» / «в») ->
        # персонаж Хотори (ивентовый S ранга). Только для строк-персонажей (без префикса
        # «Дуга» / «Предмет»): ранг принудительный — S, цвет на скриншоте не важен.
        "category": "character", "name": "Хотори", "rank": 5,
        "strong": (("хотори", 0.80),),
        "strong_re": (r"(?i)(?<!\w)[хx]?[оo0][тtлlвb][оo0][рp][иi](?!\w)",),
    },
    {
        "category": "glider", "name": "Предвестник", "rank": 4,
        "strong": (("предвестник", 0.66),),
        "strong_re": (r"(?i)(?<!\w)пр[еe]дв[еe]\w*", r"(?i)\w*[вb][еe]стн[иi][кk](?!\w)",
                      r"(?i)(?<!\w)predvestn\w*"),
    },
    {
        "category": "item", "name": "Фрагмент искривления", "rank": 5,
        "qty": ("30", "16", "4"), "qty_default": "30", "any_lead": True,
        "strong": (("фрагмент искривления", 0.72), ("искривления", 0.74)),
        "strong_re": (r"(?i)стран[аa]\s*сн[аa]", r"(?i)f[il1]?pas[ea]re?",
                      r"(?i)g?[pр]am[il1]c[ea]r", r"(?i)зетав\w*", r"(?i)\w*яхест\w*",
                      r"(?i)фрагмент\s*иск\w*"),
    },
    {
        "category": "item", "name": "Твердый кубик", "rank": 5,
        "qty": ("1", "5"), "qty_default": "1", "any_lead": True,
        "exclude_re": (r"(?i)шул\w*", r"(?i)trick", r"(?i)ш[уy]л[еe]р"),
        "strong": (("кубик", 0.75), ("твердый кубик", 0.74)),
        "strong_re": (r"(?i)re[a-z]{0,2}mn?ear", r"(?i)tesp[ea]p", r"(?i)care{1,2}r",
                      r"(?i)(?<![a-z])pass[ea]r", r"(?i)th?[ea]pa[ea]?[aе]?n", r"(?i)(?<!\w)кубик\w*"),
    },
    {   # «Онасная игpa», «Опаснаяигра», «Дуга - 0пасная игра» -> «Дуга - Опасная игра»
        "category": "arc", "name": "Опасная игра",
        "strong": (("опасная", 0.72), ("опасная игра", 0.75)),
        "weak": (("игра", 0.75),), "weak_re": (r"(?i)(?<!\w)[оo0][пn]?[аa]с\w{0,4}",),
    },
    {   # ИСПРАВЛЕНО: «Мы.» OCR читает как «Мини», «Мыни», «Миы», «MbI» — «Мини» ещё и похоже на
        # персонажа «Минт» (0.75), из-за чего дуга становилась персонажем. «Минт» не затрагивается.
        "category": "arc", "name": "Мы.", "need_lead": "arc",
        "strong_re": (r"(?i)(?<![a-zа-яё0-9])[мm](?:ы|b[l1I]|[иu]ни|[иu]ыи?|[иu]{2})\.?(?![a-zа-яё0-9])",),
    },
    {   # ИСПРАВЛЕНО: «Обнаженный клинок» — искажения слова «клинок» / «обнаженный»
        "category": "arc", "name": "Обнаженный клинок",
        # «Ненасытный клинок» — отдельная дуга S: слово «клинок» само по себе её не превращает
        "exclude_re": (r"(?i)расколот\w*", r"(?i)[аa]с[ыi]тн\w*"),
        "strong": (("обнаженный клинок", 0.72), ("обнаженный", 0.78)),
        "strong_re": (r"(?i)(?<![a-zа-яё])обн[аa]ж\w*", r"(?i)(?<![a-zа-яё])[кk][лnl][иu][нh][оo0][кk](?![a-zа-яё])"),
    },
    {   # «Hастоящая музыкa», «Настояшая муэыка» -> «Дуга - Настоящая музыка»
        "category": "arc", "name": "Настоящая музыка",
        "strong": (("настоящая", 0.72), ("музыка", 0.75), ("настоящая музыка", 0.75)),
    },
    {   # ИСПРАВЛЕНО (костюмы): «Костюм - Бесценная орхидея» Tesseract читает как
        # «Kocmomilbeectiennanlopxvines» (слитно, кириллица/латиница вперемешку) ->
        # ЖЁСТКО «Костюм - Бесценная орхидея», тип «Костюм», ранг S (цвет на скриншоте не важен).
        # Срабатывает на любой из признаков (проверяется и сама строка, и строка без пробелов):
        #   * «Kocmomil…» — искажённое слово «Костюм», слипшееся с названием;
        #   * искажённое «Бесценная» («beectiennan», «Becuennan», «Бесценная»);
        #   * ИЛИ вместе: искажённое «Костюм» + искажённое «орхидея» («opxvines», «opxuneA»).
        # Одно «орхидея» БЕЗ слова «Костюм» не срабатывает: это планер «Орхидеевый бриз».
        "category": "outfit", "name": "Бесценная орхидея", "rank": OUTFIT_RANK, "squash": True,
        "strong": (("бесценная орхидея", 0.70), ("бесценная", 0.70)),
        "strong_re": (
            # «Kocmomil» + буквы названия (костюм слитно с названием)
            r"(?i)[кk][оo0][сc][тtm][a-zа-яё0-9|]{0,3}[мm][il1|!]{1,2}[a-zа-яё]{3,}",
            # «бесценная» с ошибками OCR: b/б, ее/е, c/с, 0-4 любые буквы (ti/ц), nn/нн, a/а/я
            r"(?i)[бb6][eеё]{1,2}[cс][a-zа-яё]{0,4}[nнh]{1,2}[aаяr]",
        ),
        "weak_re": (
            r"(?i)[кk][оo0][сc][тtm][a-zа-яё0-9|]{0,3}[мm]",          # «Костюм» / «Kocmom»
            r"(?i)[оo0][pрr1l][xх×k][iиvuнn]",                         # «орхи…» / «opxv…»
        ),
    },
)



# ---------------------------------------------------------------------------
# ИСПРАВЛЕНО (персонажи): ЖЁСТКИЕ ПРАВИЛА для имён персонажей, которые OCR искажает до мусора
# ---------------------------------------------------------------------------
# Пример: «Персонаж Занку» -> «NepconarkKgrsanky»: слово «Персонаж» превращается в «Nepconark»
# (слитно с именем), а имя — в «Kgrsanky». Работают три уровня (от жёсткого к мягкому):
#   1) CHARACTER_FORCED_PATTERNS — вручную заданные регулярные выражения для имени (ДОПОЛНЯЙТЕ
#      по мере появления новых искажений: добавьте регулярку в кортеж нужного имени);
#   2) регулярные выражения, которые строятся АВТОМАТИЧЕСКИ для ВСЕХ персонажей состава
#      (ROSTER_*): каждая буква заменяется классом «двойников» кириллица / латиница;
#   3) словарь CHARACTER_OCR_ALIASES (резерв, нечёткое сравнение — см. _master_scan).
# Результат — «Персонаж: <имя>» и ранг состава (S / A) принудительно, цвет не важен.
CHAR_LABEL_GARBLE_RE = re.compile(
    r"(?i)^[\W_]*[nmиuhп][eеё3][pрr][cсs][oо0][nнh][aаa][жxkr]{1,2}[\W_]*")



CHARACTER_FORCED_PATTERNS = {
    # «Занку»: Kgrsanky, Zanky, 3анку, Sанку (з -> s/z/3, у -> y/u)
    "Занку": (r"(?i)[sз3z5][aа][nнh][kк][yуu]",
              r"(?i)(?<![a-zа-яё])[zз3][aа][nнh][kк]"),
    # «Ирой»: Ipou, Hpoii, Upoi, Ипой (и -> u/h/n/m, й -> ii/u/и)
    "Ирой": (r"(?i)(?<![a-zа-яё])[иuнhnm1l][pр][oо0][иiйuлn]{1,2}(?![a-zа-яё])",
             r"(?i)(?<![a-zа-яё])[иuнhnm1l][pр][oо0]\s?[иiйuлn]"),
}



# «двойники» букв: какие символы Tesseract подставляет вместо кириллической буквы
_CHAR_LOOKALIKE = {
    "а": "аa", "б": "бb6", "в": "вbv", "г": "гr", "д": "дdg", "е": "еёeэ", "ё": "ёеeэ",
    "ж": "жxk", "з": "зz3sэ", "и": "иuнnhi", "й": "йиiuл", "к": "кk", "л": "лl1", "м": "мm",
    "н": "нhn", "о": "оo0", "п": "пnh", "р": "рp", "с": "сc", "т": "тtm", "у": "уyu",
    "ф": "фf", "х": "хxk", "ц": "цu", "ч": "чn4", "ш": "шw", "щ": "щw", "ъ": "ъb", "ы": "ыb",
    "ь": "ьb", "э": "эe3", "ю": "юio", "я": "яr",
}



_CHAR_LOOKALIKE["ы"] = "ыbl1I"      # ИСПРАВЛЕНО: «ы» OCR читает как «bl» / «bI»



_CHAR_RE_CACHE = {}



def _char_lookalike_body(name: str, gap: bool) -> str:
    """Тело регулярного выражения «имя с двойниками букв»; gap — допускается лишняя буква между
    соседними буквами (OCR вставляет мусор в длинные имена)."""
    parts = []
    for ch in name.lower():
        chars = _CHAR_LOOKALIKE.get(ch, ch)
        parts.append("[" + re.escape("".join(dict.fromkeys(chars))) + "]")
    return ("[a-zа-яё]?" if gap else "").join(parts)



def _char_regexes(name: str):
    """(в границах слова, с начала строки, вся строка) — регулярные выражения имени."""
    cached = _CHAR_RE_CACHE.get(name)
    if cached is None:
        body = _char_lookalike_body(name, gap=len(name) >= 5)
        cached = _CHAR_RE_CACHE[name] = (
            re.compile(rf"(?i)(?<![a-zа-яё]){body}(?![a-zа-яё])"),
            re.compile(rf"(?i)^{body}"),
            re.compile(rf"(?i)^{_char_lookalike_body(name, gap=False)}$"))
    return cached



def garbled_character_name(text: str, lead=None):
    """ИСПРАВЛЕНО (персонажи): (имя из состава, жёсткое ли совпадение) или None. «Жёсткое» —
    сработало ручное правило CHARACTER_FORCED_PATTERNS или слитная искажённая подпись
    «Nepconark…» + имя; мягкое — автоматическая регулярка «двойников» для длинного имени
    (5+ букв). Дуги, планеры и предметы (явный префикс) не затрагиваются."""
    if lead in ("arc", "item") or not text:
        return None
    t = strip_leading_junk(text)
    label = CHAR_LABEL_GARBLE_RE.match(t)
    tail = clean_name(t[label.end():] if label else t)
    squashed = re.sub(r"\s+", "", tail)
    if not squashed:
        return None
    for name, patterns in CHARACTER_FORCED_PATTERNS.items():       # 1) ручные правила
        if any(re.search(p, h) for p in patterns for h in (tail, squashed)):
            return name, True
    labeled = bool(label) or lead == "character"
    for name, _rank, _banner in ROSTER_KNOWN.values():              # 2) автоматические
        bounded, prefix, whole = _char_regexes(name)
        if whole.match(squashed) and (labeled or len(name) >= 4):
            return name, labeled
        if labeled and prefix.match(squashed):                       # «NepconarkKgrsanky»
            return name, True
        if len(name) >= 5 and bounded.search(tail):
            return name, False
    return None



_RULE_RE_CACHE = {}



# Слова-«шум», которые никогда не бывают названием: подарок / очки / предмет / подписи бонуса
_MASTER_NOISE_RE = re.compile(
    r"(?<!\w)(?:п[оo0]д[аa][рp]\w{0,4}|за\s+очки|очки|пр[еe]дм[еe]т\w*)(?!\w)", re.I)



def _rule_word_hit(tokens: list, word: str, cutoff: float) -> bool:
    """Есть ли среди слов строки (и склеек соседних слов) слово, похожее на эталонное."""
    target = _phrase_form(word)
    variants = tokens + [a + b for a, b in zip(tokens, tokens[1:])]
    for v in variants:
        f = _phrase_form(v)
        if len(f) < 4 or abs(len(f) - len(target)) > max(2, len(target) // 3):
            continue
        if f == target or difflib.SequenceMatcher(None, f, target).ratio() >= cutoff:
            return True
    return False



def _rule_re_hit(pattern: str, text: str) -> bool:
    rx = _RULE_RE_CACHE.get(pattern)
    if rx is None:
        rx = _RULE_RE_CACHE[pattern] = re.compile(pattern)
    return bool(rx.search(text))



def forced_name_rule(text: str, lead=None):
    """Жёсткое правило: возвращает эталон-словарь master_index() для строки, в которой
    есть признаки искажённого названия из FORCED_NAME_RULES, иначе None."""
    tokens = re.findall(r"[^\W_]+", text or "")
    if not tokens:
        return None
    allowed = {"arc": ("arc",), "character": ("character",),
               "item": ("glider", "arc", "outfit", "item")}.get(lead)
    squashed = re.sub(r"\s+", "", text or "")      # для слитных искажений («Kocmomil beec…»)
    for rule in FORCED_NAME_RULES:
        if allowed is not None and rule["category"] not in allowed and not rule.get("any_lead"):
            continue
        if rule.get("need_lead") and lead != rule["need_lead"]:
            continue                      # правило только для строк с явным префиксом («Дуга - …»)
        if any(_rule_re_hit(rx, text) for rx in rule.get("exclude_re", ())):
            continue
        # правило с "squash": регулярные выражения проверяются и по строке без пробелов
        hay = (text, squashed) if rule.get("squash") else (text,)
        strong = (any(_rule_word_hit(tokens, w, c) for w, c in rule.get("strong", ()))
                  or any(_rule_re_hit(rx, h) for rx in rule.get("strong_re", ()) for h in hay))
        weak = (sum(1 for w, c in rule.get("weak", ()) if _rule_word_hit(tokens, w, c))
                + sum(1 for rx in rule.get("weak_re", ()) if any(_rule_re_hit(rx, h) for h in hay)))
        if strong or weak >= 2:
            for e in master_index():
                if e["category"] == rule["category"] and e["name"] == rule["name"]:
                    return dict(e, force_rank=rule.get("rank"), qty_options=rule.get("qty"),
                                qty_default=rule.get("qty_default"))
    return None



_MASTER_CACHE = {}



# ИСПРАВЛЕНО (баннер дуг): в этом баннере выпадают только дуги (и предметы: кубики, фрагменты).
# Персонажи, костюмы, планеры, окраски / детали модификации и скины на авто выпасть не могут,
# поэтому в режиме «только дуги» они исключаются из всех справочников и правил.
ARC_BANNER_BLOCKED_LOOT = ("character", "outfit", "glider", "paint", "car_skin")



ARC_BANNER_ALLOWED_CATEGORIES = ("arc", "item")



# префиксы типов, которых в баннере дуг быть не может: «Персонаж:», «Костюм -», «Планер -»,
# «Окраска», «Скин на авто», «Детали модификации -» (с типичными искажениями OCR)
_ARC_BLOCKED_PREFIX_RE = re.compile(
    r"^\W*(?:[пnm][еeё][рp][сc][оo0][нnh][аa][жxk]\w*|[кk][оo0][сc][тt][юуy][мm]\w*"
    r"|[пn][лl][аa][нh][еeё][рp]\w*|[оo0][кk][рp][аa][сc][кk]\w*|[сc][кk][иi][нh]\w*"
    r"|[дd][еeё][тt][аa][лl][иi]\s+[мm][оo0][дd]\w*|[мm][оo0][дd][иi][фf]\w*)"
    r"(?:\s+[нh][аa]\s+[аa][вb][тt][оo0])?[\s:.\-–—|]*", re.I | re.U)



def strip_arc_blocked_prefix(body: str) -> str:
    """Баннер дуг: убирает префикс запрещённого типа («Персонаж: Мы.» -> «Мы.»)."""
    t = _ARC_BLOCKED_PREFIX_RE.sub("", body or "", count=1).strip()
    return t or (body or "")



def master_match(body: str, arc_only: bool = False):
    """Ищет в строке OCR эталонное название из мастер-справочника (как подстроку, точно или
    с опечатками). Возвращает {"label", "name", "category", "score", "matched", "rank"} или
    None. label — чистое каноническое название с префиксом типа; matched — фрагмент строки,
    по которому найдено совпадение; score — сходство (1.0 — точное).

    Осторожность: сравниваются «окна» из соседних слов (мусор и номера вокруг отбрасываются),
    у названий короче MASTER_MIN_FUZZY_LEN допустимо только точное совпадение, при почти
    одинаковых кандидатах разных названий результат не засчитывается. Явный префикс строки
    («Дуга - …», «Персонаж: …», «Предмет - …») ограничивает типы кандидатов. Точное название
    важнее словаря искажений CHARACTER_OCR_ALIASES, а словарь — важнее нечёткого поиска."""
    key = (body, True) if arc_only else body
    cached = _MASTER_CACHE.get(key)
    if cached is not None:
        return dict(cached[0]) if cached[0] else None
    result = _master_match_uncached(body, arc_only)
    if arc_only and result and result.get("category") not in ARC_BANNER_ALLOWED_CATEGORIES:
        result = None                       # персонаж / костюм / планер / окраска в баннере дуг — нет
    if len(_MASTER_CACHE) > 4000:
        _MASTER_CACHE.clear()
    _MASTER_CACHE[key] = (dict(result) if result else None,)
    return dict(result) if result else None



def _master_match_uncached(body: str, arc_only: bool = False):
    """Тело master_match без кэша (см. описание выше). arc_only — баннер дуг: только дуги и
    предметы (кубики, фрагменты), без персонажей, костюмов, планеров и окрасок."""
    if arc_only:
        body = strip_arc_blocked_prefix(body)
    plain = clean_lookup_text(body or "") or strip_leading_junk(body or "")
    # OCR-ФИКС 5 (Ирой): «8 персонажеиИрой» / «персонажиИрой» -> строго «Персонаж: Ирой», ранг
    # состава принудительный (цвет не важен). Проверка идёт ДО словарей и нечёткого поиска.
    plain, iroy_hit = normalize_iroy_text(plain)
    if iroy_hit and not arc_only:
        entry = next((e for e in master_index()
                      if e["category"] == "character" and e["name"] == IROY_NAME), None)
        if entry:
            rank = ROSTER_KNOWN[IROY_NAME.lower()][1]
            return {"label": entry["label"], "name": IROY_NAME, "category": "character",
                    "score": 1.0, "matched": plain, "rank": rank, "force_rank": rank}
    plain, zanku_hit = normalize_zanku_text(plain)      # OCR-ФИКС 7: Занку (S)
    if zanku_hit and not arc_only:
        entry = next((e for e in master_index()
                      if e["category"] == "character" and e["name"] == ZANKU_NAME), None)
        if entry:
            rank = ROSTER_KNOWN[ZANKU_NAME.lower()][1]
            return {"label": entry["label"], "name": ZANKU_NAME, "category": "character",
                    "score": 1.0, "matched": plain, "rank": rank, "force_rank": rank}
    lead = leading_type(plain)             # тип по префиксу — до того, как префиксы будут сняты
    if arc_only and lead != "item":
        lead = "arc"                       # баннер дуг: строка без предметного префикса — дуга
    # OCR-ФИКС 5 (Занку): строка с ключевым словом предмета / ресурса ищется ТОЛЬКО среди
    # предметов (персонажи исключены: lead="item" не допускает категорию «character»)
    if lead != "arc" and is_resource_text(plain):
        lead = "item"
    elif arc_only and lead == "arc" and not plain:
        return None
    bonus_soft = bool(BONUS_MARK_RE.search(plain))   # «Подарок за очки»: только точные имена
    # НОВОЕ: перед сравнением из строки убираются «Подарок за очки», «Предмет», подписи бонуса
    # и ранг в начале — они не должны мешать нечёткому поиску названия
    stripped = BONUS_NOISE_RE.sub(" ", BONUS_MARK_RE.sub(" ", plain))
    stripped = strip_leading_junk(_MASTER_NOISE_RE.sub(" ", stripped))
    stripped = strip_leading_junk(strip_labels(re.sub(r"\s+", " ", stripped), ("rank", "item")))
    # жёсткие правила для искажённых названий (Опасная игра, Настоящая музыка, планер)
    forced = forced_name_rule(stripped, lead) or (
        forced_name_rule(plain, lead) if stripped != plain else None)
    if forced:
        return {"label": forced["label"], "name": forced["name"],
                "category": forced["category"], "score": 1.0, "matched": stripped or plain,
                "rank": forced.get("rank_hint"), "force_rank": forced.get("force_rank"),
                "qty_options": forced.get("qty_options"),
                "qty_default": forced.get("qty_default")}
    result = _master_scan(stripped, lead, arc_only)
    if result is None and stripped != plain:      # слитное «ПодарокзаочкиАдлер» съедено целиком
        result = _master_scan(plain, lead, arc_only)
    # ИСПРАВЛЕНО (персонажи): жёсткие правила имён («NepconarkKgrsanky» -> Занку). Жёсткое
    # совпадение важнее поиска по справочнику; мягкое — только если справочник ничего не нашёл
    # или нашёл персонажа (так дуга / планер не превращаются в персонажа)
    garbled = None if arc_only else (garbled_character_name(stripped, lead) or (
        garbled_character_name(plain, lead) if stripped != plain else None))
    if garbled and garbled[0].lower() in (stripped or plain).lower():
        garbled = None                      # имя прочитано точно — обычный разбор, ничего не форсируем
    if bonus_soft:
        garbled = None                      # OCR-ФИКС 5: в бонусной строке персонажа не «угадываем»
        if result and result["category"] == "character" and result["score"] < 1.0:
            result = None                   # нечёткое совпадение с персонажем — не засчитываем
    if garbled and (garbled[1] or result is None or result["category"] == "character"):
        entry = next((e for e in master_index()
                      if e["category"] == "character" and e["name"] == garbled[0]), None)
        if entry:
            rank = ROSTER_KNOWN[garbled[0].lower()][1]
            return {"label": entry["label"], "name": entry["name"], "category": "character",
                    "score": 1.0 if garbled[1] else 0.9, "matched": stripped or plain,
                    "rank": rank, "force_rank": rank}
    # ИСПРАВЛЕНО (костюмы): встроенные костюмы (OUTFIT_NAMES) — всегда ранг S, цвет не важен
    if result and result["category"] == "outfit" and result["name"] in OUTFIT_NAMES:
        result["force_rank"] = OUTFIT_RANK
    return result



MASTER_GLUED_FUZZY_LEN = 7        # нечёткий слитный поиск — только для названий от 7 букв



MASTER_GLUED_FUZZY_BONUS = 0.07   # порог сходства строже обычного (меньше ложных срабатываний)



def _glued_fuzzy(glued: str, folded: str, cutoff: float) -> float:
    """Нечёткий поиск названия в строке без пробелов (OCR слепил или разорвал слова и добавил
    лишние буквы): скользящее окно длиной len(folded) ± 1. 0.0 — совпадения нет."""
    n, best = len(folded), 0.0
    matcher = difflib.SequenceMatcher(None, autojunk=False)
    matcher.set_seq2(folded)
    for size in (n, n - 1, n + 1):
        for i in range(0, max(0, len(glued) - size) + 1):
            matcher.set_seq1(glued[i:i + size])
            if matcher.real_quick_ratio() < cutoff or matcher.quick_ratio() < cutoff:
                continue
            best = max(best, matcher.ratio())
    return best if best >= cutoff else 0.0



def _master_scan(text: str, lead=None, arc_only: bool = False):
    """Поиск эталона в уже подготовленной строке (см. master_match)."""
    tokens = re.findall(r"[^\W_]+", text)
    if not tokens:
        return None
    allowed = {"arc": ("arc",), "character": ("character",),
               "item": ("glider", "outfit", "paint", "car_skin", "item", "arc")}.get(lead)
    if arc_only:
        allowed = ARC_BANNER_ALLOWED_CATEGORIES      # баннер дуг: только дуги и предметы
    glued = _phrase_form(text)
    whole = _phrase_form(split_garbled_type(text)[1])   # название без префикса типа
    found = []                                  # (сходство, длина формы, эталон, фрагмент)
    for e in master_index():
        if allowed and e["category"] not in allowed:
            continue
        folded, n = e["form"], e["ntok"]
        cutoff = ROSTER_MATCH_CUTOFF if e["category"] == "character" else PHRASE_MATCH_CUTOFF
        best, where = 0.0, ""
        for size in range(max(1, n - 1), n + 2):
            for i in range(0, len(tokens) - size + 1):
                part = tokens[i:i + size]
                window = _phrase_form(" ".join(part))
                if window == folded:
                    if len(folded) < MASTER_MIN_FUZZY_LEN and folded != whole:
                        continue    # ИСПРАВЛЕНО: «Мы» внутри «Мы вместе» — не дуга «Мы.»
                    score = 1.0
                elif (len(folded) < MASTER_MIN_FUZZY_LEN
                      or abs(len(window) - len(folded)) > max(2, len(folded) // 4)):
                    continue
                else:
                    score = difflib.SequenceMatcher(None, window, folded).ratio()
                    if score < cutoff:
                        continue
                if score > best:
                    best, where = score, " ".join(part)
        if not best and len(folded) >= MASTER_MIN_GLUED_LEN and folded in glued:
            best, where = 1.0, text                     # слитное написание без пробелов
        if not best and len(folded) >= MASTER_GLUED_FUZZY_LEN and len(glued) >= len(folded) - 1:
            best, where = _glued_fuzzy(glued, folded, cutoff + MASTER_GLUED_FUZZY_BONUS), text
        if best:
            found.append((best, len(folded), e, where))
    found.sort(key=lambda t: (-t[0], -t[1]))
    exact = [t for t in found if t[0] >= 1.0]
    pick = None
    if exact:
        top = [t for t in exact if t[1] == exact[0][1]]
        if len({t[2]["category"] for t in top}) > 1:    # одно название у разных типов
            low = fold_name(text)
            top = [t for t in top
                   if fold_name(MASTER_CATEGORY_WORDS.get(t[2]["category"], "~~")) in low]
        if len({t[2]["category"] for t in top}) == 1:
            pick = top[0]
    else:
        # словарь известных искажений имён персонажей («Mepconax Sarap» -> Эдгар)
        if lead is None:
            hay = _letters_form(text)
            for name, aliases in CHARACTER_OCR_ALIASES.items():
                if any(_fuzzy_contains(hay, _letters_form(a), CHARACTER_ALIAS_CUTOFF)
                       for a in aliases):
                    entry = next((e for e in master_index()
                                  if e["category"] == "character" and e["name"] == name), None)
                    if entry:
                        return {"label": entry["label"], "name": name, "category": "character",
                                "score": CHARACTER_ALIAS_CUTOFF, "matched": text, "rank": None}
        if found:
            ranked = {}
            for t in found:                               # лучший результат по каждому названию
                ranked.setdefault((t[2]["category"], t[2]["name"]), t)
            ranked = sorted(ranked.values(), key=lambda t: (-t[0], -t[1]))
            if len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= PHRASE_AMBIGUITY_GAP:
                pick = ranked[0]
    if not pick:
        return None
    score, _n, e, where = pick
    return {"label": e["label"], "name": e["name"], "category": e["category"],
            "score": score, "matched": where, "rank": e["rank_hint"]}



# ---------------------------------------------------------------------------
# ИСПРАВЛЕНО: ОГРАНИЧЕННОЕ СОПОСТАВЛЕНИЕ названия по типу строки и цвету (рангу)
# ---------------------------------------------------------------------------
# Проблема: у строк с цветной обводкой (розовые A, золотые S) Tesseract портит и название, и
# слово-тип («Муга», «Пленер», «Nepconax»), а общий поиск по справочнику требует высокого
# сходства и отбрасывает такие строки. Но у строки известны ТИП (префикс «Дуга» / «Планер» /
# «Персонаж», даже искажённый) и РАНГ (цвет текста) — значит, искать надо не среди всех
# названий, а только среди названий этого типа и ранга: у A-персонажей 6 имён, у дуг B ранга
# 4 названия, у планеров 9. В таком маленьком наборе безопасно принимать и сильно искажённое
# написание, если оно заметно ближе к одному названию, чем к остальным.
SNAP_TYPE_WORDS = {"arc": "дуга", "glider": "планер", "character": "персонаж", "item": "предмет"}



SNAP_TYPE_CUTOFF = 0.60       # похожесть первого слова на слово-тип («Муга», «Пленер»)



SNAP_NAME_CUTOFF = 0.50       # минимальное сходство названия с эталоном внутри набора



SNAP_NAME_CUTOFF_LONG = 0.60  # то же для длинных названий (от 8 букв)



SNAP_MARGIN = 0.12            # отрыв лучшего эталона от второго — иначе не угадываем



SNAP_SHORT_FORM = 3           # название из ≤3 букв («Мы.») — отдельное правило (см. ниже)



_SNAP_HEAD_RE = re.compile(r"^\s*([^\s\-–—:|]{2,12})\s*(?:[\-–—:|]\s*|\s+)(.+)$")



# Путаницы Tesseract на ЦВЕТНЫХ строках с чёрной обводкой (розовый / золотой шрифт): буквы
# сливаются в «пятна» — «Минт» читается как «Maar» (и/н -> a, т -> r). Используются только при
# сопоставлении внутри набора «тип + ранг» (constrained_master_match), где вариантов единицы.
_STYLED_CONFUSION = {"и": "aeu", "н": "ah", "т": "rm", "к": "rk", "л": "an", "п": "n", "д": "a",
                     "я": "ar", "ь": "b", "ы": "bl", "а": "ao", "о": "ao", "е": "ec", "с": "ce"}



def _lookalike_cost(got: str, want: str) -> float:
    """Цена замены символа OCR на нужную букву: 0 — «двойник» (о/o/0, н/h/n, я/r…),
    0.35 — типичная путаница шрифта с обводкой (и -> a, т -> r)."""
    if got == want:
        return 0.0
    if got in _CHAR_LOOKALIKE.get(want, "") or fold_name(got) == fold_name(want):
        return 0.0
    if got.lower() in _STYLED_CONFUSION.get(want.lower(), ""):
        return 0.35
    return 1.0



def lookalike_similarity(raw: str, target: str) -> float:
    """Сходство 0..1: расстояние Левенштейна, где замена на «двойник» буквы бесплатна, а
    лишний знак препинания / цифра (мусор OCR) стоит вдвое дешевле лишней буквы."""
    a = re.sub(r"[\s.\-–—:|_]+", "", (raw or "").lower())
    b = re.sub(r"[\s.\-–—:|_]+", "", (target or "").lower())
    if not a or not b:
        return 0.0
    prev = [float(j) for j in range(len(b) + 1)]
    for i, ca in enumerate(a, 1):
        cur = [float(i)]
        junk = 0.5 if not ca.isalpha() else 1.0
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + junk,                       # лишний символ в OCR
                           cur[j - 1] + 1.0,                     # потерянная буква
                           prev[j - 1] + _lookalike_cost(ca, cb)))
        prev = cur
    return max(0.0, 1.0 - prev[-1] / max(len(a), len(b)))



def split_garbled_type(body: str):
    """(тип, остаток): тип — «arc» / «glider» / «character» / «item» / None по первому слову
    строки, даже искажённому («Муга», «Пленер», «Nepconax»); остаток — название без него."""
    t = strip_leading_junk(clean_name(body or ""))
    t = strip_leading_junk(_MASTER_NOISE_RE.sub(" ", BONUS_MARK_RE.sub(" ", t)))
    t = re.sub(r"\s+", " ", t).strip()
    head = _SNAP_HEAD_RE.match(t)
    if head:
        word, rest = head.group(1), head.group(2)
        best, kind = 0.0, None
        for k, ref in SNAP_TYPE_WORDS.items():
            score = lookalike_similarity(word, ref)
            if score > best:
                best, kind = score, k
        if kind and best >= SNAP_TYPE_CUTOFF and rest.strip():
            return kind, re.sub(r"\s+", " ", rest).strip()
    return None, t



def _snap_rank_of(entry: dict):
    """Ранг эталона мастер-справочника (5 / 4 / 3) или None, если он не задан."""
    cat, name = entry["category"], entry["name"]
    if cat == "character":
        info = ROSTER_KNOWN.get(name.lower())
        return info[1] if info else entry.get("rank_hint")
    if cat == "arc":
        info = ARC_KNOWN.get(f"{DUGA_PREFIX}{name}".lower())
        return info[1] if info else entry.get("rank_hint")
    if cat == "glider":
        return FIXED_RARITY.get("glider", 4)
    return entry.get("rank_hint")



def constrained_master_match(body: str, color=None, arc_only: bool = False):
    """Сопоставление с мастер-справочником ТОЛЬКО среди названий нужного типа и ранга.
    Возвращает словарь как master_match() или None. Вызывается после обычного поиска, если он
    ничего не нашёл. Тип берётся из (возможно искажённого) префикса строки, ранг — из цвета.
    Без явного префикса работает лишь для серых строк (ранг B): это всегда дуги."""
    kind, name = split_garbled_type(body)
    if arc_only:                        # баннер дуг: любая строка — только дуга (цвет задаёт ранг)
        if kind in ("character", "outfit", "glider", "paint", "car_skin"):
            name = strip_arc_blocked_prefix(body)
        kind, strict = "arc", kind in (None, "item")
    elif kind in (None, "item"):
        if color != 3:
            return None
        kind = "arc"                    # серая строка без читаемого префикса — дуга B ранга
        strict = True
    else:
        strict = False
    letters = re.sub(r"[\W_]+", "", name)
    if not letters:
        return None
    pool = []
    for e in master_index():
        if e["category"] != kind:
            continue
        rank = _snap_rank_of(e)
        if color and rank and rank != color:
            continue                    # цвет строки уже определил ранг — чужие ранги не нужны
        pool.append(e)
    if not pool:
        return None
    scored = []
    for e in pool:
        target = e["name"]
        score = lookalike_similarity(name, target)
        # OCR часто теряет начало / конец слова: сравниваем и с «обрезанным» названием
        if len(re.sub(r"[\W_]+", "", target)) >= 4:
            score = max(score, lookalike_similarity(name, target[:-1]) - 0.05,
                        lookalike_similarity(name, target[1:]) - 0.05)
        need = SNAP_NAME_CUTOFF_LONG if len(target) >= 8 else SNAP_NAME_CUTOFF
        if len(re.sub(r"[\W_]+", "", target)) <= SNAP_SHORT_FORM:
            need = 0.99                 # короткое название («Мы.») — только точное (см. ниже)
        if strict:
            need += 0.1
        if score >= need:
            scored.append((score, e))
    scored.sort(key=lambda t: -t[0])
    pick = None
    if scored and (len(scored) == 1 or scored[0][0] - scored[1][0] >= SNAP_MARGIN):
        pick = scored[0]
    elif not scored and len(letters) <= SNAP_SHORT_FORM + 1 and kind == "arc" and color == 3:
        # крошечный обрывок серой дуги не похож ни на одно длинное название: это короткая дуга
        # («Мы.») — выбираем её, только если такая в наборе ровно одна
        # и только если в строке есть признак искажения (латиница / цифра / «|»): чисто
        # кириллическое «Мир» или «Мыс» — это другое слово, а не испорченное «Мы.»
        short = [e for e in pool if len(re.sub(r"[\W_]+", "", e["name"])) <= SNAP_SHORT_FORM]
        if (len(short) == 1 and re.search(r"[A-Za-z0-9|!]", name)
                and lookalike_similarity(name, short[0]["name"]) >= 0.5):
            pick = (0.5, short[0])
    if not pick:
        return None
    score, e = pick
    return {"label": e["label"], "name": e["name"], "category": e["category"],
            "score": min(score, 0.99), "matched": name, "rank": None}



refresh_master_names()          # встроенные списки + master_names.json (если файл есть)
