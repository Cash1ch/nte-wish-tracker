"""Вкладка «Скриншот»: распознавание одного снимка и добавление найденных записей."""

from collections import Counter

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QPlainTextEdit, QVBoxLayout, QWidget,
)

from ..catalog import (
    ARC_BANNER, arc_kind_by_name, BANNERS, loot_rarity, LOOT_TYPES, MANUAL_HIDDEN_LOOT, NO_PITY_KINDS,
    pick_item_qty, rank_letter,
)
from ..config import QT_DATE_FMT
from ..database import _reward_key, _wish_key
from ..errors import blocked, DatabaseError
from ..icons import scale_smooth
from ..labels import default_reward_name
from ..ocr.names import finalize_loot_name
from ..ocr.names_read import set_ocr_arc_banner
from ..ocr.pipeline import bottom_to_top_order, parse_screenshot_text
from ..ui.shot_editor import (
    collect_editor_entries, populate_shot_list, review_total, RowEditorDialog, shot_list_min_height,
    shot_title,
)
from ..ui.widgets import make_button, make_combo, make_label, scroll_page, SmoothIconLabel
from ..workers.ocr_threads import OcrThread


class ScreenshotMixin:
    """Вкладка «Скриншот»: распознавание одного снимка и добавление найденных записей."""

    # ---------- подвкладка «Скриншот» ----------
    def _build_screenshot(self) -> QWidget:
        page, root = scroll_page()
        self.shot_path = ""
        self.shot_ranks, self.shot_global, self.shot_found = [], None, []

        # НОВОЕ: «Баннер (пул)» и на вкладке «Скриншот». Список всегда синхронен со списком
        # формы «Ручная» (self.in_banner): тот, что выбран здесь, попадёт в форму при
        # «Подставить в форму». Автоопределение баннера обновляет оба списка сразу.
        self.shot_banner = make_combo([(l, k) for k, l in BANNERS.items()])
        banner_row = QHBoxLayout()
        banner_row.addWidget(QLabel("Баннер (пул):"))
        banner_row.addWidget(self.shot_banner, 1)
        root.addLayout(banner_row)
        # activated — только действия пользователя: переносим выбор в форму «Ручная»
        self.shot_banner.activated.connect(self._on_shot_banner_activated)
        # любое изменение списка формы «Ручная» (в т.ч. автоматическое) отражаем здесь
        self.in_banner.currentIndexChanged.connect(self._sync_shot_banner)
        self._sync_shot_banner()

        top = QHBoxLayout()
        top.addWidget(make_button("Выбрать скриншот…", self.pick_screenshot, "primary"))
        self.shot_file_lbl = make_label("Файл не выбран", "hint", wrap=True)
        top.addWidget(self.shot_file_lbl, 1)
        root.addLayout(top)

        self.shot_preview = SmoothIconLabel("Предпросмотр скриншота")   # ИЗМЕНЕНО: сглаживание
        self.shot_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.shot_preview.setMinimumHeight(200)
        root.addWidget(self.shot_preview)

        text_box = QGroupBox("Распознанный текст (можно исправить)")
        text_l = QVBoxLayout(text_box)
        self.shot_text = QPlainTextEdit()
        self.shot_text.setMinimumHeight(110)
        text_l.addWidget(self.shot_text)
        text_l.addWidget(make_button("Разобрать текст заново", self.reparse_screenshot))
        root.addWidget(text_box)

        list_box = QGroupBox("Распознанные варианты")
        list_l = QVBoxLayout(list_box)
        self.shot_list = QListWidget()
        self.shot_list.setIconSize(QSize(40, 40))
        self.shot_list.setMinimumHeight(shot_list_min_height())   # >= 5 полных строк
        self.shot_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.shot_list.itemDoubleClicked.connect(lambda *_: self.apply_ocr_result())
        list_l.addWidget(self.shot_list)
        # НОВОЕ: у каждой найденной крутки есть флажок; кнопка ниже добавляет все отмеченные
        # (по умолчанию отмечены все, кроме сомнительных строк с «⚠») одним действием
        self.shot_add_all = make_button("Добавить все найденные крутки", self.add_all_found,
                                        "primary")
        self.shot_add_all.setEnabled(False)
        # (флажки теперь внутри строк ShotRow — каждая строка сама сообщает об изменении)
        list_l.addWidget(self.shot_add_all)
        list_l.addWidget(make_button("Подставить в форму", self.apply_ocr_result))
        self.shot_status = make_label(name="hint", wrap=True)
        list_l.addWidget(self.shot_status)
        root.addWidget(list_box)
        root.addStretch(1)
        return page

    def pick_screenshot(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Скриншот", "", "Изображения (*.png *.jpg *.jpeg *.webp *.bmp);;Все файлы (*)")
        if not path:
            return
        if getattr(self, "_ocr_thread", None) is not None:
            self.info("Распознавание предыдущего скриншота ещё идёт — подождите немного.")
            return
        self.shot_path = path
        self.shot_file_lbl.setText(path)
        pm = QPixmap(path)
        if pm.isNull():
            self.shot_preview.setText("Не удалось показать изображение")
        else:
            # ИЗМЕНЕНО: KeepAspectRatio + SmoothTransformation, с учётом плотности пикселей
            # экрана (scale_smooth) — скриншот остаётся резким и на HiDPI
            self.shot_preview.setPixmap(scale_smooth(
                pm, 760, 320, Qt.AspectRatioMode.KeepAspectRatio,
                self.shot_preview.devicePixelRatioF()))
        self.recognize_screenshot()

    def recognize_screenshot(self):
        """Запускает распознавание (OCR + цвет значков) в фоновом потоке — окно не зависает.
        Результат приходит в _on_ocr_done / _on_ocr_failed."""
        if getattr(self, "_ocr_thread", None) is not None:
            self.shot_status.setText("Распознавание уже идёт — подождите…")
            return
        self.shot_status.setText("Распознаю скриншот…")
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        set_ocr_arc_banner(self.shot_banner.currentData() == ARC_BANNER)
        thread = OcrThread(self.shot_path, self)
        thread.done.connect(self._on_ocr_done)
        thread.failed.connect(self._on_ocr_failed)
        self._ocr_thread = thread
        thread.start()

    def _on_ocr_done(self, lines, ranks, glob):
        """Распознавание закончено: показываем текст и строим список вариантов."""
        QApplication.restoreOverrideCursor()
        self._ocr_thread = None
        # служебные строки интерфейса уже убраны, ранги привязаны к оставшимся строкам
        self.shot_ranks, self.shot_global = ranks, glob
        self.shot_text.setPlainText("\n".join(ln["text"] for ln in lines))
        self._fill_candidates()

    def _on_ocr_failed(self, text: str):
        QApplication.restoreOverrideCursor()
        self._ocr_thread = None
        self.shot_status.setText("Не удалось распознать скриншот.")
        self.warn(text)

    def reparse_screenshot(self):
        self._fill_candidates()

    def _fill_candidates(self, keep_state: bool = False):
        """Строит список ВСЕХ круток со скриншота из текста (в том числе после ручной правки).
        ИЗМЕНЕНО: служебный текст отфильтрован, каждая строка списка — отдельная крутка с
        флажком; кнопка «Добавить все найденные крутки» добавляет отмеченные."""
        # НОВОЕ: при смене баннера список пересобирается (тип безымянных строк зависит от
        # баннера), но флажки и ИСПРАВЛЕННОЕ вручную время сохраняются, если число строк прежнее
        state = []
        if keep_state:
            for i in range(self.shot_list.count()):
                r = self._shot_row(i)
                if r is not None:
                    state.append((r.check.isChecked(), r.datetime(), r.time_confirmed))
        text = self.shot_text.toPlainText()
        # тип безымянных строк зависит от баннера: на «Дуге» это дуги, иначе — персонажи
        default_loot = "arc" if self.shot_banner.currentData() == ARC_BANNER else "character"
        # ЕДИНЫЙ разбор: та же функция использует и вкладка «Скриншот оптом»
        self.shot_found, skipped = parse_screenshot_text(text, self.known, self.shot_ranks,
                                                         self.shot_global, default_loot)
        # запасное время для строк, у которых на снимке времени нет, — время формы «Ручная»
        populate_shot_list(self.shot_list, self.shot_found, self.in_dt.dateTime(),
                           state, self._update_add_all_button)
        self._update_add_all_button()
        if self.shot_found:
            status = f"Найдено вариантов: {len(self.shot_found)}"
            status += f" · отмечено к добавлению: {self._checked_count()}"
            if skipped:
                status += f" · нераспознанных строк пропущено: {skipped}"
            self.shot_status.setText(status)
        else:
            self.shot_status.setText(
                "Ничего не распознано — исправьте текст и нажмите «Разобрать текст заново».")

    @staticmethod
    def _shot_title(p: dict) -> str:
        """Название найденной записи для списка (единая функция shot_title)."""
        return shot_title(p)

    def _shot_row(self, i: int):
        """Виджет-строка ShotRow списка вариантов (или None)."""
        item = self.shot_list.item(i)
        return self.shot_list.itemWidget(item) if item is not None else None

    def _checked_count(self) -> int:
        """Сколько строк списка найденных круток отмечено флажком."""
        rows = (self._shot_row(i) for i in range(self.shot_list.count()))
        return sum(1 for r in rows if r is not None and r.check.isChecked())

    def _update_add_all_button(self, *_):
        """Кнопка «Добавить все найденные крутки»: доступна, если что-то отмечено."""
        n = self._checked_count()
        self.shot_add_all.setEnabled(n > 0)
        self.shot_add_all.setText(f"Добавить все найденные крутки ({n})" if n
                                  else "Добавить все найденные крутки")

    def _record_from_ocr(self, p: dict, banner: str, fallback_stamp: str):
        """НОВОЕ: запись для базы из распознанной строки -> («wish» | «reward», словарь).
        Правила те же, что у формы «Ручная» (add_item): ранг предметов и кешбэка жёсткий,
        название очищено, у дуги — «Дуга - Название». Нет времени на снимке — берётся
        запомненное время формы; привязка костюма/планера/окраски к персонажу остаётся пустой;
        тип S дуги (стандартная / ивентовая) берётся из формы «Ручная»."""
        key = p["loot"]
        info = LOOT_TYPES[key]
        stamp = p["timestamp"].toString(QT_DATE_FMT) if p["has_time"] else fallback_stamp
        name = finalize_loot_name(key, p["name"])
        mode = info["mode"]
        if mode == "reward":
            if info.get("qty"):
                detail = pick_item_qty(info, p.get("qty"))
            elif info.get("bind"):
                detail = ""
            else:
                detail = info.get("detail", "")
            return "reward", {
                "kind": info["kind"], "name": name or default_reward_name(info["kind"], detail),
                "detail": detail, "obtained_at": stamp, "banner": banner,
                # «Подарок за очки» среди предметов: вне гаранта (счётчик круток не растёт)
                "no_pity": int(bool(info.get("no_pity")) or info["kind"] in NO_PITY_KINDS
                               or bool(p.get("is_bonus")) or bool(p.get("no_pity"))),
                # OCR-ФИКС: ранг по цвету текста на скриншоте (иначе — по виду предмета)
                "rarity": (rank_letter(p["rarity"]) if p.get("rarity_src") == "цвет" else "")}
        # НОВОЕ: бонусная добыча («Подарок за очки») — is_bonus=1, ранг A, счётчики и гарант
        # не затрагиваются (см. compute_stats), в истории тип «Бонус (10 круток) · …»
        is_bonus = bool(p.get("is_bonus")) and mode == "wish"
        rarity = (loot_rarity(info) if mode == "cashback" else 4 if is_bonus else p["rarity"])
        arc_kind = ""
        if mode == "wish" and banner == ARC_BANNER and rarity == 5 and not is_bonus:
            arc_kind = arc_kind_by_name(name, self.in_arc_kind.currentData() or "")
        return "wish", {
            "banner": banner, "rarity": rarity, "name": name or info["default"],
            "pulled_at": stamp, "is_bonus": int(is_bonus), "arc_kind": arc_kind,
            "cashback": info.get("cashback", "") if mode == "cashback" else ""}

    # ---------- НОВОЕ: «Редактор нераспознанных строк» (общий для обеих вкладок) ----------
    def _update_editor_buttons(self):
        """Кнопки редакторов: число строк для проверки; недоступны, пока идёт обработка."""
        for which, btn in (("mass", getattr(self, "mass_edit_btn", None)),):
            if btn is None:
                continue
            data = self.mass_data
            n = review_total(data)
            busy = self._mass_thread is not None or self._mass_job is not None
            btn.setEnabled(n > 0 and not busy)
            btn.setText(f"Редактор нераспознанных строк ({n})" if n
                        else "Редактор нераспознанных строк")

    def _run_row_editor(self, which: str, auto: bool = False):
        """Открывает редактор для вкладки which («batch» / «mass»). После «Применить» правки
        сохраняются по номерам строк, список пересобирается теми же правилами и порядком."""
        if self._mass_thread is not None or self._mass_job is not None:
            return
        paths, data = self.mass_paths, self.mass_data
        entries = collect_editor_entries(paths, data)
        if not entries:
            if not auto:
                self.info("Нет строк, требующих проверки.")
            return
        dlg = RowEditorDialog(entries, self.in_dt.dateTime(), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        for res in dlg.results:                  # правки запоминаем по номеру строки файла
            d = data[res["path"]]
            d["reviewed"].add(res["line"])
            if res["kind"] == "flag" and not res["include"]:
                d["edits"][res["line"]] = {"include": False}          # строку убрали
            elif res["include"] and (res["changed"] or res["kind"] == "skipped"):
                d["edits"][res["line"]] = res["edit"]
        self._mass_start_job()

    def _commit_multi_shots(self, found: list, row_of, banner_combo, extra_warnings=()):
        """ОБЩАЯ запись для «Скриншот оптом» и «Скриншоты разом»: все отмеченные записи общего
        списка пишутся ОДНОЙ транзакцией (import_batch -> executemany). Список уже идёт в
        порядке записи (старые первыми), поэтому seq выдаётся по порядку списка; дубликаты с
        одинаковым временем не пропускаются (как и на вкладке «Скриншот»).
        found — записи, row_of(i) — виджет строки, banner_combo — выбор «Баннер (пул)».
        Возвращает текст итога или None (нет отмеченных / ошибка)."""
        picked, no_time = [], 0
        for i, p in enumerate(found):
            row = row_of(i)
            if row is None or not row.check.isChecked():
                continue
            picked.append(dict(p, timestamp=row.datetime(), has_time=True))
            no_time += not row.time_confirmed
        if not picked:
            self.info("Нет отмеченных круток для добавления.")
            return
        banner = banner_combo.currentData()
        fallback = self.in_dt.dateTime().toString(QT_DATE_FMT)
        wishes, rewards, mismatch, s_arcs = [], [], 0, 0
        for seq, p in enumerate(picked):
            kind, rec = self._record_from_ocr(p, banner, fallback)
            rec["seq"] = seq
            (wishes if kind == "wish" else rewards).append(rec)
            if LOOT_TYPES[p["loot"]]["mode"] == "wish":
                mismatch += (p["loot"] == "arc") != (banner == ARC_BANNER)
                s_arcs += p["loot"] == "arc" and banner == ARC_BANNER and p["rarity"] == 5

        # подтверждение перед записью убрано: отмеченные записи добавляются сразу
        try:
            added_w, added_r = self.db.import_batch(wishes, rewards)
        except DatabaseError as e:
            self.error(str(e))
            return
        self.refresh()
        msg = f"Добавлено круток: {added_w}"
        if rewards:
            msg += f", предметов: {added_r}"
        return msg

    def _count_already_in_db(self, wishes: list, rewards: list) -> int:
        """НОВОЕ: сколько записей пакета уже есть в базе (по названию, типу и времени).
        Одинаковые записи учитываются с кратностью: две одинаковые в пакете и одна в базе —
        «уже есть» одна. Ошибки базы здесь не критичны — возвращается 0."""
        try:
            have_w = Counter(_wish_key(r) for r in self.db.fetch_all())
            have_r = Counter(_reward_key(r) for r in self.db.fetch_rewards())
        except (DatabaseError, KeyError, TypeError):
            return 0
        total = 0
        for keys, have in ((Counter(_wish_key(r) for r in wishes), have_w),
                           (Counter(_reward_key(r) for r in rewards), have_r)):
            total += sum(min(n, have.get(k, 0)) for k, n in keys.items())
        return total

    def add_all_found(self):
        """Добавляет в базу ВСЕ отмеченные крутки скриншота одним действием.
        Баннер — выбранный в списке «Баннер (пул)». ИСПРАВЛЕНО: записи пишутся СНИЗУ ВВЕРХ
        (bottom_to_top_order: нижняя строка скриншота — самая ранняя), одной транзакцией
        (Database.import_batch), а дубликаты с одинаковым временем НЕ пропускаются."""
        # ИЗМЕНЕНО: время каждой записи берётся из РЕДАКТИРУЕМОГО поля строки списка
        # (оно уже содержит время со скриншота), а не из datetime.now() и не из формы.
        # has_time=True гарантирует, что _record_from_ocr использует именно это значение.
        picked, no_time = [], 0
        for i, p in enumerate(self.shot_found):
            row = self._shot_row(i)
            if row is None or not row.check.isChecked():
                continue
            picked.append(dict(p, timestamp=row.datetime(), has_time=True))
            no_time += not row.time_confirmed   # время не найдено и не правилось вручную
        if not picked:
            self.info("Нет отмеченных круток для добавления.")
            return
        banner = self.shot_banner.currentData()
        fallback = self.in_dt.dateTime().toString(QT_DATE_FMT)  # запасной вариант, не используется
        wishes, rewards, mismatch, s_arcs = [], [], 0, 0
        for seq, p in enumerate(bottom_to_top_order(picked)):  # снизу вверх: старые первыми
            kind, rec = self._record_from_ocr(p, banner, fallback)
            rec["seq"] = seq   # порядковый номер в хронологии пакета (см. Database.import_batch)
            (wishes if kind == "wish" else rewards).append(rec)
            if LOOT_TYPES[p["loot"]]["mode"] == "wish":
                mismatch += (p["loot"] == "arc") != (banner == ARC_BANNER)
                s_arcs += p["loot"] == "arc" and banner == ARC_BANNER and p["rarity"] == 5

        bonus_n = sum(1 for rec in wishes if rec["is_bonus"]) + sum(
            1 for p in picked if p.get("is_bonus") and LOOT_TYPES[p["loot"]]["mode"] == "reward")
        text = (f"Будет добавлено записей: {len(picked)} (круток: {len(wishes)}, "
                f"предметов: {len(rewards)}).\nБаннер (пул): {BANNERS[banner]}.")
        if bonus_n:
            text += (f"\nИз них бонусной добычи («Подарок за очки»): {bonus_n} — "
                     f"гарант и счётчик круток она не меняет.")
        if no_time:
            text += (f"\n⚠ Время не найдено на снимке и не исправлено у записей: {no_time} — "
                     f"они сохранятся со временем из поля в списке (по умолчанию — время формы "
                     f"«Ручная»). Проверьте оранжевые поля даты.")
        if s_arcs:
            text += f"\nТип S дуги берётся из формы «Ручная»: {self.in_arc_kind.currentText()}."
        if mismatch:
            text += (f"\n⚠ Строк, не подходящих к выбранному баннеру (дуги и персонажи): "
                     f"{mismatch} — проверьте «Баннер (пул)».")
        # НОВОЕ: предупреждение о повторном добавлении того же скриншота. Записи НЕ отбрасываются
        # (в игре несколько круток бывают в одну секунду), но пользователь видит, что часть уже есть.
        already = self._count_already_in_db(wishes, rewards)
        if already:
            text += (f"\n⚠ Записей, которые уже есть в базе с тем же названием и временем: "
                     f"{already}. Возможно, этот скриншот уже добавлялся.")
        text += "\nВсе отмеченные записи будут добавлены, в том числе одинаковые с тем же временем.\n\nДобавить?"
        if not self.ask(text):
            return
        try:
            added_w, added_r = self.db.import_batch(wishes, rewards)
        except DatabaseError as e:
            self.error(str(e))
            return
        self.refresh()
        self.shot_found = []
        with blocked(self.shot_list):
            self.shot_list.clear()
        self._update_add_all_button()
        msg = f"Добавлено круток: {added_w}"
        if rewards:
            msg += f", предметов: {added_r}"
        self.shot_status.setText(msg.replace("\n", " · "))
        self.info(msg)

    def apply_ocr_result(self):
        row = self.shot_list.currentRow()
        if not 0 <= row < len(self.shot_found):
            self.info("Выберите вариант в списке.")
            return
        p = self.shot_found[row]
        widget = self._shot_row(row)
        if widget is not None:  # берём время из редактируемого поля строки
            p = dict(p, timestamp=widget.datetime(), has_time=widget.time_confirmed)
        self._fill_manual_from_ocr(p)

    def _fill_manual_from_ocr(self, p: dict):
        """Переносит выбранный вариант в форму «Ручная»: дата и время, тип, ранг,
        количество и ОЧИЩЕННОЕ название."""
        key = p["loot"] or self.in_type.currentData()
        info = LOOT_TYPES[key]
        if key in MANUAL_HIDDEN_LOOT:
            self.info("Этот тип записи нельзя добавить вручную.")
            return
        with blocked(self.in_type, self.in_bonus, self.in_rarity, self.in_name):
            self.in_type.setCurrentIndex(self.in_type.findData(key))
            self.in_bonus.setChecked(bool(p.get("is_bonus")) and info["mode"] == "wish")
            if info["mode"] == "wish":
                self.in_rarity.setCurrentIndex(self.in_rarity.findData(p["rarity"]))
            self.in_name.setText(finalize_loot_name(key, p["name"]))
        self._fill_qty(info)
        if p.get("qty"):
            if (self.in_qty.findData(p["qty"]) < 0 and info.get("qty_free")
                    and str(p["qty"]).isdigit()):
                self.in_qty.addItem(f"{p['qty']} шт", str(p["qty"]))
            self.in_qty.setCurrentIndex(max(0, self.in_qty.findData(p["qty"])))
        if p["has_time"]:  # нет времени на снимке — запомненное время не трогаем
            self.in_dt.setDateTime(p["timestamp"])
        self._sync_form()
        self.add_tabs.setCurrentIndex(0)
        self.add_status.setText("Данные со скриншота подставлены в форму — проверьте и нажмите «Добавить».")
