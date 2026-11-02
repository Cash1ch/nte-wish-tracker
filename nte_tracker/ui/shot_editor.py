"""Правка строк после сканирования и список «Распознанные варианты»."""

import os
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, QDateTime, QEvent, QSize, Qt, QUrl
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateTimeEdit, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..catalog import (
    BONUS_TYPE_PREFIX, loot_aliases, loot_rarity, LOOT_TYPES, pick_item_qty, rank_letter, REWARD_KINDS,
)
from ..config import DATE_FMT, QT_DATE_FMT
from ..errors import blocked
from ..icons import make_pixmap
from ..labels import default_reward_name
from ..ocr.names import (
    clean_character_name, clean_name, format_duga_name, format_outfit_name, strip_item_prefix, strip_labels,
)
from ..ocr.pipeline import parse_screenshot_text_ex
from ..paths import app_dir
from .widgets import make_button, make_label, SmoothIconLabel


# ---------------------------------------------------------------------------
# НОВОЕ: правки строк после сканирования (общие для «Скриншот оптом» и «Скриншоты разом»)
# ---------------------------------------------------------------------------
def new_file_data() -> dict:
    """Данные одного файла пакета: текст OCR, ранги, уверенность, статус и правки строк."""
    return {"text": "", "ranks": [], "glob": None, "confs": None, "page": None, "page_alts": [], "status": "Ожидает",
            "count": None, "chrono": None, "done": False,
            "edits": {}, "reviewed": set(),            # правки и просмотренные строки (по номеру строки)
            "pulls_all": [], "skipped_rest": [], "flagged": 0}



def review_total(data: dict) -> int:
    """Сколько строк всех файлов вкладки ждут проверки."""
    return sum(review_count(d) for d in data.values())



def review_count(d: dict) -> int:
    """Сколько строк файла ещё ждут проверки (помеченные + нераспознанные)."""
    return int(d.get("flagged", 0)) + len(d.get("skipped_rest", ()))



def pull_from_edit(base: dict, e: dict) -> dict:
    """Запись по правке из редактора: тип, название, количество, ранг, время. base — прежняя
    запись (или заготовка для нераспознанной строки). Место строки в раскладке (line) не
    меняется, поэтому порядок выпадений сохраняется."""
    key = e["loot"]
    info = LOOT_TYPES[key]
    mode = info["mode"]
    qty = e.get("qty") or None
    rank = e.get("rank") or base.get("rarity") or 3
    if mode == "cashback":
        rarity, src = loot_rarity(info), "тип предмета"
    elif mode == "reward":
        fixed = loot_rarity(info)
        rarity, src = rank, ("тип предмета" if rank == fixed else "цвет")
    else:
        rarity, src = rank, "правка"
    name = (e.get("name") or "").strip()
    if info.get("hide_name") or not name:
        name = ""
    elif key == "arc":
        name = format_duga_name(name)
    elif key == "character":
        name = clean_character_name(name)
    elif key == "outfit":
        name = format_outfit_name(name)              # «Костюм - Название»
    else:
        name = strip_item_prefix(key, strip_labels(name, ("rank",)))
    is_bonus = bool(base.get("is_bonus")) and mode != "cashback"
    type_text = (REWARD_KINDS[info["kind"]] if mode == "reward" and info.get("kind") in REWARD_KINDS
                 else info["label"])
    if is_bonus:
        type_text = f"{BONUS_TYPE_PREFIX} - {type_text}"
    when = QDateTime.fromString(e["ts"], QT_DATE_FMT)
    out = dict(base)
    out.update(
        loot=key, name=name, rarity=rarity, rarity_src=src, qty=qty, amount=qty,
        rarity_type=info["label"] if mode != "wish" else rank_letter(rarity),
        item_label=info["label"] if mode == "reward" else "",
        item_type=("Предмет" if mode == "reward" else "Кешбэк" if mode == "cashback"
                   else info["label"]),
        display_name=(default_reward_name(info["kind"], qty or info.get("detail", ""))
                      if mode == "reward" and not name else name),
        type_text=type_text, is_bonus=is_bonus, timestamp=when, has_time=when.isValid(),
        known=True, doubtful=False, weak=[], needs_review=False, edited=True)
    return out



def merge_row_edits(pulls: list, skipped_rows: list, d: dict):
    """Накладывает правки редактора на результат разбора файла. Возвращает (записи в порядке
    раскладки скриншота, нераспознанные строки без правок, сколько строк превращено в записи).
    Порядок — строго по номеру строки текста, поэтому правка не может переставить строки."""
    edits, reviewed = d.get("edits") or {}, d.get("reviewed") or set()
    out, rest, converted = [], [], 0
    for p in pulls:
        line = p.get("line")
        e = edits.get(line)
        if e is not None:
            if e.get("include", True):
                out.append(pull_from_edit(p, e))
            continue                                   # include=False — строка убрана пользователем
        if line in reviewed:
            p = dict(p, needs_review=False, weak=[])   # просмотрена — подсветка снимается
        out.append(p)
    for r in skipped_rows:
        e = edits.get(r["line"])
        if e is not None and e.get("include") and e.get("loot"):
            base = {"is_bonus": r.get("bonus", False), "raw_date": r.get("raw_date", ""),
                    "body_raw": r["body"], "conf": r.get("conf"), "line": r["line"]}
            out.append(pull_from_edit(base, e))
            converted += 1
        elif r["line"] not in reviewed:
            rest.append(r)
    out.sort(key=lambda q: q.get("line", 0))
    return out, rest, converted



def parse_file_with_edits(d: dict, known: dict, default_loot: str):
    """Разбор одного файла + правки редактора. Сохраняет в d итоговые записи (pulls_all),
    оставшиеся нераспознанные строки (skipped_rest) и число помеченных (flagged).
    Возвращает (записи, число пропущенных строк)."""
    pulls, skipped, rows = parse_screenshot_text_ex(d["text"], known, d["ranks"], d["glob"],
                                                    default_loot, d.get("confs"))
    pulls, rest, converted = merge_row_edits(pulls, rows, d)
    d["pulls_all"], d["skipped_rest"] = pulls, rest
    d["flagged"] = sum(1 for p in pulls if p.get("needs_review"))
    return pulls, max(0, skipped - converted)



def QDateTime_le(a, b) -> bool:
    """ИСПРАВЛЕНО: a <= b для QDateTime с точностью до секунды (равное время — допустимо)."""
    fa, fb = (_qdt_seconds(a).toString(QT_DATE_FMT), _qdt_seconds(b).toString(QT_DATE_FMT))
    return datetime.strptime(fa, DATE_FMT) <= datetime.strptime(fb, DATE_FMT)



def _qdt_seconds(value):
    """ИСПРАВЛЕНО: QDateTime без миллисекунд (формат DATE_FMT), чтобы время записей одной крутки
    совпадало побайтно и границы поля времени не отсекали равные секунды."""
    try:
        out = QDateTime.fromString(value.toString(QT_DATE_FMT), QT_DATE_FMT)
        return out if out.isValid() else value
    except AttributeError:
        return value



def collect_editor_entries(paths: list, data: dict) -> list:
    """Строки для «Редактора нераспознанных строк»: помеченные записи и нераспознанные строки
    в порядке файлов и раскладки. Для каждой считаются границы времени: не новее ближайшей
    записи выше (она выпала позже) и не старше ближайшей записи ниже (выпала раньше)."""
    entries = []
    for path in paths:
        d = data[path]
        pulls = d.get("pulls_all", [])
        timed = sorted(((q["line"], q["timestamp"]) for q in pulls
                        if q.get("has_time") and "line" in q), key=lambda t: t[0])
        todo = [("flag", q) for q in pulls if q.get("needs_review")]
        todo += [("skipped", r) for r in d.get("skipped_rest", ())]
        todo.sort(key=lambda t: t[1]["line"])
        for kind, item in todo:
            line = item["line"]
            above = [t for ln, t in timed if ln < line]     # выше на скриншоте — выпали позже
            below = [t for ln, t in timed if ln > line]     # ниже — выпали раньше
            # ИСПРАВЛЕНО: границы — время с точностью до секунды (без миллисекунд)
            above = [_qdt_seconds(t) for t in above]
            below = [_qdt_seconds(t) for t in below]
            entries.append({
                "path": path, "file": Path(path).name, "line": line, "kind": kind,
                "item": item, "hi": above[-1] if above else None,
                "lo": below[0] if below else None,
                "timeline": timed,
                "number": 1 + sum(1 for q in pulls if q.get("line", -1) < line)})
    return entries



class RowEditorDialog(QDialog):
    """НОВОЕ: «Редактор нераспознанных строк» — модальное окно проверки после сканирования.
    По каждой помеченной (низкая уверенность OCR / нечёткое совпадение) или нераспознанной
    строке можно исправить тип, название, количество (30 / 50 у фрагментов), ранг S / A / B и
    время. Порядок строк фиксирован (по файлам и раскладке скриншота) — переставлять их нельзя;
    время ограничено соседними записями, а при «Применить» последовательность выпадений
    проверяется ещё раз. После accept() результат — в self.results."""

    HEADERS = ["Файл", "№", "Текст OCR", "Уверенность", "Тип", "Название", "Кол-во", "Ранг",
               "Время", "Добавить"]
    WARN_BG = QColor(255, 214, 79, 80)        # мягкий жёлтый фон помеченных строк
    LINK_COLOR = QColor("#4da3ff")            # синий цвет кликабельного имени файла

    def __init__(self, entries: list, fallback_dt: QDateTime, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактор нераспознанных строк")
        self.setModal(True)
        self.resize(1240, 640)
        self.entries, self.fallback_dt, self.results = entries, fallback_dt, []
        self._w, self._initial = [], []
        lay = QVBoxLayout(self)
        lay.addWidget(make_label(
            "Здесь строки с низкой уверенностью OCR (< 70%), нечётким совпадением и нераспознанные "
            "строки. Исправьте тип, название, количество, ранг и время. Порядок строк менять "
            "нельзя: время каждой строки ограничено соседними записями на скриншоте (выше — "
            "новее, ниже — старше), чтобы последовательность выпадений сохранилась. "
            "Нераспознанные строки добавляются, только если выбран тип и стоит флажок «Добавить».",
            "hint", wrap=True))
        self.table = QTableWidget(len(entries), len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)
        # клик по имени файла (колонка 0) открывает скриншот в программе просмотра по умолчанию
        self._hover_item = None
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.viewport().installEventFilter(self)
        self.table.cellClicked.connect(self._on_cell_clicked)
        for r, e in enumerate(entries):
            self._build_row(r, e)
        self.status = make_label("", "hint", wrap=True)
        lay.addWidget(self.status)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(make_button("Пропустить", self.reject))
        btns.addWidget(make_button("Применить", self._try_accept, "primary"))
        lay.addLayout(btns)

    # ---- построение строки ----
    def _build_row(self, r: int, e: dict):
        item, skipped = e["item"], e["kind"] == "skipped"
        conf = item.get("conf")
        reasons = "; ".join(item.get("weak") or []) or ("нераспознанная строка" if skipped else "")
        text = item.get("body_raw") or item.get("body") or ""
        cells = (e["file"], str(e["number"]), text, "—" if conf is None else f"{conf:.0f}%")
        for c, val in enumerate(cells):
            it = QTableWidgetItem(val)
            it.setBackground(self.WARN_BG)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            it.setToolTip(reasons or val)
            if c in (1, 3):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if c == 0:
                # имя файла выглядит как ссылка: синий цвет, подсказка, данные для открытия
                it.setForeground(QBrush(self.LINK_COLOR))
                it.setToolTip("Кликните, чтобы открыть скриншот")
                it.setData(Qt.ItemDataRole.UserRole, e["path"])
            self.table.setItem(r, c, it)

        typ = QComboBox()
        typ.addItem("— выберите тип —", "")
        for key, info in LOOT_TYPES.items():
            typ.addItem(info["label"], key)
        name = QLineEdit()
        qty = QComboBox()
        rank = QComboBox()
        for letter, num in (("S", 5), ("A", 4), ("B", 3)):
            rank.addItem(letter, num)
        dt = QDateTimeEdit()
        dt.setDisplayFormat(QT_DATE_FMT)
        dt.setCalendarPopup(True)
        if (e["hi"] is not None and e["lo"] is not None
                and QDateTime_le(e["lo"], e["hi"])):          # lo <= hi (равное время допустимо)
            dt.setDateTimeRange(e["lo"], e["hi"])
        elif e["hi"] is not None and e["lo"] is None:
            dt.setMaximumDateTime(e["hi"])
        elif e["lo"] is not None and e["hi"] is None:
            dt.setMinimumDateTime(e["lo"])
        inc = QCheckBox()

        if skipped:
            typ.setCurrentIndex(0)
            name.setText(clean_name(item["body"]))
            rank_val = item.get("color") if item.get("color") in (3, 4, 5) else 3
            when = (QDateTime.fromString(item["stamp"], QT_DATE_FMT) if item.get("stamp")
                    else None)
            qty_val = item.get("qty") or ""
            inc.setChecked(False)           # нераспознанная строка: добавляется только по решению пользователя
        else:
            typ.setCurrentIndex(max(0, typ.findData(item["loot"])))
            name.setText(item.get("name") or "")
            rank_val = item.get("rarity") or 3
            when = item["timestamp"] if item.get("has_time") else None
            qty_val = item.get("qty") or item.get("amount") or ""
            inc.setChecked(True)
        rank.setCurrentIndex(max(0, rank.findData(rank_val)))
        if when is None or not when.isValid():
            when = e["lo"] or e["hi"] or _qdt_seconds(self.fallback_dt)  # время соседа — безопасно
        dt.setDateTime(when)

        w = {"type": typ, "name": name, "qty": qty, "rank": rank, "dt": dt, "inc": inc}
        self._w.append(w)
        self._refresh_type(r, str(qty_val or ""), user=False)
        for c, widget in ((4, typ), (5, name), (6, qty), (7, rank), (8, dt), (9, inc)):
            self.table.setCellWidget(r, c, widget)
        typ.currentIndexChanged.connect(lambda _i, row=r: self._refresh_type(row, "", user=True))
        self._initial.append(self._values(r))

    # ---- открытие скриншота по клику на имя файла ----
    def _resolve_shot_path(self, raw) -> Path | None:
        """Строит полный путь к скриншоту: абсолютный путь берётся как есть, относительный
        ищется от текущей папки, от папки программы и от папки, где лежит main.py."""
        if not raw:
            return None
        p = Path(str(raw)).expanduser()
        candidates = [p] if p.is_absolute() else [
            Path.cwd() / p, Path(sys.argv[0]).resolve().parent / p, app_dir() / p]
        for cand in candidates:
            try:
                if cand.is_file():
                    return cand.resolve()
            except OSError:
                continue
        return None

    def _open_screenshot(self, raw_path) -> bool:
        """Открывает файл в программе просмотра изображений по умолчанию."""
        full = self._resolve_shot_path(raw_path)
        if full is None:
            self.status.setText(f"Файл скриншота не найден: {raw_path}")
            return False
        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(full))):
            return True
        if sys.platform == "win32":                 # запасной вариант для Windows
            try:
                os.startfile(str(full))               # type: ignore[attr-defined]
                return True
            except OSError:
                pass
        self.status.setText(f"Не удалось открыть скриншот: {full}")
        return False

    def _on_cell_clicked(self, row: int, col: int):
        if col != 0:
            return
        it = self.table.item(row, 0)
        if it is not None:
            self._open_screenshot(it.data(Qt.ItemDataRole.UserRole) or self.entries[row]["path"])

    def _set_link_hover(self, item, on: bool):
        """Подчёркивает имя файла при наведении мыши."""
        if item is None:
            return
        f = item.font()
        f.setUnderline(on)
        item.setFont(f)

    def eventFilter(self, obj, event):
        """Курсор-«рука» и подчёркивание имени файла при наведении на колонку «Файл»."""
        if obj is self.table.viewport():
            et = event.type()
            if et == QEvent.Type.MouseMove:
                it = self.table.itemAt(event.position().toPoint())
                it = it if (it is not None and it.column() == 0) else None
                if it is not self._hover_item:
                    self._set_link_hover(self._hover_item, False)
                    self._set_link_hover(it, True)
                    self._hover_item = it
                self.table.viewport().setCursor(
                    Qt.CursorShape.PointingHandCursor if it is not None
                    else Qt.CursorShape.ArrowCursor)
            elif et == QEvent.Type.Leave:
                self._set_link_hover(self._hover_item, False)
                self._hover_item = None
                self.table.viewport().unsetCursor()
        return super().eventFilter(obj, event)

    def _refresh_type(self, r: int, qty_hint: str, user: bool):
        """Включает/выключает поля под выбранный тип (название, количество, ранг)."""
        w = self._w[r]
        key = w["type"].currentData()
        info = LOOT_TYPES.get(key)
        w["name"].setEnabled(bool(info) and not info.get("hide_name"))
        if info and info.get("hide_name"):
            w["name"].clear()
        w["qty"].clear()
        options = tuple(info.get("qty", ())) if info else ()
        for q in options:
            w["qty"].addItem(f"{q} шт", q)
        if (options and info.get("qty_free") and str(qty_hint or "").isdigit()
                and str(qty_hint) not in options):
            w["qty"].addItem(f"{qty_hint} шт", str(qty_hint))   # значение с экрана вне списка
        w["qty"].setEnabled(bool(options))
        if options:
            w["qty"].setCurrentIndex(max(0, w["qty"].findData(qty_hint)))
        w["rank"].setEnabled(bool(info) and info["mode"] != "cashback")
        if user and info and info["mode"] != "wish":      # сменили тип — ранг по виду предмета
            fixed = loot_rarity(info)
            if fixed:
                w["rank"].setCurrentIndex(max(0, w["rank"].findData(fixed)))
        if user and key:
            w["inc"].setChecked(True)      # выбрал тип — значит, строку надо добавить

    def _values(self, r: int) -> tuple:
        w = self._w[r]
        return (w["type"].currentData(), w["name"].text().strip(), w["qty"].currentData() or "",
                w["rank"].currentData(), w["dt"].dateTime().toString(QT_DATE_FMT))

    # ---- проверка и результат ----
    def _try_accept(self):
        """«Применить»: проверяет тип и порядок выпадений; при ошибке окно остаётся открытым."""
        by_file = {}
        for r, e in enumerate(self.entries):
            w = self._w[r]
            if w["inc"].isChecked() and not w["type"].currentData():
                self.status.setText(f"Строка {r + 1} ({e['file']}): не выбран тип — выберите тип "
                                    f"или снимите флажок «Добавить».")
                self.table.scrollToItem(self.table.item(r, 0))
                return
            by_file.setdefault(e["path"], []).append((r, e))
        for path, items in by_file.items():
            problem = self._order_problem(items)
            if problem:
                self.status.setText(problem)
                return
        self.results = []
        for r, e in enumerate(self.entries):
            w, vals = self._w[r], self._values(r)
            include = w["inc"].isChecked()
            self.results.append({
                "path": e["path"], "line": e["line"], "kind": e["kind"], "include": include,
                "changed": vals != self._initial[r],
                "edit": {"include": include, "loot": vals[0], "name": vals[1], "qty": vals[2],
                         "rank": vals[3], "ts": vals[4]}})
        self.accept()

    @staticmethod
    def _as_datetime(value):
        """ИСПРАВЛЕНО: время как datetime (а не строка и не QDateTime): без миллисекунд и пояса,
        чтобы одинаковое время записей одной крутки сравнивалось как РАВНОЕ. None — если время
        не читается."""
        try:
            text = value.toString(QT_DATE_FMT) if hasattr(value, "toString") else str(value)
            return datetime.strptime(text.strip(), DATE_FMT)
        except (ValueError, AttributeError, TypeError):
            return None

    def _order_problem(self, items: list):
        """Последовательность выпадений одного скриншота: сверху вниз время не должно расти
        (верхняя запись новее). Проверяются пары, где участвует строка редактора.

        ИСПРАВЛЕНО: одинаковое время у соседних записей (мультикрутка: 5 предметов в
        2026-10-03 18:35:47) — НЕ ошибка. Время сравнивается как datetime с точностью до секунды
        (раньше сравнивались QDateTime с миллисекундами из запасного времени формы, и равные
        секунды считались «старше / новее»), нарушением считается только строгое t1 < t2. Если
        неизменённые соседи строки уже стоят в обратном порядке (граница невыполнима), строка
        не проверяется — пользователя нельзя блокировать из-за чужого порядка."""
        edited = {e["line"]: self._w[r]["dt"].dateTime() for r, e in items
                  if self._w[r]["inc"].isChecked()}
        dropped = {e["line"] for r, e in items if not self._w[r]["inc"].isChecked()}
        fixed = [(ln, self._as_datetime(t)) for ln, t in items[0][1]["timeline"]
                 if ln not in edited and ln not in dropped]
        fixed = [(ln, t) for ln, t in fixed if t is not None]
        seq = [(ln, t, False) for ln, t in fixed]
        seq += [(ln, self._as_datetime(t), True) for ln, t in edited.items()]
        seq = [x for x in seq if x[1] is not None]
        seq.sort(key=lambda t: (t[0], t[2]))

        def unsatisfiable(line: int) -> bool:
            above = [t for ln, t in fixed if ln < line]
            below = [t for ln, t in fixed if ln > line]
            return bool(above and below and below[0] > above[-1])   # границы уже перевёрнуты

        for (l1, t1, e1), (l2, t2, e2) in zip(seq, seq[1:]):
            if not (e1 or e2) or not t1 < t2:           # равное время допустимо
                continue
            if (e1 and unsatisfiable(l1)) or (e2 and unsatisfiable(l2)):
                continue
            return (f"{items[0][1]['file']}: нарушен порядок выпадений — запись выше "
                    f"({t1.strftime(DATE_FMT)}) не может быть старше записи ниже "
                    f"({t2.strftime(DATE_FMT)}). Исправьте время.")
        return ""



ShotRow_WARN_BG = QColor(255, 214, 79, 80)      # мягкий жёлтый фон «проверить»



class ShotRow(QWidget):
    """НОВОЕ: строка списка «Распознанные варианты» (вкладка «Скриншот»):
    флажок + иконка + описание + РЕДАКТИРУЕМЫЕ дата и время (QDateTimeEdit).

    Поле даты сразу содержит время, найденное на скриншоте («30 апр. 2026 г. 12:03:36» ->
    2026-04-30 12:03:36). Если на снимке времени нет, в поле стоит запасное значение (время
    формы «Ручная»), а само поле подсвечено оранжевым — это сигнал проверить его вручную.
    Именно значение этого поля записывается в базу как время записи (pulled_at /
    obtained_at); datetime.now() для записей со скриншота не используется."""

    time_edited = pyqtSignal()  # пользователь изменил дату/время

    def __init__(self, text: str, pixmap: QPixmap, when: QDateTime, found: bool,
                 checked: bool, raw_date: str = ""):
        super().__init__()
        self.time_confirmed = found  # True: время взято со снимка или исправлено вручную
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(8)

        self.check = QCheckBox()
        self.check.setChecked(checked)
        icon = SmoothIconLabel()
        icon.setFixedSize(40, 40)
        icon.setPixmap(pixmap)
        self.text_lbl = QLabel(text)
        self.text_lbl.setWordWrap(True)
        # клики по описанию «проходят насквозь» — строка выделяется, работает двойной щелчок
        self.text_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.dt = QDateTimeEdit(when if when.isValid() else QDateTime.currentDateTime())
        self.dt.setDisplayFormat(QT_DATE_FMT)
        self.dt.setCalendarPopup(True)
        self.dt.setFixedWidth(190)
        self._mark_found(found, raw_date)
        self.dt.dateTimeChanged.connect(self._on_changed)

        lay.addWidget(self.check)
        lay.addWidget(icon)
        lay.addWidget(self.text_lbl, 1)
        lay.addWidget(self.dt)

    def set_review(self, reason: str):
        """НОВОЕ: мягкая ЖЁЛТАЯ подсветка всей строки — запись надо проверить глазами (низкая
        уверенность OCR / нечёткое совпадение). Полупрозрачная заливка видна и на тёмной теме."""
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("shotRowReview")
        self.setStyleSheet("#shotRowReview { background-color: rgba(255, 214, 79, 80);"
                           " border-left: 4px solid #f2c200; border-radius: 4px; }")
        self.setToolTip(f"Проверьте строку: {reason}" if reason else "Проверьте строку")

    def _mark_found(self, found: bool, raw_date: str = ""):
        """Подсветка поля: оранжевая рамка, пока время не найдено и не подтверждено."""
        if found:
            self.dt.setStyleSheet("")
            self.dt.setToolTip(f"Время со скриншота: {raw_date}" if raw_date
                               else "Время записи (можно изменить)")
        else:
            self.dt.setStyleSheet("QDateTimeEdit { border: 1px solid #ff9800; }")
            self.dt.setToolTip("Время на скриншоте не найдено — подставлено время формы "
                               "«Ручная». Проверьте и при необходимости исправьте.")

    def _on_changed(self, *_):
        self.time_confirmed = True      # пользователь поправил — считаем время подтверждённым
        self._mark_found(True)
        self.time_edited.emit()

    def datetime(self) -> QDateTime:
        return self.dt.dateTime()

    def stamp(self) -> str:
        """Время записи в формате базы «ГГГГ-ММ-ДД ЧЧ:ММ:СС»."""
        return self.dt.dateTime().toString(QT_DATE_FMT)



# ---------------------------------------------------------------------------
# НОВОЕ: ЕДИНОЕ построение списка «Распознанные варианты» (вкладки «Скриншот» и «Скриншот оптом»)
# ---------------------------------------------------------------------------
SHOT_ROW_HEIGHT = 64            # высота одной строки списка, px (иконка 40 + поля + поле даты)



SHOT_LIST_VISIBLE_ROWS = 6      # сколько строк должно быть видно без прокрутки (не меньше 5)



def shot_list_min_height() -> int:
    """Минимальная высота списка: SHOT_LIST_VISIBLE_ROWS полных строк + отступы и рамка."""
    return SHOT_LIST_VISIBLE_ROWS * (SHOT_ROW_HEIGHT + 8) + 16



def shot_title(p: dict) -> str:
    """Читаемое название найденной записи: у персонажа и дуги — очищенное название, у
    предметов без названия — стандартное («Потерянный фрагмент (30 шт)»)."""
    info = LOOT_TYPES.get(p["loot"])
    if info is None:
        return p["name"] or "—"
    if p["name"]:
        return p["name"]
    if info["mode"] == "reward":
        qty = info.get("qty")
        detail = pick_item_qty(info, p.get("qty")) if qty else info.get("detail", "")
        return default_reward_name(info["kind"], detail)
    return info["label"]



def shot_list_state(lst: QListWidget) -> list:
    """(флажок, время, подтверждено ли время) каждой строки — чтобы пересборка списка
    (смена баннера) не теряла отметки и ручные правки времени."""
    out = []
    for i in range(lst.count()):
        row = lst.itemWidget(lst.item(i))
        if row is not None:
            out.append((row.check.isChecked(), row.datetime(), row.time_confirmed))
    return out



def append_shot_row(lst: QListWidget, idx: int, p: dict, fallback_dt, state: list = None,
                    on_check=None, numbered: bool = False, show_file: bool = False):
    """НОВОЕ: добавляет в QListWidget ОДНУ строку ShotRow для записи p (индекс idx). Вынесено из
    populate_shot_list, чтобы вкладка «Скриншоты разом» могла строить список порциями, не
    замораживая окно. state — уже согласованный с списком (или None)."""
    title = shot_title(p)
    # название — чистое («Потерянный фрагмент (30 шт)», «Дуга - Чистое небо»), затем
    # ранг буквой; тип добавляется, только если он ещё не входит в название
    parts = [f"{idx + 1}. {title}" if numbered else title, rank_letter(p["rarity"])]
    if p.get("type_text") and p["type_text"] not in title:
        parts.append(p["type_text"])
    if p.get("amount"):
        parts.append(f"×{p['amount']}")
    if p.get("needs_review"):          # причины — уверенность OCR, нечёткое совпадение и т. п.
        parts.append("⚠ проверьте: " + "; ".join(p.get("weak") or ["строка ненадёжна"]))
    elif p.get("doubtful"):
        parts.append("⚠ проверьте строку")
    if show_file and p.get("file"):
        parts.append(f"файл: {p['file']}")
    pm = make_pixmap(p["name"] or title, p["rarity"], 40,
                     loot_aliases(p["loot"]) if p["loot"] else ())
    row = ShotRow(" · ".join(parts), pm,
                  p["timestamp"] if p["has_time"] else fallback_dt,
                  found=p["has_time"], checked=not p.get("doubtful"),
                  raw_date=p.get("raw_date", ""))
    if state:
        checked, when, confirmed = state[idx]
        row.check.setChecked(checked)
        with blocked(row.dt):
            row.dt.setDateTime(when)
        row.time_confirmed = confirmed
        row._mark_found(confirmed, p.get("raw_date", ""))
    if p.get("needs_review"):
        row.set_review("; ".join(p.get("weak") or []))
    elif p.get("conf") is not None:
        row.setToolTip(f"Уверенность OCR: {p['conf']:.0f}%")
    if on_check is not None:
        row.check.toggled.connect(on_check)
    row.time_edited.connect(lambda i=idx: lst.setCurrentRow(i))
    item = QListWidgetItem()
    item.setSizeHint(QSize(row.sizeHint().width(),
                           max(row.sizeHint().height(), SHOT_ROW_HEIGHT)))
    lst.addItem(item)
    lst.setItemWidget(item, row)



def populate_shot_list(lst: QListWidget, found: list, fallback_dt, state: list = None,
                       on_check=None, numbered: bool = False, show_file: bool = False):
    """Заполняет QListWidget строками ShotRow. ОДНА реализация для обеих вкладок: одинаковые
    подписи, иконки, высота строк (SHOT_ROW_HEIGHT) и восстановление состояния."""
    state = state if state and len(state) == len(found) else None
    lst.setMinimumHeight(shot_list_min_height())
    lst.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    with blocked(lst):
        lst.clear()
        for idx, p in enumerate(found):
            append_shot_row(lst, idx, p, fallback_dt, state, on_check, numbered, show_file)
        if found:
            lst.setCurrentRow(0)
