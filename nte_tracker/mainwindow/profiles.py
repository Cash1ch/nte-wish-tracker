"""Настройки, профили игроков и оформление."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from ..catalog import BANNER_PANEL_KEYS
from ..config import ANIM_DEFAULT_EFFECT, ANIM_EFFECT_KEY, ANIM_EFFECTS, ANIM_ENABLED_KEY, TIME_SETTING_KEY
from ..errors import blocked, DatabaseError
from ..ui.profile_dialog import ProfileNameDialog
from ..ui.widgets import make_button, make_label, scroll_page


class ProfilesMixin:
    """Настройки, профили игроков и оформление."""

    # ---------- НОВОЕ: вкладка «Настройки» ----------
    def _build_settings(self) -> QWidget:
        self.settings_tabs = QTabWidget()
        self.settings_tabs.addTab(self._build_visuals(), "Визуал")
        self.settings_tabs.addTab(self._build_profile(), "Профиль")
        self.settings_tabs.addTab(self._build_io(), "Импорт / Экспорт")
        return self.settings_tabs

    def _build_visuals(self) -> QWidget:
        page, root = scroll_page()
        box = QGroupBox("Фоновая анимация")
        box_l = QVBoxLayout(box)

        self.anim_check = QCheckBox("Включить падающую анимацию на вкладке «Стафф»")
        self.anim_check.setChecked(self._anim_enabled)
        box_l.addWidget(self.anim_check)

        row = QHBoxLayout()
        row.addWidget(QLabel("Эффект:"))
        self.anim_combo = QComboBox()
        for key, title in ANIM_EFFECTS:
            self.anim_combo.addItem(title, key)
        self.anim_combo.setCurrentIndex(max(0, self.anim_combo.findData(self._anim_effect)))
        self.anim_combo.setEnabled(self._anim_enabled)
        row.addWidget(self.anim_combo)
        row.addStretch(1)
        box_l.addLayout(row)

        box_l.addWidget(make_label(
            "Снежинки — медленное падение с плавным вращением по часовой стрелке.\n"
            "Листочки — падение с медленным покачиванием из стороны в сторону.\n"
            "Звёздочки — диагональное падение от левого края с вращением по часовой стрелке.",
            "hint", wrap=True))
        root.addWidget(box)
        root.addStretch(1)

        self.anim_check.toggled.connect(self._on_anim_changed)
        self.anim_combo.currentIndexChanged.connect(self._on_anim_changed)
        return page

    # ---------- НОВОЕ: подвкладка «Профиль» (внутри «Настройки») ----------
    def _build_profile(self) -> QWidget:
        page, root = scroll_page()

        cur = QGroupBox("Активный профиль")
        cur_l = QVBoxLayout(cur)
        self.profile_current_lbl = QLabel()
        self.profile_current_lbl.setStyleSheet("color: #ffd740; font-size: 18px; font-weight: bold;")
        cur_l.addWidget(self.profile_current_lbl)
        cur_l.addWidget(make_label(
            "У каждого профиля своя история круток и предметов, свой гарант и свои баннеры. "
            "При переключении все вкладки обновляются.", "hint", wrap=True))
        root.addWidget(cur)

        box = QGroupBox("Профили")
        box_l = QVBoxLayout(box)
        self.profile_list = QListWidget()
        self.profile_list.setMinimumHeight(160)
        self.profile_list.itemDoubleClicked.connect(lambda *_: self._profile_switch())
        self.profile_list.currentRowChanged.connect(lambda *_: self._update_profile_buttons())
        box_l.addWidget(self.profile_list)
        row = QHBoxLayout()
        self.profile_switch_btn = make_button("Переключиться", self._profile_switch, "primary")
        self.profile_new_btn = make_button("Создать…", self._profile_create)
        self.profile_rename_btn = make_button("Переименовать…", self._profile_rename)
        self.profile_delete_btn = make_button("Удалить", self._profile_delete, "danger")
        for btn in (self.profile_switch_btn, self.profile_new_btn,
                    self.profile_rename_btn, self.profile_delete_btn):
            row.addWidget(btn)
        box_l.addLayout(row)
        root.addWidget(box)
        root.addStretch(1)
        return page

    def _selected_profile_id(self):
        item = self.profile_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _refresh_profile_ui(self):
        if getattr(self, "profile_list", None) is None:
            return
        try:
            profiles = self.db.list_profiles()
        except DatabaseError as e:
            self.error(str(e))
            return
        keep = self._selected_profile_id()
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        active_row = 0
        for i, prof in enumerate(profiles):
            is_active = prof["id"] == self.db.profile_id
            text = f"{prof['name']} — круток: {prof['wishes_n']}, предметов: {prof['rewards_n']}"
            item = QListWidgetItem(text + ("   (активный)" if is_active else ""))
            item.setData(Qt.ItemDataRole.UserRole, prof["id"])
            if is_active:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                active_row = i
            self.profile_list.addItem(item)
            if keep is not None and prof["id"] == keep:
                active_row = i
        if profiles:
            self.profile_list.setCurrentRow(active_row)
        self.profile_list.blockSignals(False)
        active = next((p for p in profiles if p["id"] == self.db.profile_id), None)
        self.profile_current_lbl.setText(active["name"] if active else "—")
        self._update_profile_buttons()

    def _update_profile_buttons(self):
        pid = self._selected_profile_id()
        total = self.profile_list.count()
        has = pid is not None
        self.profile_switch_btn.setEnabled(has and pid != self.db.profile_id)
        self.profile_rename_btn.setEnabled(has)
        self.profile_delete_btn.setEnabled(has and total > 1)

    def _sync_profile_state(self):
        """Подтягивает данные активного профиля: время формы, отметки баннеров, все вкладки."""
        with blocked(self.in_dt):
            self.in_dt.setDateTime(self._load_saved_dt(TIME_SETTING_KEY))
        info = getattr(self, "_banner_info", None)
        if info:
            self._stamp_banner_activation(info)
            for pool_key in BANNER_PANEL_KEYS:
                self.pools[pool_key].set_banners(info)
        self.refresh()

    def _switch_to_profile(self, pid: int):
        if pid == self.db.profile_id:
            return
        if self._dt_timer.isActive():     # время формы дописывается в профиль, который покидаем
            self._dt_timer.stop()
            self._save_form_dt()
        try:
            self.db.set_active_profile(pid)
        except DatabaseError as e:
            self.error(str(e))
            return
        self._sync_profile_state()

    def _profile_switch(self):
        pid = self._selected_profile_id()
        if pid is not None:
            self._switch_to_profile(pid)

    def _profile_create(self):
        dlg = ProfileNameDialog(self.db, self, "Новый профиль", "Введите никнейм нового профиля")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            pid = self.db.create_profile(dlg.name)
        except DatabaseError as e:
            self.error(str(e))
            return
        self._refresh_profile_ui()
        if self.ask(f"Профиль «{dlg.name}» создан. Переключиться на него?", "Новый профиль"):
            self._switch_to_profile(pid)

    def _profile_rename(self):
        pid = self._selected_profile_id()
        if pid is None:
            return
        old = next((p["name"] for p in self.db.list_profiles() if p["id"] == pid), "")
        dlg = ProfileNameDialog(self.db, self, "Переименование профиля", "Новый никнейм",
                                text=old, ok_text="Сохранить", exclude_id=pid)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.db.rename_profile(pid, dlg.name)
        except DatabaseError as e:
            self.error(str(e))
            return
        self._update_profile_label()
        self._refresh_profile_ui()

    def _profile_delete(self):
        pid = self._selected_profile_id()
        if pid is None:
            return
        profiles = self.db.list_profiles()
        prof = next((p for p in profiles if p["id"] == pid), None)
        if prof is None:
            return
        if len(profiles) <= 1:
            self.warn("Нельзя удалить единственный профиль.")
            return
        if not self.ask(f"Удалить профиль «{prof['name']}» вместе со всеми его крутками "
                        f"({prof['wishes_n']}) и предметами ({prof['rewards_n']})? "
                        f"Это действие необратимо."):
            return
        was_active = pid == self.db.profile_id
        if was_active and self._dt_timer.isActive():
            self._dt_timer.stop()
        try:
            self.db.delete_profile(pid)
        except DatabaseError as e:
            self.error(str(e))
            return
        if was_active:
            self._sync_profile_state()
        else:
            self._refresh_profile_ui()

    def _on_anim_changed(self, *_):
        self._anim_enabled = self.anim_check.isChecked()
        self._anim_effect = self.anim_combo.currentData() or ANIM_DEFAULT_EFFECT
        self.anim_combo.setEnabled(self._anim_enabled)
        self.staff_anim.configure(self._anim_enabled, self._anim_effect)
        self.db.set_setting(ANIM_ENABLED_KEY, "1" if self._anim_enabled else "0")
        self.db.set_setting(ANIM_EFFECT_KEY, self._anim_effect)
