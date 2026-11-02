"""Единый конвейер OCR для вкладок «Скриншот» и «Скриншот оптом»."""

import difflib
import re
from collections import Counter
from datetime import datetime

from PyQt6.QtCore import QDateTime

from ..catalog import (
    ARC_KNOWN, BONUS_TYPE_PREFIX, DUGA_PREFIX, LOOT_TYPES, OUTFIT_KNOWN, RANK_LETTERS, REWARD_KINDS,
    ROSTER_KNOWN,
)
from ..config import QT_DATE_FMT
from .columns import PAGE_ALTS, PAGE_INFO
from .config import OCR_PAGE_COMPLETE, OCR_PAGE_SIZE
from .dates import alt_day_stamp, soft_day_stamps
from .image import ocr_image
from .layout import FUZZY_REVIEW_SIM, line_confidence, OCR_FALLBACK_CONF, OCR_REVIEW_CONF
from .names import (
    _fuzzy_contains, _is_real_name, _letters_form, _loot_from_text, _trim_edge_junk, ARC_BANNER_BLOCKED_LOOT,
    BONUS_MARK_RE, CHARACTER_ALIAS_CUTOFF, CHARACTER_LABEL_CUTOFF, CHARACTER_LABEL_WORD,
    CHARACTER_OCR_ALIASES, clean_character_name, clean_name, constrained_master_match, fold_name,
    forced_item_label, fragment_stem_hint, hard_item_kind, is_resource_text, ITEM_PHRASE_KEYS, leading_type,
    master_match, match_roster_name, parse_ocr_result, recover_item_loot, snap_known_phrase, STRANA_SNA_RE,
    strict_fragment_key, strip_arc_blocked_prefix, strip_labels, strip_leading_junk,
)
from .noise import (
    _split_row_rank, clean_ocr_line, filter_ocr_lines, OCR_MAX_ROWS, prepare_ocr_row, split_ocr_line,
    strip_ui_notes_lines,
)
from .rarity import detect_rarity_colors


def apply_ocr_corrections(body: str, qty=None, known: dict = None):
    """НОВОЕ: единый шаг исправлений названия строки (вызывается из ocr_extract_pulls, то есть
    одинаково для вкладок «Скриншот» и «Скриншот оптом»). Возвращает каноническую строку
    или None, если исправлять нечего:
      * искажённое имя персонажа («Mepconax Sarap», «Плане ладшии младшего босса») ->
        «Персонаж: Эдгар» (словарь CHARACTER_OCR_ALIASES); искажённая подпись «Персонаж»
        + имя, похожее на состав, -> «Персонаж: <имя из состава>»;
      * «подерянныФравмени», «олерянны Фрапмента», «Фрапмента», «Фравмени» ->
        «Предмет - Потерянный фрагмент» (количество 30 / 50 берётся из строки);
      * дуги («дуга Чиетое небо») исправляет snap_known_phrase (KNOWN_PHRASES) в parse_ocr_result.
    Явные префиксы («Дуга - …», «Персонаж: …») и бонусы «Подарок за очки» не затрагиваются."""
    clean = strip_leading_junk(body or "")
    if not clean or BONUS_MARK_RE.search(clean):
        return None
    lead = leading_type(clean)
    if lead == "arc" or snap_known_phrase(clean, keys=("arc",) + ITEM_PHRASE_KEYS):
        return None                                    # эталонная дуга / предмет — не трогаем
    hay = _letters_form(clean)
    # OCR-ФИКС 5: строка с ключевым словом предмета / ресурса никогда не превращается в персонажа
    if lead is None and not is_resource_text(clean):
        for name, aliases in CHARACTER_OCR_ALIASES.items():
            if any(_fuzzy_contains(hay, _letters_form(a), CHARACTER_ALIAS_CUTOFF)
                   for a in aliases):
                return f"{CHARACTER_LABEL_WORD}: {name}"
        tokens = clean.split()
        if len(tokens) >= 2:                           # искажённая подпись «Персонаж» + имя
            first = _letters_form(tokens[0])
            if (6 <= len(first) <= 10 and not fragment_stem_hint(tokens[0])
                    and difflib.SequenceMatcher(None, first, _letters_form(
                        CHARACTER_LABEL_WORD)).ratio() >= CHARACTER_LABEL_CUTOFF):
                rest = " ".join(tokens[1:])
                hit = match_roster_name(rest)
                name = hit[0] if hit else clean_character_name(rest)
                if name:
                    return f"{CHARACTER_LABEL_WORD}: {name}"
    if lead in (None, "item") and fragment_stem_hint(clean):
        name = strip_labels(clean_name(clean), ("rank", "item"))
        if not _is_real_name(name, known):
            kind = "warp_fragment" if re.search(r"искр|warp", clean.lower()) else "lost_fragment"
            return f"Предмет - {REWARD_KINDS[kind]}"
    return None



# ---------------------------------------------------------------------------
# НОВОЕ: ЕДИНЫЙ КОНВЕЙЕР OCR для вкладок «Скриншот» и «Скриншот оптом»
# ---------------------------------------------------------------------------
def run_ocr_pipeline(path: str) -> dict:
    """Шаг 1 (тяжёлый, выполняется в фоновом потоке): подготовка изображения, Tesseract,
    очистка мусора и служебных строк, определение ранга по цвету текста.
    Возвращает {"lines", "text", "ranks", "glob"}. Бросает OcrError.

    Двухконвейерная схема: ТЕКСТ строк — конвейер Б (ocr_image: улучшенная копия строки ->
    Tesseract); РАНГ — конвейер А (detect_rarity_colors: пиксели неизменённого снимка по
    рамке названия). Конвейеры независимы: конвейер Б меняет только текст строки."""
    info = {}
    lines = filter_ocr_lines(ocr_image(path, info=info))  # конвейер Б: текст
    PAGE_INFO[path] = info.get("page")                   # номер страницы «N/M» (или None)
    PAGE_ALTS[path] = info.get("page_alts") or []
    ranks, glob = detect_rarity_colors(path, lines)      # конвейер А: ранг по цвету (без изменений)
    return {"lines": lines, "text": "\n".join(ln["text"] for ln in lines),
            "ranks": ranks, "glob": glob, "page": info.get("page"),
            "confs": [line_confidence(ln) for ln in lines]}     # НОВОЕ: уверенность по строкам



def parse_screenshot_text_ex(text: str, known: dict, ranks=None, glob=None,
                             default_loot: str = "character", confs=None):
    """Шаг 2 (лёгкий, в окне): разбор текста в записи — фильтр подсказок интерфейса, чистка
    строк, словари исправлений, ранги, типы, время. Цвета и уверенность по строкам годятся,
    только пока число строк не изменилось. Возвращает (записи, число пропущенных строк,
    нераспознанные строки для «Редактора нераспознанных строк»)."""
    n = len((text or "").splitlines())
    ranks = ranks if ranks is not None and n == len(ranks) else None
    confs = confs if confs is not None and n == len(confs) else None
    return ocr_extract_pulls_ex(text, known, ranks, glob, default_loot, confs)



def parse_screenshot_text(text: str, known: dict, ranks=None, glob=None,
                          default_loot: str = "character"):
    """Совместимая обёртка (вкладка «Скриншот»): возвращает (записи, число пропущенных строк)."""
    pulls, skipped, _rows = parse_screenshot_text_ex(text, known, ranks, glob, default_loot)
    return pulls, skipped



def ocr_extract_pulls(text: str, known: dict, line_ranks: list = None,
                      global_rank: int = None, default_loot: str = "character"):
    """Совместимая обёртка: (список круток, число пропущенных строк) — см. ocr_extract_pulls_ex."""
    pulls, skipped, _rows = ocr_extract_pulls_ex(text, known, line_ranks, global_rank,
                                                 default_loot)
    return pulls, skipped



def _next_row_lacks_stamp(lines: list, i: int) -> bool:
    for j in range(i + 1, len(lines)):
        cleaned = clean_ocr_line(lines[j])
        if not cleaned:
            continue
        cleaned, _dice = prepare_ocr_row(cleaned)
        if not cleaned:
            continue
        part = split_ocr_line(cleaned)
        return bool(re.search(r"[^\W\d_]{2,}", part["body"])) and part["stamp"] is None
    return False



def _is_recognized_row(body: str) -> bool:
    """НОВОЕ: строка без даты всё равно настоящая запись, если в ней есть распознанное
    название: явный префикс «Дуга - Название» / «Персонаж: Имя» или совпадение с
    мастер-справочником (персонажи, дуги, планеры, костюмы, предметы)."""
    clean = strip_leading_junk(body or "")
    if leading_type(clean) in ("arc", "character") and strip_labels(
            clean_name(clean), ("rank", "arc", "char", "item")):
        return True
    # ИСПРАВЛЕНО: обрывок без даты и префикса («мини» — мусор из заголовка) нечётким совпадением
    # («мини» ~ «Минт») записью не становится: нужно точное совпадение с эталоном
    found = master_match(body)
    return found is not None and found["score"] >= 1.0



def inherit_page_dates(rows: list) -> None:
    """OCR-ФИКС 6: наследование даты пула. Строки скриншота — одна крутка: у строки без
    прочитанной даты (или с системной датой «сегодня», подставленной вместо неверной) время берётся
    у ближайшей строки с самым частым достоверным временем. Если к дню приклеилась цифра
    количества («15 май» вместо «1 | 5 май»), день исправляется по общей дате страницы."""
    stamped = [r for r in rows if r["stamp"]]
    if not stamped:
        return
    # День-буква («Б май» — это 5 или 6 мая) — слабое свидетельство: если на странице есть
    # строки с ЯСНО прочитанным днём, выбирается вариант, совпадающий с ними (по времени
    # суток — сильнее, по дате — слабее). Раньше «Б» всегда становилась 6-м числом и даже
    # перебивала настоящие «5 май» при подсчёте большинства.
    firm = [r for r in stamped if not soft_day_stamps(r.get("raw_date") or "")]
    if firm:
        firm_full = Counter(r["stamp"] for r in firm)
        firm_date = Counter(r["stamp"][:10] for r in firm)
        for r in stamped:
            alts = soft_day_stamps(r.get("raw_date") or "")
            if not alts:
                continue
            best = max(alts, key=lambda a: (firm_full.get(a, 0), firm_date.get(a[:10], 0)))
            if firm_full.get(best, 0) or firm_date.get(best[:10], 0):
                r["stamp"] = best
    # Строки с ОДИНАКОВЫМ временем суток (ЧЧ:ММ:СС) — одна крутка; если у меньшинства из них
    # OCR исказил цифру дня («13 май» прочитано как «15 май»), берём дату большинства.
    by_clock = {}
    for r in stamped:
        by_clock.setdefault(r["stamp"][11:], []).append(r)
    for clock, group in by_clock.items():
        dates = Counter(r["stamp"][:10] for r in group)
        if len(dates) < 2:
            continue
        (major, major_n), (_second, second_n) = dates.most_common(2)
        if major_n >= 2 and major_n > second_n:
            for r in group:
                if r["stamp"][:10] != major:
                    r["stamp"] = f"{major} {clock}"
                    r["date_fixed"] = True
    today = datetime.now().strftime("%Y-%m-%d")
    top_date = Counter(r["stamp"][:10] for r in stamped).most_common(1)[0][0]
    for r in stamped:
        if r["stamp"][:10] == top_date:
            continue
        alt = alt_day_stamp(r["raw_date"])
        if alt and alt[:10] == top_date:
            r["stamp"] = alt
        elif r["stamp"][:10] == today and len(stamped) >= 2:
            r["stamp"] = None                       # похоже на подставленную системную дату
    good = [r for r in rows if r["stamp"]]
    if not good:
        return
    cnt = Counter(r["stamp"] for r in good)
    best = max(cnt.values())
    for r in rows:
        if r["stamp"]:
            continue
        src = min((g for g in good if cnt[g["stamp"]] == best),
                  key=lambda g: abs(g["line"] - r["line"]))
        r["stamp"], r["date_inherited"], r["no_date"] = src["stamp"], True, False



def fill_missing_rows(rows: list, arc_mode: bool = False) -> list:
    """OCR-ФИКС 6: полнота страницы. 1) Строка только со временем (название не прочитано —
    тёмные/фиолетовые строки вроде «Планер - Предвестник») получает название по цвету строки:
    золото — не угадывается (уйдёт в редактор), серый — повтор единственного «Потерянного
    фрагмента» страницы, иначе «Планер - Предвестник». 2) Если найдено 3–4 строки из 5: одной
    недостающей строке при единственном «Потерянном фрагменте» достраивается его дубль (второй
    такой же ряд Tesseract пропускает), в остальных случаях в редактор добавляются пустые
    строки-заглушки с общим временем страницы. Все достроенные строки помечаются для проверки."""
    for r in rows:
        if not r.get("missing"):
            continue
        if arc_mode:
            continue         # баннер дуг: «Планер» / «Фрагмент» не выпадают — строка уйдёт в редактор
        col = r["color"]
        if col == 5:
            continue                                     # S-ранг не угадываем
        lost = [x for x in rows if not x.get("missing") and hard_item_kind(x["body"]) == "lost_fragment"]
        if col == 3 and len(lost) == 1:
            r["body"], r["qty"] = lost[0]["body"], lost[0]["qty"]
            r["guess"], r["guess_note"] = True, "текст строки не прочитан: достроен повтор «Потерянного фрагмента»"
        else:
            r["body"], r["guess"] = "Планер - Предвестник", True
    n = len(rows)
    if not (OCR_PAGE_COMPLETE and 3 <= n < OCR_PAGE_SIZE):
        return rows
    stamps = [r["stamp"] for r in rows if r["stamp"]]
    batch = Counter(stamps).most_common(1)[0][0] if stamps else None
    lost = [r for r in rows if hard_item_kind(r["body"]) == "lost_fragment" and not r.get("guess")]
    missing = OCR_PAGE_SIZE - n
    note = f"достроена строка: на странице должно быть {OCR_PAGE_SIZE} записей, найдено {n}"
    if missing == 1 and len(lost) == 1 and not arc_mode:
        dup = dict(lost[0], line=lost[0]["line"] + 0.5, guess=True, conf=None, guess_note=note)
        rows.append(dup)
    else:
        last = max(r["line"] for r in rows)
        for k in range(missing):
            rows.append({"body": "", "qty": None, "stamp": batch, "raw_date": "", "color": None,
                         "bonus": False, "dice": False, "line": last + 0.5 * (k + 1),
                         "conf": None, "placeholder": True})
    rows.sort(key=lambda r: r["line"])
    return rows



def ocr_extract_pulls_ex(text: str, known: dict, line_ranks: list = None,
                         global_rank: int = None, default_loot: str = "character",
                         line_confs: list = None):
    """Разбирает весь текст скриншота и возвращает (список круток, число пропущенных строк,
    список нераспознанных строк). НОВОЕ: line_confs[i] — уверенность OCR строки i; у каждой
    записи появляются «line» (номер строки текста — место в раскладке скриншота), «conf»,
    «weak» (причины проверки) и «needs_review» (строку надо проверить глазами).

    Строки очищаются от служебного текста (clean_ocr_line) и разбираются по одной:
    каждая строка со словами — отдельная запись (название, ранг, тип, количество).
    Время берётся из самой строки; строка только со временем относится к предыдущей записи
    без времени («название / время» друг под другом), а если такой нет — к следующей
    («время / название»). line_ranks[i] — ранг по цвету рядом со строкой i (индексы — по
    строкам text); global_rank — ранг по цвету всего снимка, он используется только когда на
    снимке одна запись (в списке он не различает строки).
    Каждый элемент — словарь parse_ocr_result + «known» (имя есть в истории/составе) и
    «doubtful» (нет времени, имя неизвестно, а у других строк время есть — возможно, это
    мусор OCR; такие строки в списке не отмечаются). Порядок — как на скриншоте."""
    rows, pending = [], None

    def orphan(pd):
        """OCR-ФИКС 6: метка времени без названия — строка, текст которой OCR не прочитал."""
        st, rd, ln, col, cf, dc = pd
        rows.append({"body": "", "qty": None, "stamp": st, "raw_date": rd, "color": col,
                     "bonus": False, "dice": dc, "line": ln, "conf": cf, "missing": True})
    # OCR-ФИКС 4: служебная подсказка интерфейса вырезается ДО разбора строк (число строк и
    # их индексы не меняются — цвета рангов line_ranks остаются на своих местах)
    ui_lines = strip_ui_notes_lines((text or "").splitlines())
    for i, raw in enumerate(ui_lines):
        line = clean_ocr_line(raw)
        if not line:
            continue
        line, has_dice = prepare_ocr_row(line)      # единые правила для каждой строки
        if not line:
            continue
        # ИЗМЕНЕНО: название, количество и дата отделяются одной функцией (split_ocr_line),
        # поэтому дата и количество больше не попадают в название предмета
        part = split_ocr_line(line)
        stamp, body, qty, raw_date = part["stamp"], part["body"], part["qty"], part["raw_date"]
        # СТРОГО: бонусом считается только строка, в которой САМА есть «Подарок за очки»
        # (заголовок на соседней строке на следующие записи не влияет)
        bonus_here = bool(BONUS_MARK_RE.search(body))
        if not re.search(r"[^\W\d_]{2,}", body):       # строка только со временем
            if stamp:
                color_here = line_ranks[i] if line_ranks and i < len(line_ranks) else None
                if (color_here == 4 and default_loot != "arc"      # в таблице дуг «Планер» не гадаем
                        and not (rows and rows[-1]["stamp"] is None and not rows[-1]["qty"])
                        and not _next_row_lacks_stamp(ui_lines, i)):
                    rows.append({"body": "Планер - Предвестник", "qty": None, "stamp": stamp,
                                 "raw_date": raw_date, "color": color_here, "bonus": False,
                                 "dice": has_dice, "line": i,
                                 "conf": line_confs[i] if line_confs and i < len(line_confs)
                                 else None, "guess": True})
                elif rows and rows[-1]["stamp"] is None:
                    rows[-1]["stamp"], rows[-1]["raw_date"] = stamp, raw_date
                else:
                    if pending:
                        orphan(pending)
                    pending = (stamp, raw_date, i, color_here, 
                               line_confs[i] if line_confs and i < len(line_confs) else None,
                               has_dice)
            continue
        if stamp is None and pending:
            (stamp, raw_date), pending = pending[:2], None
        elif pending and stamp:
            orphan(pending)
            pending = None
        color = line_ranks[i] if line_ranks and i < len(line_ranks) else None
        conf = line_confs[i] if line_confs and i < len(line_confs) else None
        rows.append({"body": body, "qty": qty, "stamp": stamp, "raw_date": raw_date,
                     "color": color, "bonus": bonus_here, "dice": has_dice,
                     "line": i, "conf": conf})
    if pending:
        orphan(pending)
    rows.sort(key=lambda r: r["line"])
    rows = rows[:OCR_MAX_ROWS]
    # OCR-ФИКС 4: ЧИСТЫЙ пакет. Если на снимке есть таблица (хотя бы у одной строки найдена
    # дата), то настоящая запись — это строка с названием И датой. Строки без даты (остатки
    # заголовков, подсказок, мусор OCR) в список предпросмотра не попадают. Если дат нет
    # вообще (текст набран вручную), строки разбираются как раньше.
    dropped = 0
    if any(r["stamp"] or r["raw_date"] for r in rows):
        # ИСПРАВЛЕНО: раньше строка без прочитанной даты отбрасывалась всегда — так пропадали
        # настоящие записи («Дуга - Настоящая музыка», «Дуга - Опасная игра», персонажи), у
        # которых OCR испортил дату. Теперь без даты остаются строки с РАСПОЗНАННЫМ названием
        # (явный префикс «Дуга - …» / «Персонаж: …» или совпадение с мастер-справочником):
        # они попадают в список с пометкой «время не найдено». Мусор без названия отбрасывается.
        valid = []
        for r in rows:
            if r["stamp"] or r["raw_date"]:
                valid.append(r)
            elif _is_recognized_row(r["body"]):
                r["no_date"] = True
                valid.append(r)
        dropped, rows = len(rows) - len(valid), valid
        # OCR-ФИКС 6: одна страница = одна крутка: общая дата и достройка недостающих строк
        inherit_page_dates(rows)
        rows = fill_missing_rows(rows, arc_mode=(default_loot == "arc"))
        inherit_page_dates(rows)               # у достроенных строк время тоже общее

    timed = sum(1 for r in rows if r["stamp"])
    out, skipped_rows = [], []
    for r in rows:
        body, qty = r["body"], r["qty"]
        body, letter = _split_row_rank(_trim_edge_junk(body))
        # OCR-ФИКС 7: «Страна сна» — признак «вне гаранта»; фраза вырезается из названия
        sna = bool(STRANA_SNA_RE.search(body))
        if sna:
            body = re.sub(r"\s+", " ", STRANA_SNA_RE.sub(" ", body)).strip(" -–—:|") or body
        raw_body, fallbacks = body, []     # прочитанное название и запасные правила (для проверки)
        raw = body + (f" Ранг {letter}" if letter else "") + (f" ×{qty}" if qty else "")
        color = r["color"] or (global_rank if len(rows) == 1 else None)
        # НОВОЕ: МАСТЕР-СПРАВОЧНИК. Если в строке есть эталонное название (персонаж, дуга,
        # планер, костюм, предмет) — вся строка заменяется чистым каноническим названием:
        # мусор OCR, номера и «Подарок за очки» вокруг исчезают (бонус уже запомнен в r["bonus"]).
        # Один и тот же шаг работает на всех трёх вкладках со скриншотами.
        arc_mode = default_loot == "arc"       # баннер дуг: персонажи, костюмы, планеры не выпадают
        # ИСПРАВЛЕНО: в таблице бросков («Эксклюзивная доска») персонажи и дуги идут вперемешку, а
        # выбран может быть баннер «Дуги»: «Персонаж - Минт» превращался в «Дуга - Минт». Цветная
        # строка (персонажи — фиолетовые / золотые, серые — всегда дуги), которая точно совпала с
        # персонажем / планером / костюмом из справочника, остаётся самим собой.
        if arc_mode and color in (4, 5):
            _cand = strip_arc_blocked_prefix(body)
            _mm = master_match(_cand)
            if (_mm and _mm.get("category") in ("character", "glider", "outfit")
                    and _mm["score"] >= 0.85):
                arc_mode = False
        if arc_mode:
            body = strip_arc_blocked_prefix(body)
        hard_kind = hard_item_kind(body)       # OCR-ФИКС 6: ключевые слова предметов
        master = None if hard_kind else master_match(body, arc_only=arc_mode)
        # ИСПРАВЛЕНО: серая строка (ранг B по цвету) — не персонаж A/S: персонажи всегда фиолетовые
        # или золотые. Нечёткое совпадение такой строки с персонажем («Мы.» -> «Минт») отбрасывается,
        # иначе жёсткий ранг персонажа перекрывал цвет и дуга превращалась в персонажа.
        if (master and master.get("category") == "character" and color == 3
                and master["score"] < 1.0 and leading_type(body) != "character"):
            master = None
        # ИСПРАВЛЕНО: обычный поиск не нашёл название (искажённая строка с цветной обводкой) —
        # ищем среди названий ТОЛЬКО нужного типа (префикс строки) и ранга (цвет текста)
        if master is None and not hard_kind:
            master = constrained_master_match(body, color, arc_only=arc_mode)
            if master:
                fallbacks.append("название подобрано по типу и рангу строки")
        if master:
            body, raw_body = master["label"], master["matched"]
            if master["score"] < 1.0:
                fallbacks.append("название исправлено по мастер-справочнику")
            if master["rank"] and not letter:         # ранг из master_names.json
                letter = RANK_LETTERS[master["rank"]]
            if master.get("qty_options") and qty not in master["qty_options"]:
                qty = master["qty_default"]
            if master.get("force_rank"):              # жёсткое правило (планер — всегда A)
                color, letter = None, RANK_LETTERS[master["force_rank"]]
            raw = body + (f" Ранг {letter}" if letter else "") + (f" ×{qty}" if qty else "")
        # НОВОЕ: словари исправлений (фрагменты, имена персонажей) — единый шаг для обеих вкладок
        fixed = None if (master or hard_kind or arc_mode) else apply_ocr_corrections(body, qty, known)
        if fixed:
            body = fixed
            fallbacks.append("название исправлено по словарю")
            raw = body + (f" Ранг {letter}" if letter else "") + (f" ×{qty}" if qty else "")
        # OCR-ФИКС 2: искажённый предмет («: Прут Фочеарякитый Фрезия 50») жёстко становится
        # «Предмет - Потерянный фрагмент» и никогда не попадает в персонажи
        forced = (f"Предмет - {REWARD_KINDS[hard_kind]}" if hard_kind
                  else forced_item_label(body, qty, known))
        if forced:
            if not (hard_kind and _loot_from_text(strip_leading_junk(body))):
                fallbacks.append("предмет определён по запасному правилу")
            raw = forced + (f" ×{qty}" if qty else "") + (f" Ранг {letter}" if letter else "")
        p = parse_ocr_result(raw, known, color_rank=color, bonus=r["bonus"],
                             default_loot=default_loot, dice_icon=r["dice"])
        # OCR-ФИКС («страховка»): у записи таблицы есть и дата, и количество, а тип не
        # определился (например, «Предмет» с искажённым названием) — пробуем узнать предмет
        # по самому мягкому порогу, а не терять строку
        if not p["loot"] and r["stamp"] and qty and not r["bonus"]:
            label = recover_item_loot(body)
            if label:
                fallbacks.append("предмет угадан по мягкому порогу")
                p = parse_ocr_result(f"{label} ×{qty}", known, color_rank=color,
                                     bonus=r["bonus"], default_loot=default_loot)
        # баннер дуг: что бы ни определилось (персонаж, костюм, планер, окраска, скин) — это
        # не может выпасть; строка переразбирается как дуга по очищенному названию
        if arc_mode and p["loot"] in ARC_BANNER_BLOCKED_LOOT:
            alt = strip_arc_blocked_prefix(r["body"])
            fallbacks.append("в баннере дуг персонажи, костюмы и планеры не выпадают")
            p = parse_ocr_result(f"{DUGA_PREFIX}{alt}" + (f" Ранг {letter}" if letter else ""),
                                 known, color_rank=color, bonus=r["bonus"],
                                 default_loot="arc", dice_icon=r["dice"])
            if p["loot"] in ARC_BANNER_BLOCKED_LOOT:
                p["loot"] = None
        # OCR-ФИКС 3: последний рубеж — мусорная строка с количеством 30 / 50 или ключевым
        # словом фрагмента НЕ может остаться персонажем / дугой: переразбираем как предмет
        if p["loot"] in ("character", "arc") and not r["bonus"] and not p["is_bonus"]:
            fkey = strict_fragment_key(body, qty, known)
            if fkey:
                fallbacks.append("материал определён по запасному правилу")
                p = parse_ocr_result(f"Предмет - {REWARD_KINDS[fkey]}"
                                     + (f" ×{qty}" if qty else "")
                                     + (f" Ранг {letter}" if letter else ""),
                                     known, color_rank=color, default_loot=default_loot)
        if not p["loot"] or (p["name"] and len(p["name"]) < 2):
            # не крутка (или мусор OCR): строка уходит в «Редактор нераспознанных строк»
            skipped_rows.append({"line": r["line"], "body": r["body"], "qty": r["qty"],
                                 "stamp": r["stamp"], "raw_date": r["raw_date"],
                                 "conf": r["conf"], "bonus": r["bonus"], "color": r["color"]})
            continue
        if r["stamp"]:
            p["timestamp"] = QDateTime.fromString(r["stamp"], QT_DATE_FMT)
            p["has_time"] = True
        # НОВОЕ: сырая дата и количество со снимка — для подсказок в списке и отладки
        p["raw_date"], p["amount"] = r["raw_date"], qty
        # имена из состава персонажей тоже считаются «известными»
        p["known"] = (p["name"].lower() in known or p["name"].lower() in ROSTER_KNOWN
                      or p["name"].lower() in ARC_KNOWN or p["name"].lower() in OUTFIT_KNOWN)
        p["doubtful"] = (not p["known"] and not p["has_time"] and timed >= 2
                         and p["loot"] in ("character", "arc"))
        # НОВОЕ: оценка надёжности строки — уверенность OCR, запасные правила, нечёткое сходство
        conf, reasons = r["conf"], []
        if conf is not None and conf < OCR_REVIEW_CONF:
            reasons.append(f"низкая уверенность OCR: {conf:.0f}%")
        if fallbacks and (conf is None or conf < OCR_FALLBACK_CONF):
            reasons.append(fallbacks[0])
        sim = master["score"] if master else _name_similarity(raw_body, p)
        if sim is not None and sim < FUZZY_REVIEW_SIM:
            reasons.append(f"нечёткое совпадение названия: {sim:.0%}")
        if p["doubtful"]:
            reasons.append("нет времени, имя неизвестно")
        if r.get("guess"):
            reasons.append(r.get("guess_note")
                           or "текст строки не прочитан: планер определён по цвету строки")
        if r.get("date_fixed"):
            reasons.append("дата исправлена по соседним строкам с тем же временем")
        if r.get("no_date") and not p["has_time"]:
            reasons.append("время не найдено — проверьте дату")
        if sna and LOOT_TYPES[p["loot"]]["mode"] == "wish":
            p["is_bonus"] = True                  # крутка (персонаж/дуга) вне гаранта
            p["type_text"] = f"{BONUS_TYPE_PREFIX} - {p['type_text']}"
        p["no_pity"] = bool(sna or p["is_bonus"])
        p.update(line=r["line"], conf=conf, weak=reasons, needs_review=bool(reasons),
                 body_raw=r["body"])
        out.append(p)
    return out, len(rows) - len(out) + dropped, skipped_rows



def _name_similarity(raw_body: str, p: dict):
    """НОВОЕ: сходство (0..1) прочитанного названия с итоговым — чем меньше, тем сильнее OCR
    «исправили» словарём / нечётким поиском. None — сравнивать нечего. Название предметов без
    имени (кубики, фрагменты) сравнивается с названием вида («Потерянный фрагмент»)."""
    info = LOOT_TYPES.get(p.get("loot"))
    if info is None:
        return None
    if info.get("hide_name") and info.get("kind") in REWARD_KINDS:
        target = REWARD_KINDS[info["kind"]]
    else:
        target = strip_labels(p.get("name") or "")
    raw = strip_labels(clean_name(strip_leading_junk(raw_body or "")))
    if not raw or not target:
        return None
    a, b = fold_name(raw), fold_name(target)
    if not a or not b:
        return None
    return 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()



def ocr_candidates(text: str, known: dict, line_ranks: list = None,
                   global_rank: int = None) -> list:
    """Совместимая обёртка: список разобранных круток скриншота (см. ocr_extract_pulls)."""
    return ocr_extract_pulls(text, known, line_ranks, global_rank)[0]



def bottom_to_top_order(pulls: list) -> list:
    """Порядок записи пакета в базу: СНИЗУ ВВЕРХ (от старых к новым).

    ИСПРАВЛЕНО. В истории игры самая верхняя строка выпала ПОЗЖЕ всех (новейшая), самая
    нижняя — РАНЬШЕ всех (старейшая). Чтобы временная линия и счёт гаранта были верными,
    старые записи должны попасть в базу первыми, а новые — последними, поэтому список
    строк скриншота просто разворачивается: идём с последней строки к первой.

    Порядок НЕ зависит от распознанных времён: у десятикратного броска все записи имеют
    одно и то же время, и только позиция строки на скриншоте различает их. Исходный список
    не меняется — возвращается новая копия."""
    return list(reversed(pulls))
