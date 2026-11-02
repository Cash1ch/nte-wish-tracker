"""Импорт / экспорт (JSON, CSV), резервные копии и очистка данных."""

import csv
import json
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QGroupBox, QHBoxLayout, QVBoxLayout, QWidget

from ..errors import DatabaseError
from ..exporting import build_export_payload
from ..importing import (
    load_csv_records, load_json_rewards, normalize_all, normalize_record, normalize_reward, parse_game_logs,
)
from ..paths import asset_dirs
from ..ui.profile_dialog import ensure_profile
from ..ui.widgets import make_button, make_label, scroll_page


class DataIoMixin:
    """Импорт / экспорт (JSON, CSV), резервные копии и очистка данных."""

    # ---------- подвкладка «Импорт / Экспорт» (внутри «Настройки») ----------
    def _build_io(self) -> QWidget:
        page, root = scroll_page()

        imp = QGroupBox("Импорт")
        imp_l = QVBoxLayout(imp)
        imp_l.addWidget(make_label(
            "Поддерживаются файлы JSON и CSV с полями: banner, rarity (S / A / B), name, "
            "pulled_at (необязательно: is_bonus, arc_kind, cashback). JSON может содержать "
            "ещё и список rewards.\nУже существующие записи пропускаются. Старые баннеры "
            "(limited_character, standard, weapon) переносятся автоматически; записи "
            "«Новичкового» баннера не импортируются.", "hint", wrap=True))
        imp_l.addWidget(make_button("Импортировать из файла (JSON / CSV / лог)…",
                                    self.import_file, "primary"))
        root.addWidget(imp)

        exp = QGroupBox("Экспорт")
        exp_l = QHBoxLayout(exp)
        exp_l.addWidget(make_button("Экспорт круток в CSV…", self.export_csv))
        exp_l.addWidget(make_button("Экспорт в JSON (крутки + предметы)…", self.export_json))
        root.addWidget(exp)

        bak = QGroupBox("Резервная копия базы данных")
        bak_l = QVBoxLayout(bak)
        path_lbl = make_label(f"Рабочая база: {self.db.path}", "hint", wrap=True)
        path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bak_l.addWidget(path_lbl)
        row = QHBoxLayout()
        row.addWidget(make_button("Создать копию…", self.backup_db))
        row.addWidget(make_button("Восстановить из копии…", self.restore_db))
        bak_l.addLayout(row)
        root.addWidget(bak)

        icons = QGroupBox("Иконки")
        icons_l = QVBoxLayout(icons)
        icons_hint = make_label(
            "Положите картинки (png / jpg / webp) в одну из папок. Имя файла = название "
            "предмета, например «Имя Персонажа.png»:\n" + "\n".join(str(d) for d in asset_dirs()),
            "hint", wrap=True)
        icons_hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        icons_l.addWidget(icons_hint)
        icons_l.addWidget(make_button("Перечитать иконки", self.refresh))
        root.addWidget(icons)

        danger = QGroupBox("Опасная зона")
        danger_l = QHBoxLayout(danger)
        danger_l.addWidget(make_button("Удалить все крутки", self.clear_all, "danger"))
        danger_l.addWidget(make_button("Удалить все предметы", self.clear_all_rewards, "danger"))
        root.addWidget(danger)
        root.addStretch(1)
        return page

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт круток", "", "Данные (*.json *.csv *.log *.txt);;Все файлы (*)")
        if not path:
            return
        p, raw_rewards = Path(path), []
        try:
            if p.suffix.lower() == ".csv":
                raw = load_csv_records(p)
            else:
                raw = parse_game_logs(path)
                if p.suffix.lower() == ".json":
                    raw_rewards = load_json_rewards(p)
        except NotImplementedError as e:
            self.warn(str(e))
            return
        except (OSError, ValueError, UnicodeDecodeError, csv.Error) as e:
            self.error(f"Не удалось прочитать файл:\n{e}")
            return

        valid, errors = normalize_all(raw, normalize_record, "запись")
        valid_rw, errors_rw = normalize_all(raw_rewards, normalize_reward, "предмет")
        all_errors = errors + errors_rw
        if not valid and not valid_rw:
            msg = "В файле не найдено корректных записей."
            if all_errors:
                msg += "\n\n" + "\n".join(all_errors[:10])
            self.warn(msg)
            return

        text = f"Найдено корректных записей: {len(valid)}"
        if raw_rewards:
            text += f"\nНайдено предметов: {len(valid_rw)}"
        if all_errors:
            text += f"\nПропущено с ошибками: {len(all_errors)}\n" + "\n".join(all_errors[:5])
            text += "\n…" if len(all_errors) > 5 else ""
        if not self.ask(text + "\n\nИмпортировать?"):
            return
        try:
            added, skipped, added_rw, skipped_rw = self.db.import_file_ordered(valid, valid_rw)
        except DatabaseError as e:
            self.error(str(e))
            return
        self.refresh()
        msg = f"Добавлено: {added}\nПропущено (дубликаты): {skipped}"
        if valid_rw:
            msg += f"\n\nПредметы: добавлено {added_rw}, пропущено {skipped_rw}"
        self.info(msg)

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт в CSV", "nte_wishes.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                wr = csv.DictWriter(f, fieldnames=["seq", "banner", "rarity", "name", "pulled_at",
                                                   "is_bonus", "arc_kind", "cashback"])
                wr.writeheader()
                # seq — сквозной номер в общей хронологии (как в JSON-экспорте)
                payload = build_export_payload(self.db.fetch_all(), self.db.fetch_rewards())
                wr.writerows(payload["records"])
        except OSError as e:
            self.error(f"Не удалось сохранить файл:\n{e}")
            return
        self.info(f"Экспортировано записей: {len(self.rows)}")

    def _profile_name_safe(self) -> str:
        try:
            for p in self.db.list_profiles():
                if p.get("id") == self.db.profile_id:
                    return str(p.get("name") or "")
        except Exception:
            pass
        return ""

    def export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт в JSON", "nte_wishes.json", "JSON (*.json)")
        if not path:
            return
        try:
            # свежие данные прямо из базы: в них есть id и seq, по которым строится порядок
            rows, rewards = self.db.fetch_all(), self.db.fetch_rewards()
            data = build_export_payload(rows, rewards, self._profile_name_safe())
        except (DatabaseError, KeyError) as e:
            self.error(f"Не удалось подготовить данные:\n{e}")
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            self.error(f"Не удалось сохранить файл:\n{e}")
            return
        self.info(f"Экспортировано круток: {len(rows)}\n"
                  f"Экспортировано предметов: {len(rewards)}")

    def backup_db(self):
        default = f"nte_wishes_backup_{datetime.now():%Y%m%d_%H%M%S}.db"
        path, _ = QFileDialog.getSaveFileName(
            self, "Резервная копия", default, "SQLite (*.db *.sqlite);;Все файлы (*)")
        if not path:
            return
        try:
            self.db.backup_to(path)
        except DatabaseError as e:
            self.error(str(e))
            return
        self.info("Резервная копия создана.")

    def restore_db(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Восстановление базы", "", "SQLite (*.db *.sqlite);;Все файлы (*)")
        if not path:
            return
        if not self.ask("Текущие данные будут заменены данными из выбранной копии. Продолжить?"):
            return
        try:
            self.db.restore_from(path)
        except DatabaseError as e:
            self.error(str(e))
            return
        if not ensure_profile(self.db, self):       # копия из старой версии: профилей нет
            try:
                self.db.create_profile("Игрок")
            except DatabaseError as e:
                self.error(str(e))
        self._sync_profile_state()
        self.info("База данных восстановлена.")

    def clear_all(self):
        if not self.rows:
            self.info("Круток в базе данных нет.")
            return
        if not self.ask(f"Удалить ВСЕ крутки ({len(self.rows)})? Это действие необратимо."):
            return
        if not self.ask("Точно удалить всё? Рекомендуется сначала сделать резервную копию."):
            return
        try:
            self.db.clear_all()
        except DatabaseError as e:
            self.error(str(e))
            return
        self.refresh()

    def clear_all_rewards(self):
        if not self.rewards:
            self.info("Предметов в базе данных нет.")
            return
        if not self.ask(f"Удалить ВСЕ предметы ({len(self.rewards)})? Это действие необратимо."):
            return
        try:
            self.db.clear_rewards()
        except DatabaseError as e:
            self.error(str(e))
            return
        self.refresh()
