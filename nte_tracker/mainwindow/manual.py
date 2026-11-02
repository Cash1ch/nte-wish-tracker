"""Вкладка «Добавить»: ручное добавление круток и предметов."""

from PyQt6.QtCore import QDateTime, QSize, Qt
from PyQt6.QtGui import QIcon, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QCompleter, QDateTimeEdit, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from ..catalog import (
    ARC_BANNER, arc_kind_by_name, ARC_KINDS, BANNERS, BONUS_EVERY, BONUS_LABEL, DUGA_PREFIX,
    ITEMS_COUNT_AS_PULL, loot_aliases, loot_rarity, LOOT_TYPES, MANUAL_HIDDEN_LOOT, NO_PITY_KINDS,
    PITY_ARC_EVENT, PITY_ARC_STD, PITY_CHAR_HARD, PITY_CHAR_SOFT, rank_letter,
)
from ..config import QT_DATE_FMT, TIME_SETTING_KEY
from ..errors import blocked, DatabaseError
from ..icons import make_pixmap
from ..labels import default_reward_name
from ..ocr.names import clean_character_name, format_duga_name, format_glider_name
from ..stats import _blank_stats
from ..ui.staff_widgets import RewardCard
from ..ui.widgets import make_button, make_combo, make_label, make_rank_combo, scroll_page


class ManualMixin:
    """Вкладка «Добавить»: ручное добавление круток и предметов."""

    # ---------- запоминание времени формы ----------
    def _load_saved_dt(self, key: str) -> QDateTime:
        """Последнее сохранённое время формы (или текущее, если ничего не сохранено)."""
        saved = self.db.get_setting(key, scoped=True)
        dt = QDateTime.fromString(saved, QT_DATE_FMT) if saved else QDateTime()
        return dt if dt.isValid() else QDateTime.currentDateTime()

    def _save_form_dt(self):
        """Записывает текущее значение поля даты в БД (вызывается с задержкой)."""
        self.db.set_setting(TIME_SETTING_KEY, self.in_dt.dateTime().toString(QT_DATE_FMT),
                            scoped=True)

    # ---------- вкладка «Добавить крутку»: подвкладки «Ручная» и «Скриншот» ----------
    def _build_add(self) -> QWidget:
        self.add_tabs = QTabWidget()
        self.add_tabs.addTab(self._build_manual(), "Ручная")
        self.add_tabs.addTab(self._build_screenshot(), "Скриншот")
        self.add_tabs.addTab(self._build_mass(), "Скриншоты разом")   # НОВОЕ: 100–200+ файлов
        return self.add_tabs

    # ---------- подвкладка «Ручная» ----------
    def _build_manual(self) -> QWidget:
        page, root = scroll_page()
        box = QGroupBox("Новая добыча")
        form = QFormLayout(box)

        # 1) баннер (пул) — теперь ПЕРВАЯ строка формы; выбирается ТОЛЬКО пользователем
        self.in_banner = make_combo([(l, k) for k, l in BANNERS.items()])
        # 2) ЧТО выпало. НОВОЕ: у каждого типа в списке есть иконка (_refresh_type_icons)
        self.in_type = make_combo([(i["label"], k) for k, i in LOOT_TYPES.items()
                                   if k not in MANUAL_HIDDEN_LOOT])      # без скина на авто и кешбэка
        self.in_type.setIconSize(QSize(28, 28))
        # количество (потерянный фрагмент: 30/50, фрагмент искривления: 30)
        self.in_qty_label, self.in_qty = QLabel("Количество:"), QComboBox()
        self.in_bonus = QCheckBox(BONUS_LABEL)
        self.in_bonus.setToolTip(
            "Бонусный A предмет за каждые 10 круток. Не увеличивает счётчик круток и гарант.")
        self.in_rarity_label = QLabel("Ранг (редкость):")
        self.in_rarity = make_rank_combo()
        self.in_arc_label = QLabel("Тип S дуги:")
        self.in_arc_kind = make_combo([(l, k) for k, l in ARC_KINDS.items()])

        # название (для костюма / планера / окраски подпись меняется на «Название …»)
        self.in_name_label = QLabel("Название (необязательно):")
        self.in_name = QLineEdit()
        self.in_name.setClearButtonEnabled(True)
        # ИЗМЕНЕНО: модель подсказок со значками (QStandardItemModel вместо списка строк)
        self.name_model = QStandardItemModel(self)
        self.name_completer = QCompleter(self.name_model, self)
        self.name_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.name_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.in_name.setCompleter(self.name_completer)

        # привязка к персонажу (костюм / планер / окраска): можно выбрать из уже
        # известных персонажей (с иконками) или вписать имя вручную
        self.in_bind_label = QLabel("Привязка к персонажу:")
        self.in_bind = QComboBox()
        self.in_bind.setEditable(True)
        self.in_bind.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.in_bind.setIconSize(QSize(24, 24))
        self.in_bind.lineEdit().setPlaceholderText("Имя персонажа")
        self.in_bind.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.in_bind.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        # Время запоминается: после добавления оно НЕ сбрасывается на текущее,
        # а последнее значение сохраняется и между запусками программы.
        self.in_dt = QDateTimeEdit(self._load_saved_dt(TIME_SETTING_KEY))
        self.in_dt.setDisplayFormat(QT_DATE_FMT)
        self.in_dt.setCalendarPopup(True)
        dt_row = QHBoxLayout()
        dt_row.addWidget(self.in_dt, 1)
        dt_row.addWidget(make_button("Сейчас",
                                     lambda: self.in_dt.setDateTime(QDateTime.currentDateTime())))

        self.in_count = QSpinBox()
        self.in_count.setRange(1, 99)

        # ИЗМЕНЕНО: порядок строк. «Баннер (пул)» — в самом верху формы, выше всех
        # остальных полей; сразу под ним — «Что получено».
        # ИЗМЕНЕНО: форма остаётся чистой — только список пула; сроки и отсчёт баннера
        # перенесены на вкладку «Стафф»
        form.addRow("Баннер (пул):", self.in_banner)
        form.addRow("Что получено:", self.in_type)
        form.addRow(self.in_qty_label, self.in_qty)
        form.addRow(self.in_bonus)
        form.addRow(self.in_rarity_label, self.in_rarity)
        form.addRow(self.in_arc_label, self.in_arc_kind)
        form.addRow(self.in_name_label, self.in_name)
        form.addRow(self.in_bind_label, self.in_bind)
        form.addRow("Дата и время:", dt_row)
        form.addRow("Количество одинаковых:", self.in_count)
        root.addWidget(box)

        prev_box = QGroupBox("Предпросмотр")
        prev_l = QVBoxLayout(prev_box)
        self.preview = RewardCard(72)
        self.preview_hint = make_label(name="hint", wrap=True)
        prev_l.addWidget(self.preview)
        prev_l.addWidget(self.preview_hint)
        root.addWidget(prev_box)

        root.addWidget(make_button("Добавить", self.add_item, "primary"))
        self.add_status = make_label(name="hint", wrap=True)
        root.addWidget(self.add_status)
        root.addStretch(1)

        # Первичная настройка формы (до подключения сигналов — лишних вызовов нет)
        self._refresh_type_icons()
        self._fill_qty(self._loot())
        self._sync_form()

        # Сигналы сведены к нескольким слотам:
        #   _on_type_changed — смена типа добычи (перестраивает список количества);
        #   _sync_form       — любое изменение, влияющее на видимость полей/редкость;
        #   _update_preview  — изменения, которым нужен только пересчёт предпросмотра.
        self.in_type.currentIndexChanged.connect(self._on_type_changed)
        for sig in (self.in_banner.currentIndexChanged, self.in_rarity.currentIndexChanged,
                    self.in_bonus.toggled):
            sig.connect(self._sync_form)

        # ======================================================================
        # >>> ВОССТАНОВЛЕННЫЙ ХВОСТ <<<
        # Всё, что выше этой строки, — ваш код. Всё ниже (до конца файла) в присланном
        # файле отсутствовало (файл был обрезан) и написано заново по вашим
        # вспомогательным функциям и описанию в docstring. Если у вас сохранился
        # оригинальный хвост — подставьте его вместо этого блока. Музыка от него
        # не зависит.
        # ======================================================================
        self.in_arc_kind.currentIndexChanged.connect(self._update_preview)
        self.in_qty.currentIndexChanged.connect(self._update_preview)
        self.in_name.textChanged.connect(self._update_preview)
        self.in_bind.editTextChanged.connect(self._update_preview)
        self.in_name.editingFinished.connect(self._autofill_rank)
        self.name_completer.activated[str].connect(self._autofill_rank)
        # Время формы пишется в БД с задержкой (debounce) и НЕ сбрасывается на текущее
        self.in_dt.dateTimeChanged.connect(lambda *_: self._dt_timer.start())
        return page

    # ---------- логика формы «Ручная» ----------
    def _loot(self) -> dict:
        """Описание выбранного типа добычи (элемент LOOT_TYPES)."""
        return LOOT_TYPES[self.in_type.currentData()]

    def _refresh_type_icons(self):
        """Значки в списке «Что получено» (нет файла — заглушка с инициалами)."""
        for i in range(self.in_type.count()):
            key = self.in_type.itemData(i)
            info = LOOT_TYPES[key]
            pm = make_pixmap(info["default"], loot_rarity(info) or 5, 28, loot_aliases(key))
            self.in_type.setItemIcon(i, QIcon(pm))

    def _fill_qty(self, info: dict):
        """Заполняет список количества (потерянный фрагмент: 30/50, искривления: 30)."""
        with blocked(self.in_qty):
            self.in_qty.clear()
            for q in info.get("qty") or ():
                self.in_qty.addItem(f"{q} шт", q)

    def _sync_form(self, *_):
        """Показывает только те поля, которые нужны выбранному типу добычи."""
        info = self._loot()
        wish = info["mode"] == "wish"
        self.in_bonus.setVisible(wish)
        if not wish and self.in_bonus.isChecked():
            with blocked(self.in_bonus):
                self.in_bonus.setChecked(False)
        bonus = wish and self.in_bonus.isChecked()
        if bonus:  # бонусная добыча всегда ранга A
            with blocked(self.in_rarity):
                self.in_rarity.setCurrentIndex(self.in_rarity.findData(4))
        self.in_rarity.setEnabled(not bonus)
        self._set_row_visible(self.in_rarity_label, self.in_rarity, wish)

        arc_visible = (wish and self.in_banner.currentData() == ARC_BANNER
                       and self.in_rarity.currentData() == 5 and not bonus)
        self._set_row_visible(self.in_arc_label, self.in_arc_kind, arc_visible)
        self._set_row_visible(self.in_qty_label, self.in_qty, bool(info.get("qty")))
        self._set_row_visible(self.in_name_label, self.in_name, not info.get("hide_name"))
        self.in_name_label.setText(info.get("name_label", "Название (необязательно):"))
        self.in_name.setPlaceholderText(f"Если пусто — будет «{info['default']}»")
        self._set_row_visible(self.in_bind_label, self.in_bind, bool(info.get("bind")))
        self._update_preview()

    def _on_type_changed(self, *_):
        self._fill_qty(self._loot())
        self._sync_form()

    def _form_rarity(self, info: dict) -> int:
        """Ранг записи: жёсткий у предметов и кешбэка, иначе из формы (бонус — всегда A)."""
        fixed = loot_rarity(info)
        if fixed is not None:
            return fixed
        return 4 if self.in_bonus.isChecked() else self.in_rarity.currentData()

    def _form_detail(self, info: dict) -> str:
        """Поле detail предмета: имя персонажа (привязка), количество или фикс. значение."""
        if info.get("bind"):
            return self.in_bind.currentText().strip()
        if info.get("qty"):
            return self.in_qty.currentData() or ""
        return info.get("detail", "")

    def _form_name(self, info: dict) -> str:
        """Итоговое название: введённое пользователем (очищенное) или название типа.
        Поле названия необязательно — пустое заменяется названием выбранного типа."""
        key = self.in_type.currentData()
        raw = "" if info.get("hide_name") else self.in_name.text().strip()
        if info["mode"] == "reward":
            if info.get("kind") == "glider" and raw:
                return format_glider_name(raw) or raw      # всегда «Планер - Название»
            return raw or default_reward_name(info["kind"], self._form_detail(info))
        if key == "arc":
            return format_duga_name(raw) or info["default"]  # всегда «Дуга - Название»
        if key == "character":
            return clean_character_name(raw) or info["default"]
        return raw or info["default"]

    def _autofill_rank(self, text=None):
        """Если введено известное имя — ранг подставляется из истории."""
        info = self._loot()
        if info["mode"] != "wish" or self.in_bonus.isChecked():
            return
        raw = (text if isinstance(text, str) else self.in_name.text()).strip()
        name = format_duga_name(raw) if self.in_type.currentData() == "arc" \
            else clean_character_name(raw)
        hit = self.known.get(name.lower())
        if hit:
            idx = self.in_rarity.findData(hit[1])
            if idx >= 0 and idx != self.in_rarity.currentIndex():
                with blocked(self.in_rarity):
                    self.in_rarity.setCurrentIndex(idx)
                self._sync_form()

    @staticmethod
    def _pity_violation(banner: str, rarity: int, s: dict):
        """Текст предупреждения, если не-S крутка противоречит жёсткому гаранту; иначе None."""
        if rarity == 5:
            return None
        if banner == ARC_BANNER:
            cs, ce = s["counter_std"] + 1, s["counter_ev"] + 1
            if cs >= PITY_ARC_STD:
                return (f"Это {cs}-я крутка без стандартной S дуги — по гарантии "
                        f"({PITY_ARC_STD}) должна выпасть S дуга.")
            if ce >= PITY_ARC_EVENT:
                return (f"Это {ce}-я крутка без ивентовой S дуги — по гарантии "
                        f"({PITY_ARC_EVENT}) должна выпасть ивентовая S дуга.")
            return None
        c = s["counter"] + 1
        if c >= PITY_CHAR_HARD:
            return (f"Это {c}-я крутка без S — на жёстком гаранте ({PITY_CHAR_HARD}) "
                    f"должна выпасть S.")
        return None

    def _update_preview(self, *_):
        """Плашка предпросмотра и подсказка про гарант для текущего состояния формы."""
        info, key = self._loot(), self.in_type.currentData()
        banner, mode = self.in_banner.currentData(), info["mode"]
        rarity, name = self._form_rarity(info), self._form_name(info)
        s = self.stats.get(banner) or _blank_stats()
        total, c5 = s["total"], s["counter"] + 1
        cs, ce = s["counter_std"] + 1, s["counter_ev"] + 1
        letter = rank_letter(rarity)

        if mode == "reward":
            detail = self._form_detail(info)
            badge = f"{letter} · {info['label']}" + (
                f" → {detail}" if info.get("bind") and detail else "")
            if info.get("no_pity"):
                hint = ("Дополнительная добыча ивента: НЕ прибавляет счётчик круток и не "
                        "влияет на гарант.")
            elif ITEMS_COUNT_AS_PULL:
                hint = (f"Предмет займёт крутку №{total + 1} на этом баннере, но НЕ сбросит "
                        f"гарант и не войдёт в статистику S/A.")
            else:
                hint = "Предмет сохраняется отдельно и не затрагивает счётчики круток и гарант."
        elif mode == "cashback":
            badge = f"{letter} · {info['label']} · крутка №{total + 1}"
            hint = "Кешбэк считается круткой, но гарант S не сбрасывает."
        elif self.in_bonus.isChecked():
            available = total // BONUS_EVERY - s["bonus"]
            badge = f"A · {BONUS_LABEL}"
            hint = (f"Эта запись не увеличивает счётчик круток и гарант. Бонусов доступно на "
                    f"баннере: {max(0, available)} (основных круток: {total}).")
        elif banner == ARC_BANNER:
            if rarity == 5:
                kind = self.in_arc_kind.currentData()
                badge = f"S · {ARC_KINDS.get(kind, '')} · гарант S: {c5}"
                if kind == "event":
                    hint = ("После этой крутки будут сброшены оба счётчика: стандартной "
                            "и ивентовой S дуги.")
                else:
                    hint = ("После этой крутки будет сброшен счётчик стандартной S дуги; "
                            "счётчик ивентовой S дуги продолжит расти.")
            else:
                badge = f"{letter} · крутка №{total + 1}"
                hint = (f"После этой крутки: стандартная дуга — {cs}/{PITY_ARC_STD}, "
                        f"ивентовая — {ce}/{PITY_ARC_EVENT}.")
        elif rarity == 5:
            badge = f"S · гарант S: {c5}"
            hint = "После этой крутки счётчик S будет сброшен."
        else:
            badge = f"{letter} · крутка №{total + 1} · гарант S: {c5}"
            if c5 >= PITY_CHAR_HARD:
                hint = (f"⚠ Это {c5}-я крутка без S — на жёстком гаранте ({PITY_CHAR_HARD}) "
                        f"должна выпасть S. Проверьте ранг.")
            elif c5 >= PITY_CHAR_SOFT:
                hint = (f"Мягкий гарант: с {PITY_CHAR_SOFT}-й крутки шанс S повышен. "
                        f"До жёсткого гаранта: {PITY_CHAR_HARD - c5}.")
            else:
                hint = (f"После этой крутки гарант S — {c5}/{PITY_CHAR_HARD} "
                        f"(мягкий гарант с {PITY_CHAR_SOFT}-й).")
        aliases = loot_aliases(key) if mode != "wish" else ()
        self.preview.set_data(name, rarity, badge, BANNERS.get(banner, ""), aliases)
        self.preview_hint.setText(hint)

    def _refresh_add_helpers(self):
        """Подсказки названий (со значками) и список персонажей для привязки."""
        names = sorted(self.known.values(), key=lambda v: v[0].lower())
        self.name_model.clear()
        for name, rank, _banner in names:
            self.name_model.appendRow(QStandardItem(QIcon(make_pixmap(name, rank, 24)), name))
        current = self.in_bind.currentText()
        with blocked(self.in_bind):
            self.in_bind.clear()
            for name, rank, banner in names:
                if banner != ARC_BANNER and not name.startswith(DUGA_PREFIX):
                    self.in_bind.addItem(QIcon(make_pixmap(name, rank, 24)), name)
            self.in_bind.setEditText(current)
        self._update_preview()

    def add_item(self):
        """Единая точка добавления: крутка (персонаж / дуга / кешбэк) или предмет.
        Время формы НЕ сбрасывается — запоминается последнее введённое значение."""
        info = self._loot()
        banner, count = self.in_banner.currentData(), self.in_count.value()
        when = self.in_dt.dateTime()
        stamp = when.toString(QT_DATE_FMT)
        rarity, name, mode = self._form_rarity(info), self._form_name(info), info["mode"]
        s = self.stats.get(banner) or _blank_stats()
        bonus = mode == "wish" and self.in_bonus.isChecked()

        if mode == "reward":
            rec = {"kind": info["kind"], "name": name, "detail": self._form_detail(info),
                   "obtained_at": stamp, "banner": banner,
                   "no_pity": int(bool(info.get("no_pity")) or info["kind"] in NO_PITY_KINDS)}
            save, tail = self.db.add_rewards, "предмет"
        else:
            if bonus:
                available = s["total"] // BONUS_EVERY - s["bonus"]
                if available < count and not self.ask(
                        f"На этом баннере доступно бонусов: {max(0, available)} "
                        f"(за каждые {BONUS_EVERY} основных круток), а вы добавляете {count}.\n"
                        f"Всё равно добавить?"):
                    return
            elif mode == "wish":
                msg = self._pity_violation(banner, rarity, s)
                if msg and not self.ask(msg + f"\nВсё равно добавить {rank_letter(rarity)}?"):
                    return
            arc_kind = ""
            if mode == "wish" and banner == ARC_BANNER and rarity == 5 and not bonus:
                arc_kind = arc_kind_by_name(name, self.in_arc_kind.currentData())
            rec = {"banner": banner, "rarity": rarity, "name": name, "pulled_at": stamp,
                   "is_bonus": int(bonus), "arc_kind": arc_kind,
                   "cashback": info.get("cashback", "") if mode == "cashback" else ""}
            save = self.db.add_many
            tail = "доп. добыча (бонус)" if bonus else "крутка"

        try:
            save([dict(rec) for _ in range(count)])
        except DatabaseError as e:
            self.error(str(e))
            return
        self._dt_timer.stop()
        self._save_form_dt()  # запоминаем введённое время (форма его не сбрасывает)
        self.refresh()
        self.in_name.clear()
        self.in_count.setValue(1)
        suffix = f" × {count}" if count > 1 else ""
        self.add_status.setText(f"Добавлено: {name}{suffix} — {BANNERS[banner]} ({tail})")
