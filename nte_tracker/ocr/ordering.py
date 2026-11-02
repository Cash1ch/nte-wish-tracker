"""Порядок скриншотов и хронология записей при пакетном распознавании."""

import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QDateTime

from ..config import DATE_FMT, QT_DATE_FMT
from ..workers.ocr_threads import natural_key
from .config import OCR_PAGE_SIZE
from .dates import soft_day_stamps
from .pipeline import bottom_to_top_order


def file_created_ns(path) -> int:
    """Время создания файла (нс): st_birthtime, на Windows — st_ctime; иначе наименьшее из
    ctime и mtime. Ошибка чтения — 0."""
    try:
        st = Path(path).stat()
    except OSError:
        return 0
    birth = getattr(st, "st_birthtime", None)
    if birth is not None:
        return int(birth * 1_000_000_000)
    if sys.platform == "win32":
        return st.st_ctime_ns
    return min(st.st_ctime_ns, st.st_mtime_ns)



def mass_sort_key(path) -> tuple:
    """Ключ порядка файлов: строго по дате создания (старые первыми); при равенстве — дата
    изменения, затем естественное имя файла и путь."""
    try:
        mtime = Path(path).stat().st_mtime_ns
    except OSError:
        mtime = 0
    return (file_created_ns(path), mtime, natural_key(path), str(path))



# Порядок скриншотов с ОДИНАКОВЫМ временем записей (десятикратный бросок, разорванный на две
# страницы): True — страницы снимались сверху вниз (ранний файл содержит более НОВЫЕ записи),
# False — снизу вверх (ранний файл содержит более СТАРЫЕ записи).
SHOT_PAGES_CAPTURED_TOP_DOWN = True



STAMP_CONFUSABLE = {frozenset(x) for x in ("35", "17", "08", "68", "56", "38", "06", "89")}



def repair_stamp_misreads(pull_lists: list) -> int:
    """Исправляет одиночные ошибки OCR в цифрах времени («31» прочитано как «51») по всем
    скриншотам пакета: если метка встречается один-два раза, а метка, отличающаяся ровно одной
    похожей цифрой (3/5, 1/7, 0/8, 6/8, 5/6 ...), встречается заметно чаще — берётся частая.
    Исправленные записи помечаются жёлтым. Возвращает число исправленных записей."""
    items = [p for pulls in pull_lists for p in pulls if p.get("has_time")]
    fixed = 0
    # день-буква («Б май» = 5 или 6 мая): берём вариант, который подтверждают записи с чётко
    # прочитанным днём по всему пакету (по полной метке времени)
    firm_count = Counter(p["timestamp"].toString(QT_DATE_FMT) for p in items
                         if not soft_day_stamps(p.get("raw_date") or ""))
    for p in items:
        alts = soft_day_stamps(p.get("raw_date") or "")
        if not alts or p.get("time_locked"):
            continue
        cur = p["timestamp"].toString(QT_DATE_FMT)
        best = max(alts, key=lambda a: firm_count.get(a, 0))
        if firm_count.get(best, 0) and best != cur:
            p["timestamp"] = QDateTime.fromString(best, QT_DATE_FMT)
            fixed += 1          # уверенная правка («Б» = 5): жёлтой пометки не нужно
    count = Counter(p["timestamp"].toString(QT_DATE_FMT) for p in items)
    for p in items:
        cur = p["timestamp"].toString(QT_DATE_FMT)
        own, best, best_n = count[cur], None, 0
        if own > 2 or p.get("time_locked"):
            continue
        for i, ch in enumerate(cur):
            if not ch.isdigit():
                continue
            for other in "0123456789":
                if other == ch or frozenset((ch, other)) not in STAMP_CONFUSABLE:
                    continue
                cand = cur[:i] + other + cur[i + 1:]
                n = count.get(cand, 0)
                if n >= 2 and n > own * 2 and n > best_n:
                    try:
                        datetime.strptime(cand, DATE_FMT)
                    except ValueError:
                        continue
                    best, best_n = cand, n
        if best:
            p["timestamp"] = QDateTime.fromString(best, QT_DATE_FMT)
            reasons = list(p.get("weak") or [])
            reasons.append(f"время исправлено по соседним записям: {cur[11:]} → {best[11:]}")
            p["weak"], p["needs_review"] = reasons, True
            fixed += 1
    return fixed



def shot_order_key(stamps: list, order: int, total: int) -> tuple:
    """Ключ порядка скриншота в пакете: сначала по найденному времени записей (старые первыми:
    минимум, затем максимум), при полном совпадении — по порядку создания файла (order) с учётом
    SHOT_PAGES_CAPTURED_TOP_DOWN; скриншоты без найденного времени — в конце по порядку файлов."""
    if not stamps:
        return (1, "", "", order)
    tie = (total - order) if SHOT_PAGES_CAPTURED_TOP_DOWN else order
    return (0, min(stamps), max(stamps), tie)



def _lnds_keep(values: list) -> set:
    """Индексы наибольшей неубывающей подпоследовательности (они считаются верными)."""
    import bisect
    tails, tails_idx, prev = [], [], [-1] * len(values)
    for i, v in enumerate(values):
        pos = bisect.bisect_right(tails, v)
        if pos == len(tails):
            tails.append(v)
            tails_idx.append(i)
        else:
            tails[pos], tails_idx[pos] = v, i
        prev[i] = tails_idx[pos - 1] if pos else -1
    keep, k = set(), (tails_idx[-1] if tails_idx else -1)
    while k != -1:
        keep.add(k)
        k = prev[k]
    return keep



def _add_review_reason(p: dict, reason: str) -> None:
    reasons = list(p.get("weak") or [])
    reasons.append(reason)
    p["weak"], p["needs_review"] = reasons, True



def mark_locked_times(entries: list) -> None:
    """Записи, время которых пользователь исправил вручную в редакторе, автоматическим
    исправлениям времени не подлежат."""
    for e in entries:
        edits = e.get("edits") or {}
        for p in e["pulls"]:
            p["time_locked"] = p.get("line") in edits



def resolve_page_conflicts(entries: list) -> list:
    """Два скриншота с одним номером страницы — одно из прочтений ошибочно (113 → 115). У менее
    уверенного (меньше голосов) берётся запасное прочтение с тем же «всего», номер которого ещё
    не занят. Возвращает предупреждения о сделанных заменах."""
    notes = []
    for _ in range(len(entries)):
        by_page = {}
        for e in entries:
            by_page.setdefault(e["page"], []).append(e)
        conflict = next((grp for grp in by_page.values() if len(grp) > 1), None)
        if not conflict:
            break

        def votes(e):
            return dict(e.get("page_alts") or []).get(e["page"], 0)
        conflict.sort(key=lambda e: -votes(e))
        taken = {e["page"][0] for e in entries}
        changed = False
        for e in conflict[1:]:
            alts = [pg for pg, _n in (e.get("page_alts") or [])
                    if pg[1] == e["page"][1] and pg[0] not in taken]
            if alts:
                notes.append(f"номер страницы файла {Path(e['path']).name} исправлен: "
                             f"{e['page'][0]} → {alts[0][0]}")
                e["page"] = alts[0]
                taken.add(alts[0][0])
                changed = True
        if not changed:
            break
    return notes



def repair_page_numbers(entries: list) -> list:
    """ИСПРАВЛЕНО (порядок и даты страниц): Tesseract путает похожие цифры и в номере страницы —
    «34/115» читается как «54/115». Такая страница попадала в начало пакета (как самая старая),
    а все её записи получали неверный порядок и счётчик. Здесь номера проверяются по времени:
    по возрастанию номера время записей должно убывать (страница с большим номером старше).
    Номера, нарушающие это, подменяются запасным прочтением или похожей цифрой, если после
    замены хронология и непрерывность страниц становятся лучше. Возвращает список замечаний."""
    if len(entries) < 3 or not all(e.get("page") for e in entries):
        return []
    total = entries[0]["page"][1]
    if any(e["page"][1] != total for e in entries):
        return []
    top = {id(e): max(e["stamps"]) if e.get("stamps") else None for e in entries}
    start = {id(e): e["page"][0] for e in entries}

    def score(pages: dict) -> float:
        order = sorted(entries, key=lambda e: -pages[id(e)])
        times = [top[id(e)] for e in order if top[id(e)]]
        inversions = len(times) - len(_lnds_keep(times)) if times else 0
        nums = [pages[id(e)] for e in entries]
        dup = len(nums) - len(set(nums))
        missing = (max(nums) - min(nums) + 1) - len(set(nums))
        changed = sum(1 for e in entries if pages[id(e)] != start[id(e)])
        return 10 * inversions + 3 * dup + 0.05 * missing + 2 * changed

    def candidates(e) -> set:
        n = start[id(e)]
        out = {pg for pg, _v in (e.get("page_alts") or []) if pg[1] == total}
        out = {pg[0] for pg in out}
        digits = str(n)
        for i, ch in enumerate(digits):
            for other in "0123456789":
                if other != ch and frozenset((ch, other)) in STAMP_CONFUSABLE:
                    v = int((digits[:i] + other + digits[i + 1:]) or 0)
                    out.add(v)
        return {v for v in out if 1 <= v <= total and v != n}

    pages = dict(start)
    best = score(pages)
    for _ in range(len(entries) * 2):
        move = None
        for e in entries:
            for v in candidates(e):
                trial = dict(pages)
                trial[id(e)] = v
                sc = score(trial)
                if sc < best - 1e-9 and (move is None or sc < move[0]):
                    move = (sc, e, v)
        if move is None:
            break
        best, e, v = move
        pages[id(e)] = v
    notes = []
    for e in entries:
        if pages[id(e)] != start[id(e)]:
            notes.append(f"номер страницы файла {Path(e['path']).name} исправлен по времени записей: "
                         f"{start[id(e)]} → {pages[id(e)]}")
            e["page"] = (pages[id(e)], total)
    return notes



def order_shots(entries: list, total_files: int):
    """Порядок скриншотов пакета. entries — [{"order", "path", "pulls", "page"}].
    Если номер страницы «N/M» найден на КАЖДОМ скриншоте и у всех одно M — порядок строго по
    странице (больший номер — старше), время только проверяется. Иначе — по найденному времени
    (shot_order_key). Возвращает (упорядоченные записи, предупреждения, page_mode)."""
    warnings = []
    for e in entries:
        e["stamps"] = [p["timestamp"].toString(QT_DATE_FMT) for p in e["pulls"] if p["has_time"]]
    totals = Counter(e["page"][1] for e in entries if e.get("page"))
    if len(totals) > 1:
        common = totals.most_common(1)[0][0]
        for e in entries:
            if e.get("page") and e["page"][1] != common:
                alts = [pg for pg, _n in (e.get("page_alts") or []) if pg[1] == common]
                if alts:
                    e["page"] = alts[0]
    pages = [e.get("page") for e in entries]
    if entries and all(pages):
        warnings += resolve_page_conflicts(entries)
        warnings += repair_page_numbers(entries)
        pages = [e.get("page") for e in entries]
    page_mode = bool(entries) and all(pages) and len({pg[1] for pg in pages}) == 1

    def time_key(e):
        return shot_order_key(e["stamps"], e["order"], total_files)

    if page_mode:
        ordered = sorted(entries, key=lambda e: (-e["page"][0], time_key(e)))
        total = entries[0]["page"][1]
        nums = [e["page"][0] for e in ordered]
        dup = sorted({n for n in nums if nums.count(n) > 1}, reverse=True)
        if dup:
            warnings.append("одна страница истории на нескольких скриншотах: "
                            + ", ".join(map(str, dup)) + " — возможны дубли")
        missing = sorted(set(range(min(nums), max(nums) + 1)) - set(nums), reverse=True)
        if missing:
            shown = ", ".join(map(str, missing[:12])) + ("…" if len(missing) > 12 else "")
            warnings.append(f"пропущены страницы между скриншотами: {shown} — гарант может быть неверным")
        for e in ordered:
            n = e["page"][0]
            found = len(e["pulls"])
            if n != total and found != OCR_PAGE_SIZE:
                warnings.append(f"страница {n}: найдено записей {found} из {OCR_PAGE_SIZE}")
    else:
        ordered = sorted(entries, key=time_key)
        if entries and any(pages):
            warnings.append("номер страницы «N/M» найден не на всех скриншотах (или у них разное "
                            "число страниц) — порядок задан по времени записей")
        elif entries:
            warnings.append("номер страницы «N/M» на скриншотах не найден — порядок задан по "
                            "времени записей")
    return ordered, warnings, page_mode



def enforce_chronology(ordered: list):
    """Проверка монотонности времени по всей цепочке «страницы от старых к новым, строки снизу
    вверх». Время должно только расти; записи, нарушающие рост (обычно — ошибка OCR в цифре),
    исправляются: сначала подбором одной похожей цифры, чтобы время встало между верными
    соседями, иначе подставляется время ближайшей верной записи ПЕРЕД ней (порядок на
    странице известен точно). Исправленные записи помечаются жёлтым.
    Возвращает (число исправлений, предупреждения)."""
    seq = [p for e in ordered for p in bottom_to_top_order(e["pulls"]) if p.get("has_time")]
    if len(seq) < 3:
        return 0, []
    vals = [p["timestamp"].toString(QT_DATE_FMT) for p in seq]
    keep = _lnds_keep(vals)
    bad = [i for i in range(len(seq)) if i not in keep]
    if not bad:
        return 0, []
    if len(bad) > max(3, int(len(seq) * 0.2)):
        for i in bad:
            _add_review_reason(seq[i], "время нарушает хронологию страниц")
        return 0, [f"хронология по номерам страниц нарушена у {len(bad)} из {len(seq)} записей — "
                   f"возможно, страницы сняты в разное время; время не менялось, проверьте жёлтые строки"]
    fixed = 0
    for i in bad:
        p = seq[i]
        if p.get("time_locked"):
            continue
        prev_ok = next((vals[j] for j in range(i - 1, -1, -1) if j in keep), None)
        next_ok = next((vals[j] for j in range(i + 1, len(seq)) if j in keep), None)
        lo, hi, cur = prev_ok or "0000", next_ok or "9999", vals[i]
        best = None
        for pos, ch in enumerate(cur):
            if not ch.isdigit():
                continue
            for other in "0123456789":
                if other == ch:
                    continue
                cand = cur[:pos] + other + cur[pos + 1:]
                if not (lo <= cand <= hi):
                    continue
                try:
                    delta = abs((datetime.strptime(cand, DATE_FMT)
                                 - datetime.strptime(cur, DATE_FMT)).total_seconds())
                except ValueError:
                    continue
                rank = (frozenset((ch, other)) not in STAMP_CONFUSABLE, delta)
                if best is None or rank < best[0]:
                    best = (rank, cand)
        if best:
            new, how = best[1], "исправлено по хронологии страниц"
        else:
            new, how = (prev_ok or next_ok), "нарушает хронологию страниц, подставлено время соседней записи"
        if not new or new == cur:
            _add_review_reason(p, "время нарушает хронологию страниц")
            continue
        p["timestamp"] = QDateTime.fromString(new, QT_DATE_FMT)
        _add_review_reason(p, f"время {how}: {cur[11:] if cur[:10] == new[:10] else cur} → "
                              f"{new[11:] if cur[:10] == new[:10] else new}")
        fixed += 1
    return fixed, ([f"время исправлено по хронологии страниц у записей: {fixed} (жёлтые)"]
                   if fixed else [])



def refresh_flagged(entries: list, data: dict) -> None:
    """Пересчёт числа помеченных строк файла после автоисправлений."""
    for e in entries:
        d = data.get(e["path"])
        if d is not None:
            d["flagged"] = sum(1 for p in e["pulls"] if p.get("needs_review"))



def format_duration(seconds) -> str:
    """Длительность для таймеров: «01:20» или «1:05:09» (с часами)."""
    total = max(0, int(round(seconds)))
    h, rest = divmod(total, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
