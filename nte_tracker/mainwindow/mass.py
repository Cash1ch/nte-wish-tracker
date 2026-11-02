"""Вкладка «Скриншот оптом»: пакетное распознавание, очередь, добавление результатов."""

import time
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QListWidget, QProgressBar,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..catalog import ARC_BANNER, BANNERS
from ..errors import blocked
from ..ocr.columns import PAGE_ALTS, PAGE_INFO
from ..ocr.names_read import set_ocr_arc_banner
from ..ocr.ordering import (
    enforce_chronology, format_duration, mark_locked_times, mass_sort_key, order_shots, refresh_flagged,
    repair_stamp_misreads,
)
from ..ocr.pipeline import bottom_to_top_order
from ..ui.shot_editor import (
    append_shot_row, new_file_data, parse_file_with_edits, review_count, review_total, shot_list_state,
    SHOT_ROW_HEIGHT, ShotRow_WARN_BG,
)
from ..ui.widgets import make_button, make_combo, make_label, scroll_page
from ..workers.ocr_threads import BATCH_EXTS, MASS_LIST_ROWS, MASS_UI_SLICE_S, MassOcrThread


class MassMixin:
    """Вкладка «Скриншот оптом»: пакетное распознавание, очередь, добавление результатов."""

    # ======================================================================
    # НОВОЕ: подвкладка «Скриншоты разом» (100–200+ файлов, QThread, ETA)
    # ======================================================================
    def _build_mass(self) -> QWidget:
        page, root = scroll_page()
        self._mass_warns = []      # предупреждения о порядке скриншотов
        self.mass_paths = []       # выбранные файлы в порядке обработки (mass_sort_key)
        self.mass_data = {}        # путь -> {"text", "ranks", "glob", "status", "count", "chrono"}
        self.mass_found = []       # общий список записей В ПОРЯДКЕ ЗАПИСИ (старые первыми)
        self._mass_thread = None   # поток OCR (MassOcrThread)
        self._mass_job = None      # генератор «порционного» разбора и построения списка
        self._mass_started = 0.0   # time.monotonic() старта OCR
        self._mass_done = 0        # сколько файлов уже обработано (успешно или с ошибкой)
        self._mass_summary = ""
        # таймер часов («Прошло» / «Осталось»), раз в секунду
        self._mass_clock = QTimer(self)
        self._mass_clock.setInterval(1000)
        self._mass_clock.timeout.connect(self._mass_tick)
        # «насос» порций разбора: срабатывает, когда очередь событий свободна
        self._mass_pump = QTimer(self)
        self._mass_pump.setInterval(0)
        self._mass_pump.timeout.connect(self._mass_pump_step)

        # «Баннер (пул)» — синхронен с формами «Ручная», «Скриншот» и «Скриншот оптом»
        self.mass_banner = make_combo([(l, k) for k, l in BANNERS.items()])
        banner_row = QHBoxLayout()
        banner_row.addWidget(QLabel("Баннер (пул):"))
        banner_row.addWidget(self.mass_banner, 1)
        root.addLayout(banner_row)
        self.mass_banner.activated.connect(self._on_mass_banner_activated)
        self._sync_shot_banner()

        top = QHBoxLayout()
        self.mass_pick_btn = make_button("Выбрать файл", self.pick_mass_screenshots, "primary")
        self.mass_pick_btn.setToolTip("Выбрать файлы скриншотов (без ограничений)")
        self.mass_pick_btn.setFixedHeight(32)
        self.mass_pick_btn.setMaximumWidth(180)
        self.mass_pick_btn.setStyleSheet("padding: 6px 12px;")
        self.mass_cancel_btn = make_button("Отменить обработку", self.cancel_mass)
        self.mass_cancel_btn.setEnabled(False)
        # НОВОЕ: мини-игра на время обработки скриншотов
        self.mass_game_btn = make_button("Поиграй 🎮", self.open_minigame, "primary")
        self.mass_game_btn.setToolTip("Мини-игры (Космические захватчики, Арканоид, Платформер, Астероиды): развлечение, пока идёт обработка скриншотов")
        top.addWidget(self.mass_pick_btn)
        top.addStretch(1)
        top.addWidget(self.mass_game_btn)
        top.addWidget(self.mass_cancel_btn)
        root.addLayout(top)
        root.addWidget(make_label(
            "Можно выбрать сколько угодно файлов (100–200 и больше). Скриншоты обрабатываются по "
            "одному в фоновом потоке — окно не зависает. Порядок: по имени файла, затем по "
            "найденному на снимках времени (старые первыми); внутри скриншота — снизу вверх.",
            "hint", wrap=True))

        prog_box = QGroupBox("Ход обработки")
        prog_l = QVBoxLayout(prog_box)
        self.mass_progress = QProgressBar()
        self.mass_progress.setRange(0, 1)
        self.mass_progress.setValue(0)
        self.mass_progress.setTextVisible(True)
        self.mass_progress.setFormat("Обработано %v из %m (%p%)")
        self.mass_progress.setFixedHeight(22)
        prog_l.addWidget(self.mass_progress)
        clock_row = QHBoxLayout()
        self.mass_elapsed_lbl = QLabel("Прошло: 00:00")
        self.mass_eta_lbl = QLabel("Осталось: —")
        clock_row.addWidget(self.mass_elapsed_lbl)
        clock_row.addStretch(1)
        clock_row.addWidget(self.mass_eta_lbl)
        prog_l.addLayout(clock_row)
        self.mass_status = make_label("Выберите файлы скриншотов для массовой обработки.",
                                      "hint", wrap=True)
        prog_l.addWidget(self.mass_status)
        root.addWidget(prog_box)

        files_box = QGroupBox("Выбранные скриншоты")
        files_l = QVBoxLayout(files_box)
        self.mass_table = QTableWidget(0, 7)
        self.mass_table.setHorizontalHeaderLabels(
            ["№", "Файл", "Путь", "Хронология", "Записей", "Статус", "Проверить"])
        self.mass_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.mass_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.mass_table.setShowGrid(False)
        self.mass_table.verticalHeader().setVisible(False)
        hdr = self.mass_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.mass_table.setMinimumHeight(190)
        files_l.addWidget(self.mass_table)
        root.addWidget(files_box)

        list_box = QGroupBox("Все распознанные записи (общий список)")
        list_l = QVBoxLayout(list_box)
        self.mass_list = QListWidget()
        self.mass_list.setIconSize(QSize(40, 40))
        self.mass_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.mass_list.setMinimumHeight(MASS_LIST_ROWS * (SHOT_ROW_HEIGHT + 8) + 16)  # расширенный
        self.mass_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        list_l.addWidget(self.mass_list)
        self.mass_edit_btn = make_button("Редактор нераспознанных строк",
                                         lambda *_: self._run_row_editor("mass"))
        self.mass_edit_btn.setEnabled(False)
        list_l.addWidget(self.mass_edit_btn)
        self.mass_add_btn = make_button("Добавить все найденные крутки", self.add_all_mass,
                                        "primary")
        self.mass_add_btn.setEnabled(False)
        list_l.addWidget(self.mass_add_btn)
        root.addWidget(list_box)
        root.addStretch(1)
        return page

    def _mass_busy(self) -> bool:
        """Идёт ли OCR, разбор или любое другое распознавание (Tesseract не запускается параллельно)."""
        return (self._mass_thread is not None or self._mass_job is not None
                or getattr(self, "_ocr_thread", None) is not None)

    def pick_mass_screenshots(self):
        if self._mass_busy():
            self.info("Обработка ещё идёт — подождите или нажмите «Отменить обработку».")
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Скриншоты разом (без ограничений)", "",
            "Изображения (*.png *.jpg *.jpeg *.bmp);;Все файлы (*)")
        if not paths:
            return
        unique = list(dict.fromkeys(paths))
        valid = [p for p in unique if Path(p).suffix.lower() in BATCH_EXTS]
        if not valid:
            self.warn("Не выбрано ни одного изображения (.jpg, .jpeg, .png, .bmp).")
            return
        valid.sort(key=mass_sort_key)                  # строгий порядок до старта обработки
        self.mass_paths = valid
        self.mass_data = {p: new_file_data() for p in valid}
        self.mass_found = []
        with blocked(self.mass_list):
            self.mass_list.clear()
        self._update_mass_button()
        self._fill_mass_table()
        total = len(valid)
        self._mass_done = 0
        self.mass_progress.setRange(0, total)
        self.mass_progress.setValue(0)
        self.mass_elapsed_lbl.setText("Прошло: 00:00")
        self.mass_eta_lbl.setText("Осталось: вычисляется…")
        skipped = len(unique) - len(valid)
        self.mass_status.setText(
            (f"Пропущено файлов неподдерживаемого формата: {skipped}. " if skipped else "")
            + f"Запуск обработки: файлов {total}…")
        self._start_mass()

    def _start_mass(self):
        set_ocr_arc_banner(self.mass_banner.currentData() == ARC_BANNER)
        thread = MassOcrThread(self.mass_paths, self)
        thread.progress.connect(self._on_mass_progress)
        thread.file_done.connect(self._on_mass_file_done)
        thread.file_failed.connect(self._on_mass_file_failed)
        thread.finished.connect(self._on_mass_finished)
        self._mass_thread = thread
        self._mass_started = time.monotonic()
        self.mass_pick_btn.setEnabled(False)
        self.mass_cancel_btn.setEnabled(True)
        self._mass_clock.start()
        thread.start()

    def cancel_mass(self):
        if self._mass_thread is not None:
            self._mass_thread.requestInterruption()
            self.mass_cancel_btn.setEnabled(False)
            self.mass_status.setText("Отмена: дожидаюсь завершения текущего скриншота…")

    def _mass_tick(self):
        """Раз в секунду: «Прошло» и оценка «Осталось» = среднее время файла × оставшиеся файлы."""
        total = len(self.mass_paths)
        elapsed = time.monotonic() - self._mass_started
        self.mass_elapsed_lbl.setText(f"Прошло: {format_duration(elapsed)}")
        done = self._mass_done
        if self._mass_thread is None:
            self.mass_eta_lbl.setText("Осталось: 00:00" if done >= total else "Осталось: —")
        elif done <= 0:
            self.mass_eta_lbl.setText("Осталось: вычисляется…")
        else:
            self.mass_eta_lbl.setText(
                f"Осталось: ~{format_duration(elapsed / done * (total - done))}")

    def _fill_mass_table(self):
        t = self.mass_table
        t.setUpdatesEnabled(False)
        t.setRowCount(len(self.mass_paths))
        for i in range(len(self.mass_paths)):
            self._mass_set_row(i)
        t.setUpdatesEnabled(True)

    def _mass_set_row(self, i: int):
        """Обновляет одну строку таблицы файлов (не перестраивает всю таблицу)."""
        path = self.mass_paths[i]
        d = self.mass_data[path]
        need = review_count(d)
        cells = (str(i + 1), Path(path).name, path,
                 "—" if d["chrono"] is None else str(d["chrono"]),
                 "—" if d["count"] is None else str(d["count"]), d["status"],
                 str(need) if need else "—")
        for c, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if c in (0, 3, 4, 6):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if c == 5 and d.get("error"):
                item.setToolTip(d["error"])
            if c == 6 and need:
                item.setBackground(ShotRow_WARN_BG)        # жёлтый: в файле есть что проверить
            self.mass_table.setItem(i, c, item)

    def _on_mass_progress(self, i: int, total: int):
        self.mass_data[self.mass_paths[i]]["status"] = "Обработка…"
        self._mass_set_row(i)
        self.mass_table.scrollToItem(self.mass_table.item(i, 1))
        self.mass_status.setText(f"Обработка скриншота {i + 1} из {total}: "
                                 f"{Path(self.mass_paths[i]).name}")

    def _on_mass_file_done(self, i: int, text: str, ranks, glob, confs=None):
        d = self.mass_data[self.mass_paths[i]]
        d["page"] = PAGE_INFO.pop(self.mass_paths[i], None)
        d["page_alts"] = PAGE_ALTS.pop(self.mass_paths[i], [])
        d.update(text=text, ranks=list(ranks or []), glob=glob,
                 confs=list(confs) if confs is not None else None,
                 status="Обработано", done=True)
        self._mass_done += 1
        self.mass_progress.setValue(self._mass_done)
        self._mass_set_row(i)
        self._mass_tick()

    def _on_mass_file_failed(self, i: int, message: str):
        d = self.mass_data[self.mass_paths[i]]
        d.update(status="Ошибка", error=message, done=False)
        self._mass_done += 1
        self.mass_progress.setValue(self._mass_done)
        self._mass_set_row(i)
        self._mass_tick()

    def _on_mass_finished(self):
        """OCR завершён (или отменён): останавливаем часы и переходим к разбору текста."""
        thread, self._mass_thread = self._mass_thread, None
        if thread is not None:
            thread.deleteLater()
        self._mass_clock.stop()
        self._mass_tick()
        self.mass_cancel_btn.setEnabled(False)
        cancelled = False
        for i, path in enumerate(self.mass_paths):
            d = self.mass_data[path]
            if d["status"] in ("Ожидает", "Обработка…"):
                d["status"], cancelled = "Отменено", True
                self._mass_set_row(i)
        failed = sum(1 for d in self.mass_data.values() if d["status"] == "Ошибка")
        head = f"Обработано {self._mass_done} из {len(self.mass_paths)} скриншотов."
        if cancelled:
            head = "Обработка отменена. " + head
        if failed:
            head += f" Не распознано: {failed} (подробности — в подсказке к статусу)."
        self._mass_head = head
        self._mass_open_editor = True        # после разбора откроем «Редактор нераспознанных строк»
        self._mass_start_job()

    # ---------- «порционный» разбор и построение списка (окно не зависает) ----------
    def _mass_start_job(self, keep_state: bool = False):
        old, self._mass_job = self._mass_job, None
        if old is not None:
            old.close()
        self.mass_pick_btn.setEnabled(False)
        self.mass_add_btn.setEnabled(False)
        self._mass_job = self._mass_job_gen(keep_state)
        self._mass_pump.start()

    def _mass_pump_step(self):
        """Один тик насоса: выполняет шаги генератора в пределах MASS_UI_SLICE_S и возвращает
        управление циклу событий — интерфейс остаётся отзывчивым."""
        gen = self._mass_job
        if gen is None:
            self._mass_pump.stop()
            return
        t0 = time.monotonic()
        try:
            while time.monotonic() - t0 < MASS_UI_SLICE_S:
                next(gen)
        except StopIteration:
            self._mass_job = None
            self._mass_pump.stop()
            self._on_mass_job_done()
        except Exception as e:  # noqa: BLE001 — ошибка разбора не должна ронять окно
            self._mass_job = None
            self._mass_pump.stop()
            self.mass_pick_btn.setEnabled(True)
            self._update_mass_button()
            self.error(f"Ошибка разбора скриншотов:\n{e}")

    def _mass_job_gen(self, keep_state: bool):
        """Генератор: 1) разбор текстов теми же правилами, что на «Скриншот» (parse_screenshot_text);
        2) порядок: скриншоты — от старых к новым (по найденному времени, без времени — в конце
        по порядку имён), внутри скриншота — снизу вверх; 3) построение общего списка строк."""
        lst = self.mass_list
        state = shot_list_state(lst) if keep_state else None
        default_loot = "arc" if self.mass_banner.currentData() == ARC_BANNER else "character"
        todo = [(order, path) for order, path in enumerate(self.mass_paths)
                if self.mass_data[path]["done"]]
        per_file, skipped_total = [], 0
        for n, (order, path) in enumerate(todo, 1):
            d = self.mass_data[path]
            # разбор + правки редактора (записи остаются на своих местах раскладки скриншота)
            pulls, skipped = parse_file_with_edits(d, self.known, default_loot)
            skipped_total += skipped
            d["count"] = len(pulls)
            per_file.append({"order": order, "path": path, "pulls": pulls,
                             "page": d.get("page"), "page_alts": d.get("page_alts") or [],
                             "edits": d.get("edits")})
            self.mass_status.setText(f"Разбор текста: {n} из {len(todo)}…")
            yield
        mark_locked_times(per_file)
        repair_stamp_misreads([e["pulls"] for e in per_file])
        per_file, order_warns, page_mode = order_shots(per_file, len(self.mass_paths))
        if page_mode:
            order_warns += enforce_chronology(per_file)[1]
        refresh_flagged(per_file, self.mass_data)
        self._mass_warns = order_warns
        per_file = [(pos, e["path"], e["pulls"]) for pos, e in enumerate(per_file)]
        self.mass_found = []
        for pos, (_key, path, pulls) in enumerate(per_file, 1):
            self.mass_data[path]["chrono"] = pos
            name = Path(path).name
            self.mass_found += [dict(p, file=name) for p in bottom_to_top_order(pulls)]
        self._fill_mass_table()
        yield
        found = self.mass_found
        state = state if state and len(state) == len(found) else None
        fallback = self.in_dt.dateTime()
        lst.setUpdatesEnabled(False)        # без перерисовки на каждую строку — быстрее
        try:
            with blocked(lst):
                lst.clear()
            for idx, p in enumerate(found):
                append_shot_row(lst, idx, p, fallback, state, self._update_mass_button,
                                numbered=True, show_file=True)
                if idx % 20 == 0:
                    self.mass_status.setText(f"Построение списка: {idx + 1} из {len(found)}…")
                yield
            if found:
                with blocked(lst):
                    lst.setCurrentRow(0)
        finally:
            lst.setUpdatesEnabled(True)
        no_time = sum(1 for _k, _p, pulls in per_file if not any(p["has_time"] for p in pulls))
        if found:
            self._mass_summary = (f"Найдено записей: {len(found)}"
                                  + (f" · нераспознанных строк пропущено: {skipped_total}"
                                     if skipped_total else "")
                                  + (f" · ⚠ скриншотов без найденного времени: {no_time} "
                                     f"(порядок задан по имени файла)" if no_time else "")
                                  + (f" · ⚠ строк для проверки (жёлтые): "
                                     f"{review_total(self.mass_data)}"
                                     if review_total(self.mass_data) else "")
                                  + "".join(f" · ⚠ {w}" for w in self._mass_warns))
        elif per_file:
            self._mass_summary = ("Ничего не распознано — попробуйте другие скриншоты "
                                  "или вкладку «Скриншот» для ручной правки текста.")
        else:
            self._mass_summary = "Ни один скриншот не распознан."

    def _on_mass_job_done(self):
        self.mass_pick_btn.setEnabled(True)
        self._update_mass_button()
        self._update_editor_buttons()
        if getattr(self, "_mass_open_editor", False):   # только после сканирования, не после смены баннера
            self._mass_open_editor = False
            if review_total(self.mass_data):
                QTimer.singleShot(0, lambda: self._run_row_editor("mass", auto=True))
        head = getattr(self, "_mass_head", "")
        self.mass_status.setText(f"{head} {self._mass_summary} · отмечено к добавлению: "
                                 f"{self._mass_checked_count()}".strip())

    def _mass_row(self, i: int):
        item = self.mass_list.item(i)
        return self.mass_list.itemWidget(item) if item is not None else None

    def _mass_checked_count(self) -> int:
        rows = (self._mass_row(i) for i in range(self.mass_list.count()))
        return sum(1 for r in rows if r is not None and r.check.isChecked())

    def _update_mass_button(self, *_):
        n = self._mass_checked_count()
        busy = self._mass_thread is not None or self._mass_job is not None
        self.mass_add_btn.setEnabled(n > 0 and not busy)
        self._update_editor_buttons()
        self.mass_add_btn.setText(f"Добавить все найденные крутки ({n})" if n
                                  else "Добавить все найденные крутки")

    def add_all_mass(self):
        """Записывает ВСЕ отмеченные записи общего списка одной транзакцией (import_batch ->
        executemany); подтверждение и предупреждения — общие с «Скриншот оптом»."""
        msg = self._commit_multi_shots(self.mass_found, self._mass_row, self.mass_banner,
                                       self._mass_warns)
        if msg is None:
            return
        self.mass_found = []
        self.mass_data = {}
        self.mass_paths = []
        with blocked(self.mass_list):
            self.mass_list.clear()
        self._fill_mass_table()
        self.mass_progress.setRange(0, 1)
        self.mass_progress.setValue(0)
        self.mass_elapsed_lbl.setText("Прошло: 00:00")
        self.mass_eta_lbl.setText("Осталось: —")
        self._update_mass_button()
        self.mass_status.setText(msg)
        self.info(msg)
