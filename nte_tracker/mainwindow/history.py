"""Вкладка «История»: таблица записей, отмена импорта, удаление."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QIcon
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QTableWidgetItem, QVBoxLayout, QWidget

from ..catalog import BANNERS, rank_letter, ROW_COLORS
from ..errors import DatabaseError
from ..icons import make_pixmap
from ..ui.widgets import make_button, make_combo, make_label, make_rank_combo, make_table


class HistoryMixin:
    """Вкладка «История»: таблица записей, отмена импорта, удаление."""

    # ---------- вкладка «История» (крутки, кешбэк, бонусы и предметы вместе) ----------
    def _build_history(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)

        self.f_banner = make_combo([("Все баннеры", None)] + [(l, k) for k, l in BANNERS.items()])
        self.f_rarity = make_rank_combo("Любой ранг")
        self.f_kind = make_combo([
            ("Все записи", None), ("Только крутки (с кешбэком)", "pulls"),
            ("Только кешбэк", "cashback"), ("Только бонусная добыча", "bonus"),
            ("Только предметы (кубики, костюмы…)", "item"),
        ])
        self.f_search = QLineEdit()
        self.f_search.setPlaceholderText("Поиск по названию…")
        self.f_search.setClearButtonEnabled(True)

        filters = QHBoxLayout()
        for f in (self.f_banner, self.f_rarity, self.f_kind):
            filters.addWidget(f)
            f.currentIndexChanged.connect(self._refresh_history)  # списки — сразу
        filters.addWidget(self.f_search, 1)
        # Поиск — через таймер (debounce): таблица перестраивается один раз после паузы
        self.f_search.textChanged.connect(lambda *_: self._hist_timer.start())
        root.addLayout(filters)

        self.table = make_table(
            ["", "№", "Баннер", "Ранг", "Название", "Тип", "Дата", "Гарант S (дуга: С / И)"], 4)
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.hist_count = make_label(name="hint")
        bottom.addWidget(self.hist_count, 1)
        bottom.addWidget(make_button("Отменить последний импорт", self.undo_last_import))
        bottom.addWidget(make_button("Удалить выбранные", self.delete_selected, "danger"))
        root.addLayout(bottom)
        return w

    def _refresh_history(self, *_):
        self._hist_timer.stop()  # если вызвали напрямую — отложенный запуск не нужен
        banner, rar = self.f_banner.currentData(), self.f_rarity.currentData()
        kind, q = self.f_kind.currentData(), self.f_search.text().strip().lower()
        rows = [
            e for e in self.history
            if (banner is None or e["banner"] == banner)
            and (rar is None or e["rarity"] == rar)
            and (kind is None or e["kind"] == kind
                 or (kind == "pulls" and e["kind"] in ("main", "cashback")))
            and (not q or q in e["name"].lower())
        ]

        t = self.table
        t.setUpdatesEnabled(False)
        t.clearSelection()
        t.setRowCount(0)
        t.setRowCount(len(rows))
        center = Qt.AlignmentFlag.AlignCenter
        for i, e in enumerate(rows):
            bg, fg = ROW_COLORS.get(e["rarity"], ROW_COLORS[3])
            values = ["", e["n"], e["banner_text"], rank_letter(e["rarity"]), e["name"],
                      e["type"], e["date"], e["pity"]]
            for c, v in enumerate(values):
                item = QTableWidgetItem(v)
                item.setBackground(QBrush(bg))
                item.setForeground(QBrush(fg))
                if c in (1, 3, 7):
                    item.setTextAlignment(center)
                if c == 0:
                    # ИЗМЕНЕНО: иконка ищется по названию И по синонимам типа предмета
                    # (у кубиков, костюмов, планеров и т.д.); нет файла — заглушка
                    item.setIcon(QIcon(make_pixmap(e["name"], e["rarity"], 40, e["aliases"])))
                if c == 1:
                    item.setData(Qt.ItemDataRole.UserRole, (e["src"], e["id"]))
                t.setItem(i, c, item)
            t.setRowHeight(i, 48)
        t.setUpdatesEnabled(True)
        self.hist_count.setText(f"Показано: {len(rows)} из {len(self.history)}")

    def undo_last_import(self):
        """Удаляет все записи последнего пакетного импорта («Скриншот оптом» / «Скриншоты
        разом») одной транзакцией; гарант пересчитывается."""
        bid = self.db.last_batch_id()
        if not bid:
            self.info("Нет пакетного импорта, который можно отменить.")
            return
        wishes_n, rewards_n = self.db.batch_counts(bid)
        if not self.ask(f"Отменить последний пакетный импорт? Будет удалено записей: "
                        f"{wishes_n + rewards_n} (круток: {wishes_n}, предметов: {rewards_n}). "
                        f"Гарант будет пересчитан."):
            return
        try:
            self.db.delete_batch(bid)
        except DatabaseError as e:
            self.error(str(e))
            return
        self.refresh()
        self.info(f"Импорт отменён, удалено записей: {wishes_n + rewards_n}.")

    def delete_selected(self):
        ids = {"wish": [], "reward": []}
        for idx in self.table.selectionModel().selectedRows():
            item = self.table.item(idx.row(), 1)
            if item is not None:
                src, rid = item.data(Qt.ItemDataRole.UserRole)
                ids[src].append(rid)
        total = len(ids["wish"]) + len(ids["reward"])
        if not total:
            self.info("Выберите строки для удаления.")
            return
        if not self.ask(f"Удалить выбранные записи ({total})? Гарант будет пересчитан."):
            return
        try:
            if ids["wish"]:
                self.db.delete_ids(ids["wish"])
            if ids["reward"]:
                self.db.delete_reward_ids(ids["reward"])
        except DatabaseError as e:
            self.error(str(e))
            return
        self.refresh()
