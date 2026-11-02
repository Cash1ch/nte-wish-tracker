"""Уточнение столбцов времени, количества и даты; номер страницы «86/115»."""

import re
from collections import Counter

from ..compat import cv2, np, pytesseract
from ..catalog import QTY_OPTIONS
from .config import OCR_ENHANCE_ROWS, OCR_PAD, OCR_PAGE_SIZE
from .dates import DATE_RE, month_from_token
from .enhance import enhance_text_crop_variants
from .names import BONUS_MARK_RE, STRANA_SNA_RE
from .names_read import _header_icon_center, _line_has_name


# ---------------------------------------------------------------------------
# НОВОЕ: цифровой проход по времени и чтение номера страницы «86/115»
# ---------------------------------------------------------------------------
_TIME_TOKEN_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})")



PAGE_INDICATOR_RE = re.compile(r"(?<![\d/])(\d{1,3})\s*[/|\\]\s*(\d{1,3})(?![\d/])")



PAGE_INFO = {}                  # путь файла -> (страница, всего) или None (заполняет run_ocr_pipeline)



PAGE_ALTS = {}                  # путь файла -> [((страница, всего), голосов), ...] — запасные прочтения



OCR_TIME_PASS = True            # False — не перечитывать время отдельным цифровым проходом



def parse_page_indicator(text: str):
    """Номер страницы истории из текста вида «86/115»: (номер, всего) или None."""
    for m in PAGE_INDICATOR_RE.finditer(text or ""):
        n, total = int(m.group(1)), int(m.group(2))
        if 1 <= n <= total <= 999:
            return n, total
    return None



def parse_page_indicator_loose(text: str) -> list:
    """ИСПРАВЛЕНО: Tesseract с цифровым списком знаков часто читает «/» как «1» («77/90» ->
    «77190») — страница не находилась, и порядок всего пакета строился по времени. Здесь строка
    из одних цифр разбирается по местам, где «разделитель» мог быть прочитан как «1» (чаще всего)
    или «7»; варианты упорядочены: сначала «1», затем с равной длиной номера и «всего».
    Возвращает список [(номер, всего), ...] по убыванию правдоподобия."""
    digits = re.sub(r"\D", "", text or "")
    if "/" in (text or "") or not 3 <= len(digits) <= 7:
        return []
    out = []
    for i in range(1, len(digits) - 1):
        if digits[i] not in "17":
            continue
        a, b = digits[:i], digits[i + 1:]
        if not (1 <= len(a) <= 3 and 1 <= len(b) <= 3) or a[0] == "0" or b[0] == "0":
            continue
        n, total = int(a), int(b)
        if 1 <= n <= total <= 999:
            out.append(((digits[i] != "1", abs(len(a) - len(b)), i), (n, total)))
    out.sort()
    return [pg for _k, pg in out]



# Цифры, которые Tesseract путает в наклонном шрифте номера страницы («39/55» -> «59/55»)
_PAGE_DIGIT_SWAP = {"5": "3", "3": "5", "1": "7", "7": "1", "0": "8", "8": "0", "6": "8",
                    "9": "8", "2": "7"}



def parse_page_indicator_repairs(text: str) -> list:
    """Исправление ОШИБОЧНОГО прочтения номера страницы. Если прочитано невозможное «59/55»
    (номер больше общего числа страниц), одна цифра номера заменяется на похожую (5<->3, 1<->7,
    0<->8 …); у трёхзначного номера пробуется ещё и отбрасывание лишней цифры («357/55» ->
    «37/55»). Возвращает список правдоподобных (номер, всего), лучшие первыми; пусто, если
    прочтение и так корректно или ничего не подошло."""
    out = []
    for m in PAGE_INDICATOR_RE.finditer(text or ""):
        n_txt, total = m.group(1), int(m.group(2))
        n = int(n_txt)
        if 1 <= n <= total <= 999 or not 1 <= total <= 999:
            continue
        bases = [n_txt]
        if len(n_txt) == 3:
            bases += [n_txt[:i] + n_txt[i + 1:] for i in range(3)]
        for b in bases:
            for i, ch in enumerate(b):
                alt = _PAGE_DIGIT_SWAP.get(ch)
                if alt is None:
                    continue
                cand = b[:i] + alt + b[i + 1:]
                if cand[0] != "0" and 1 <= int(cand) <= total and (int(cand), total) not in out:
                    out.append((int(cand), total))
        for b in bases[1:]:
            if b[0] != "0" and 1 <= int(b) <= total and (int(b), total) not in out:
                out.append((int(b), total))
    return out[:4]



def _tess_digits(img, whitelist: str, psm: int = 7) -> str:
    """Чтение картинки Tesseract только с разрешёнными знаками (цифры, «:», «/»)."""
    cfg = (f"--psm {psm} --oem 1 -c user_defined_dpi=300 "
           f"-c tessedit_char_whitelist={whitelist}")
    try:
        return pytesseract.image_to_string(img, lang="eng", config=cfg).strip()
    except (pytesseract.TesseractError, pytesseract.TesseractNotFoundError, RuntimeError):
        return ""



def _refine_time_column(lines: list, src) -> list:
    """Отдельный цифровой проход по времени «ЧЧ:ММ:СС» каждой строки: узкая вырезка, несколько
    вариантов обработки, Tesseract только с цифрами. Голосование: значение первого прохода и
    все прочтения; побеждает большинство (при равенстве — первый проход). Если прочтения
    расходятся и большинства нет — строка помечается сомнительной (жёлтая, в редактор)."""
    if not OCR_TIME_PASS or cv2 is None or np is None or not lines:
        return lines
    rgb = np.array(src)
    height, width = rgb.shape[:2]
    budget = OCR_ENHANCE_ROWS
    for ln in lines:
        words = ln.get("words") or []
        idx = next((i for i in range(len(words) - 1, -1, -1)
                    if _TIME_TOKEN_RE.search(words[i]["text"])), None)
        if idx is None or budget <= 0:
            continue
        budget -= 1
        w = words[idx]
        first = _TIME_TOKEN_RE.search(w["text"]).group(0)
        x0, y0, x1, y1 = (int(v) for v in w["box"])
        padv = max(OCR_PAD, (y1 - y0) // 3)
        crop = rgb[max(0, y0 - padv):min(height, y1 + padv),
                   max(0, x0 - OCR_PAD):min(width, x1 + OCR_PAD)]
        if crop.shape[0] < 4 or crop.shape[1] < 8:
            continue
        try:
            variants = enhance_text_crop_variants(crop)
        except cv2.error:
            continue
        votes = [first]
        for v in variants:
            m = re.fullmatch(r"\D*(\d{2}:\d{2}:\d{2})\D*", _tess_digits(v, "0123456789:"))
            if m:
                votes.append(m.group(1))
        if len(votes) == 1:
            continue                                   # цифровой проход ничего не прочитал
        best, n = Counter(votes).most_common(1)[0]
        if n < 2:
            ln["time_doubt"] = True                    # все прочтения разные
            continue
        if best != first:
            pos = ln["text"].rfind(first)
            if pos >= 0:
                ln["text"] = ln["text"][:pos] + best + ln["text"][pos + len(first):]
            w["text"] = w["text"].replace(first, best)
            ln["time_fixed"] = (first, best)
    return lines



def _day_word_index(words: list):
    """Индекс слова-ДНЯ в строке таблицы («13» перед «май. 2026»): число 1–2 цифры (или
    буква-двойник цифры) + слово-месяц + слово с цифрами (год). None, если даты нет."""
    idx = None
    for i in range(len(words) - 1):
        mon = words[i + 1]["text"].strip(".,")
        if (re.fullmatch(r"\d{1,2}|[БбЗзlI|]", words[i]["text"].strip())
                and re.fullmatch(r"[^\W\d_]{2,9}", mon) and month_from_token(mon) is not None
                and i + 2 < len(words) and re.search(r"\d", words[i + 2]["text"])):
            idx = i
    return idx



def _refine_qty_column(lines: list, src) -> list:
    """Отдельный цифровой проход по КОЛИЧЕСТВУ (слово перед днём даты): «30» у потерянного
    фрагмента читалось как «50» (3<->5), из-за чего в статистику попадало неверное число.
    Узкая вырезка, несколько вариантов обработки, Tesseract только с цифрами; побеждает
    значение, прочитанное минимум дважды (первый проход тоже голосует). Количество «1»
    (дуги, персонажи, кубики) не перечитывается: его ошибка не возможна на практике."""
    if not OCR_TIME_PASS or cv2 is None or np is None or not lines:
        return lines
    rgb = np.array(src)
    height, width = rgb.shape[:2]
    budget = OCR_ENHANCE_ROWS
    for ln in lines:
        words = ln.get("words") or []
        if budget <= 0:
            break
        di = _day_word_index(words)
        if di is None or di < 1:
            continue
        w = words[di - 1]
        first = w["text"].strip()
        if not re.fullmatch(r"\d{1,3}", first):
            continue
        if first == "1" and not re.search(r"куб|шулер|тв[её]рд", ln["text"], re.I):
            continue                    # у дуг и персонажей количество всегда 1
        budget -= 1
        x0, y0, x1, y1 = (int(v) for v in w["box"])
        padv = max(6, (y1 - y0) // 2)
        crop = rgb[max(0, y0 - padv):min(height, y1 + padv),
                   max(0, x0 - OCR_PAD):min(width, x1 + OCR_PAD)]
        if crop.shape[0] < 4 or crop.shape[1] < 8:
            continue
        try:
            variants = enhance_text_crop_variants(crop)
        except cv2.error:
            continue
        low_text = ln["text"].lower()
        if re.search(r"куб|шулер|тв[её]рд", low_text):
            allowed = ("1", "5")                 # кубики: 1 или 5 шт
        elif re.search(r"искр|warp", low_text):
            allowed = None                       # Фрагмент искривления: любое число (4, 16, 30…)
        elif re.search(r"потер|фрагм|lost", low_text):
            allowed = ("30", "50")               # Потерянный фрагмент: 30 или 50 шт
        else:
            allowed = None
        votes = [first]
        for v in variants:
            m = re.fullmatch(r"\D*(\d{1,3})\D*", _tess_digits(v, "0123456789"))
            if m and m.group(1)[0] != "0":
                votes.append(m.group(1))
        if allowed:                              # невозможные для предмета значения не голосуют
            votes = [v for v in votes if v in allowed]
            if not votes:
                continue
        best, n = Counter(votes).most_common(1)[0]
        if allowed is None and re.search(r"искр|warp", low_text):
            known = QTY_OPTIONS["warp_fragment"]       # 30 / 16 / 4: «50» вместо «30» — ошибка 3<->5
            if first not in known and any(v in known for v in votes):
                best, n = Counter(v for v in votes if v in known).most_common(1)[0]
                n = max(n, 2)
        if best == first or (n < 2 and (not allowed or first in allowed)):
            continue
        pos = ln["text"].rfind(f"{first} {words[di]['text']}")
        if pos < 0:
            continue
        ln["text"] = ln["text"][:pos] + best + ln["text"][pos + len(first):]
        w["text"] = best
        ln["qty_fixed"] = (first, best)
    return lines



def _refine_date_column(lines: list, src) -> list:
    """Отдельный цифровой проход по ДНЮ месяца каждой строки («13 май. 2026 г.»): у Tesseract
    «13» часто превращается в «15», а «5» — в «Б». Узкая вырезка числа, несколько вариантов
    обработки, Tesseract только с цифрами; побеждает значение, которое прочитали минимум два
    раза (первый проход тоже голосует, если это число). Исправленная строка помечается
    ln["day_fixed"]; нет большинства — строка остаётся как есть."""
    if not OCR_TIME_PASS or cv2 is None or np is None or not lines:
        return lines
    rgb = np.array(src)
    height, width = rgb.shape[:2]
    budget = OCR_ENHANCE_ROWS
    for ln in lines:
        words = ln.get("words") or []
        if budget <= 0:
            break
        idx = _day_word_index(words)
        if idx is None:
            continue
        budget -= 1
        w = words[idx]
        first = w["text"].strip()
        x0, y0, x1, y1 = (int(v) for v in w["box"])
        padv = max(6, (y1 - y0) // 2)
        crop = rgb[max(0, y0 - padv):min(height, y1 + padv),
                   max(0, x0 - OCR_PAD):min(width, x1 + OCR_PAD)]
        if crop.shape[0] < 4 or crop.shape[1] < 8:
            continue
        try:
            variants = enhance_text_crop_variants(crop)
        except cv2.error:
            continue
        votes = [first] if first.isdigit() else []
        for v in variants:
            m = re.fullmatch(r"\D*(\d{1,2})\D*", _tess_digits(v, "0123456789"))
            if m and 1 <= int(m.group(1)) <= 31:
                votes.append(str(int(m.group(1))))
        if not votes:
            continue
        best, n = Counter(votes).most_common(1)[0]
        if n < 2 or best == first:
            continue
        mon_text = words[idx + 1]["text"]
        pos = ln["text"].rfind(f"{first} {mon_text}")
        if pos < 0:
            continue
        ln["text"] = ln["text"][:pos] + best + ln["text"][pos + len(first):]
        w["text"] = best
        ln["day_fixed"] = (first, best)
    return lines



def _find_page_in_lines(raw_lines: list, table_lines: list):
    """Номер страницы среди строк первого прохода: нижняя строка без даты, ниже таблицы."""
    anchors = [ln for ln in table_lines if DATE_RE.search(ln["text"])]
    floor = max((ln["box"][3] for ln in anchors), default=-1)
    best = None
    for ln in raw_lines:
        if DATE_RE.search(ln["text"]) or ln["box"][1] < floor - 2:
            continue
        found = parse_page_indicator(ln["text"])
        if found:
            best = found
            break
    return best



def _page_bar_crops(rgb, top: int, med_h: int) -> list:
    """Кандидаты вырезок для номера страницы. Номер стоит в центре окна на тёмной плашке между
    кнопками «Назад» и «Далее»: ищется ближайшая к таблице тёмная полоса в центральной части
    снимка (кнопки по бокам в неё не попадают). Запасной вариант — центральная полоса под
    таблицей. Возвращает список картинок RGB."""
    h, w = rgb.shape[:2]
    cx0, cx1 = int(w * 0.44), int(w * 0.56)
    top = max(0, min(h - 1, top))
    out = []
    gray = cv2.cvtColor(rgb[top:, cx0:cx1], cv2.COLOR_RGB2GRAY)
    dark = gray.mean(axis=1) < 90
    y, n = 0, len(dark)
    while y < n:
        if not dark[y]:
            y += 1
            continue
        k = y
        while k < n and dark[k]:
            k += 1
        if 0.4 * med_h <= k - y <= 3 * med_h:
            pad = max(2, (k - y) // 8)
            out.append(rgb[top + max(0, y - pad):min(h, top + k + pad), cx0:cx1])
            break
        y = k
    out.append(rgb[top:min(h, top + int(7 * med_h)), cx0:cx1])
    return out



def _read_page_below(src, table_lines: list):
    """Запасное чтение «N/M», когда общий проход его не увидел (белые цифры на чёрной плашке):
    вырезка плашки под таблицей, увеличение ×2/×3/×4, серый и бинарный вариант, Tesseract только
    с цифрами и «/». Голосование: побеждает самое частое прочтение. Возвращает
    (страница или None, список [(страница, голосов), ...] по убыванию голосов)."""
    if cv2 is None or np is None:
        return None, []
    anchors = [ln for ln in table_lines if DATE_RE.search(ln["text"])]
    if not anchors:
        return None, []
    heights = sorted(ln["box"][3] - ln["box"][1] for ln in anchors)
    med_h = max(8, heights[len(heights) // 2])
    rgb = np.array(src)
    votes = Counter()
    for crop in _page_bar_crops(rgb, int(max(ln["box"][3] for ln in anchors)), med_h):
        if crop.shape[0] < 8 or crop.shape[1] < 16:
            continue
        base = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        for fx in (2, 3, 4):
            gray = cv2.resize(base, None, fx=fx, fy=fx, interpolation=cv2.INTER_CUBIC)
            if float(gray.mean()) < 110:                  # светлые цифры на тёмном -> наоборот
                gray = cv2.bitwise_not(gray)
            gray = cv2.copyMakeBorder(gray, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
            imgs = [gray]
            try:
                imgs.append(cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1])
            except cv2.error:
                pass
            for img in imgs:
                raw = _tess_digits(img, "0123456789/", 7)
                found = parse_page_indicator(raw)
                if found:
                    votes[found] += 1
                else:
                    fixed = parse_page_indicator_repairs(raw)
                    if fixed:                  # «59/55» -> «39/55»: невозможный номер
                        for k, cand in enumerate(fixed):
                            votes[cand] += 0.9 if k == 0 else 0.1
                        continue
                    for k, cand in enumerate(parse_page_indicator_loose(raw)[:3]):
                        votes[cand] += 1 if k == 0 else 0.1
        if votes:
            break
    alts = votes.most_common()
    return (alts[0][0] if alts else None), alts



def _fill_row_gaps(lines: list) -> list:
    """ИСПРАВЛЕНО (счётчик гаранта): строку, которую OCR потерял, нельзя достраивать в конец
    страницы — тогда сдвигается порядок всех записей ниже/выше неё (персонаж на 2-й позиции
    сверху становился 5-м вместо 4-го). Здесь по геометрии находятся пропуски между строками и
    над первой строкой (под заголовком таблицы) и на их место вставляются строки-«пустышки»
    с общим временем страницы: дальше разбор видит их как строки без названия на своём месте
    и помечает для проверки. Вставляется не больше, чем нужно до OCR_PAGE_SIZE строк."""
    dated = [ln for ln in lines if DATE_RE.search(ln["text"])]
    if len(dated) < 3:
        return lines
    last_y = max(ln["box"][3] for ln in dated)
    first_y = min(ln["box"][1] for ln in dated)
    head = [ln for ln in lines if ln["box"][3] <= first_y + 2 and not DATE_RE.search(ln["text"])]
    header = max(head, key=lambda ln: ln["box"][3]) if head else None
    rows = sorted((ln for ln in lines if ln["box"][1] >= first_y - 2 and ln["box"][3] <= last_y + 2),
                  key=lambda ln: ln["box"][1])
    if len(rows) < 3 or len(rows) >= OCR_PAGE_SIZE:
        return lines
    mid = [(ln["box"][1] + ln["box"][3]) / 2 for ln in rows]
    diffs = sorted(b - a for a, b in zip(mid, mid[1:]) if b - a > 4)
    if len(diffs) < 2:
        return lines
    near = [d for d in diffs if d <= diffs[0] * 1.35]
    pitch = near[len(near) // 2]
    stamps = Counter(m.group() for ln in dated for m in [DATE_RE.search(ln["text"])])
    stamp = stamps.most_common(1)[0][0]
    x0 = min(ln["box"][0] for ln in rows)
    x1 = max(ln["box"][2] for ln in rows)
    height = sum(ln["box"][3] - ln["box"][1] for ln in rows) / len(rows)
    room = OCR_PAGE_SIZE - len(rows)
    new = []

    def blank(center):
        return {"text": stamp, "box": (x0, int(center - height / 2), x1, int(center + height / 2)),
                "words": [], "name_left": x0, "synthetic": True}

    if header is not None:
        top_gap = mid[0] - (header["box"][1] + header["box"][3]) / 2
        k = min(room, max(0, round(top_gap / pitch - 1.2))) if top_gap >= 1.8 * pitch else 0
        for i in range(k, 0, -1):
            new.append(blank(mid[0] - i * pitch))
        room -= k
    for a, b in zip(mid, mid[1:]):
        if room > 0 and b - a >= 1.7 * pitch:
            k = min(room, round((b - a) / pitch) - 1)
            new += [blank(a + i * pitch) for i in range(1, k + 1)]
            room -= k
    if not new:
        return lines
    return sorted(lines + new, key=lambda ln: (ln["box"][1], ln["box"][0]))



def _flag_rows_without_icon(lines: list, src) -> list:
    """ИСПРАВЛЕНО (счётчик): в таблице бросков у каждой ОБЫЧНОЙ строки в левом столбце стоит значок
    кубика, а у «Подарок за очки» / «Страна сна» вместо него — подпись. Подпись OCR иногда не читает
    («Страна с нева»), и тогда бонусная строка считалась обычной круткой и сдвигала гарант на 1.
    Строка без значка кубика (при заголовке «Результат броска» и значках у остальных строк) без
    прочитанной подписи получает «Подарок за очки»: бонус и «Страна сна» одинаково не меняют счётчик."""
    if cv2 is None or np is None or len(lines) < 3:
        return lines
    cx = _header_icon_center(lines)
    rows = [ln for ln in lines if not ln.get("synthetic") and DATE_RE.search(ln.get("text") or "")]
    if cx is None or len(rows) < 3:
        return lines
    mids = sorted((ln["box"][1] + ln["box"][3]) / 2.0 for ln in rows)
    diffs = sorted(b - a for a, b in zip(mids, mids[1:]) if b - a > 8)
    if not diffs:
        return lines
    pitch = diffs[len(diffs) // 2]
    rgb = np.array(src).astype(int)
    height, width = rgb.shape[:2]
    half = 0.30 * pitch
    flags = {}
    for ln in rows:
        yc = (ln["box"][1] + ln["box"][3]) / 2.0
        y0, y1 = int(max(0, yc - half)), int(min(height, yc + half))
        x0, x1 = int(max(0, cx - half)), int(min(width, cx + half))
        if y1 - y0 < 4 or x1 - x0 < 4:
            continue
        reg = rgb[y0:y1, x0:x1]
        gray = ((np.abs(reg[:, :, 0] - reg[:, :, 1]) < 14) & (np.abs(reg[:, :, 1] - reg[:, :, 2]) < 14)
                & (reg[:, :, 0] > 55) & (reg[:, :, 0] < 115))
        flags[id(ln)] = float(gray.mean()) >= 0.45          # есть значок кубика
    if len(flags) < 3 or sum(flags.values()) < 0.6 * len(flags) or all(flags.values()):
        return lines
    out = []
    for ln in lines:
        if flags.get(id(ln)) is False and _line_has_name(ln):
            t = ln["text"]
            if not (BONUS_MARK_RE.search(t) or STRANA_SNA_RE.search(t)):
                # «Фрагмент искривления» без значка кубика — награда «Страна сна», не бонус
                mark = "Страна сна" if re.search(r"искр|warp", t, re.I) else "Подарок за очки"
                ln = dict(ln, text=f"{mark} {t}", no_icon=True)
        out.append(ln)
    return out
