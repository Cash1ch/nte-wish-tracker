"""Вкладка «Симуляция»."""

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QSizePolicy, QSlider, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..catalog import (
    ARC_KNOWN, DUGA_PREFIX, rank_letter, RARITY_COLORS, ROSTER_A, ROSTER_EVENT_S, ROSTER_STANDARD_S,
)
from ..errors import blocked
from ..icons import make_pixmap, scale_smooth
from ..ui.widgets import make_button, make_combo, make_label, make_stat_card, scroll_page, SmoothIconLabel
from .calc import (
    _sim_clamp, find_portrait_path, SIM_BASE_CRIT, SIM_BASE_CRIT_DMG, SIM_BASE_REGEN, SIM_BASE_STAMINA,
    sim_calculate, SIM_CHAR_DEFAULTS, sim_character_stats, SIM_ELEMENTS, SIM_FIELDS, sim_hidden_bonus,
    SIM_HIDDEN_KINDS, sim_level_cap, sim_load_overrides, sim_marginal, SIM_MAX_LEVEL, SIM_NO_WEAPON,
    SIM_PHASE_AFFIXES, sim_phase_bonuses, SIM_PHASE_NAMES, sim_required_ascension, SIM_ROLE_BY_NAME,
    SIM_ROLES, SIM_SETTING_ARC, SIM_SETTING_CHAR, sim_skill_ratio, SIM_SLIDERS, sim_stat_weights, SIM_STYLE,
    sim_weapon_atk, SIM_WEAPON_DEFAULTS,
)


class SimulationTab(QWidget):
    """Вкладка «Симуляция»: слева арт персонажа, справа выбор персонажа и дуги, уровни,
    возвышение, характеристики, результаты расчёта, сравнение сценариев и веса статов."""

    def __init__(self, db=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.overrides = sim_load_overrides()
        self._portraits = {}
        self._portrait_src = None
        self._weapon_keys = ()
        self.setStyleSheet(SIM_STYLE)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(14)
        root.addWidget(self._build_portrait_panel(), 4)
        root.addWidget(self._build_stats_panel(), 8)

        self._fill_lists()
        self._restore_selection()
        self._load_selection()

    # ---------- построение интерфейса ----------
    def _build_portrait_panel(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("simPortrait")
        frame.setMinimumWidth(300)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(6)
        self.portrait = SmoothIconLabel()
        self.portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.portrait.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.portrait.setMinimumSize(200, 300)
        self.name_label = make_label("—", "simName")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub_label = make_label("—", "simSub", wrap=True)
        self.sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.portrait, 1)
        lay.addWidget(self.name_label)
        lay.addWidget(self.sub_label)
        return frame

    def _build_stats_panel(self) -> QWidget:
        page, lay = scroll_page()
        lay.setSpacing(12)

        pick = QGroupBox("Выбор")
        pick_l = QGridLayout(pick)
        self.char_combo = QComboBox()
        self.char_combo.setIconSize(QSize(32, 32))
        self.weapon_combo = QComboBox()
        self.weapon_combo.setIconSize(QSize(32, 32))
        self.element_combo = make_combo([(e, e) for e in SIM_ELEMENTS])
        self.role_combo = make_combo([(v[0], k) for k, v in SIM_ROLES.items()])
        self.hidden_combo = make_combo(list(SIM_HIDDEN_KINDS))
        for row, (text, widget) in enumerate((("Персонаж", self.char_combo), ("Дуга", self.weapon_combo),
                                              ("Роль (архетип)", self.role_combo),
                                              ("Стихия", self.element_combo),
                                              ("Скрытый бонус S-ранга", self.hidden_combo))):
            pick_l.addWidget(QLabel(text), row, 0)
            pick_l.addWidget(widget, row, 1)
        pick_l.addWidget(make_button("Сбросить поля", self._reset_fields), 5, 0, 1, 2)
        pick_l.setColumnStretch(1, 1)
        lay.addWidget(pick)

        cards = QGridLayout()
        self.cards = {}
        for i, (key, title, accent) in enumerate((
                ("white", "Белая АТК", "#42a5f5"), ("atk", "Общая АТК", "#42a5f5"),
                ("with_bonus", "Урон с бонусами", "#b66cff"), ("average", "Средний урон", "#66bb6a"),
                ("final", "Итоговый средний урон", "#ffd740"), ("crit_hit", "Крит-удар по цели", "#ff8a65"))):
            frame, value = make_stat_card(title, accent)
            self.cards[key] = value
            cards.addWidget(frame, i // 3, i % 3)
        lay.addLayout(cards)

        prog = QGroupBox("Характеристики на выбранном уровне")
        prog_l = QGridLayout(prog)
        self.stat_labels = {}
        for row, (key, text) in enumerate((
                ("hp", "HP персонажа"), ("char_atk", "АТК персонажа  ATK_персонаж(L)"),
                ("def", "ЗАЩ персонажа"), ("weapon_atk", "АТК дуги  ATK_оружие(L_орк)"),
                ("white", "Белая АТК  ATK_белая"), ("hidden", "Скрытый бонус возвышения"),
                ("phase", "Аффиксы фаз возвышения"), ("skill", "Эффективный % навыка"),
                ("totals", "Итого крит / крит. урон / урон"),
                ("consts", "Константы"))):
            self.stat_labels[key] = QLabel("—")
            self.stat_labels[key].setAlignment(Qt.AlignmentFlag.AlignRight)
            prog_l.addWidget(QLabel(text), row, 0)
            prog_l.addWidget(self.stat_labels[key], row, 1)
        prog_l.setColumnStretch(0, 1)
        self.asc_hint = make_label("—", "simHint", wrap=True)
        prog_l.addWidget(self.asc_hint, len(self.stat_labels), 0, 1, 2)
        lay.addWidget(prog)

        self.spins, self.sliders, self.field_labels = {}, {}, {}
        groups = {"char": QGroupBox("Уровни, дуга и характеристики"),
                  "enemy": QGroupBox("Противник"),
                  "scenario": QGroupBox("Параметры сценариев сравнения")}
        grids = {k: QGridLayout(g) for k, g in groups.items()}
        rows = {k: 0 for k in groups}
        for key, label, lo, hi, dec, step, default, suffix, group in SIM_FIELDS:
            spin = QDoubleSpinBox()
            spin.setRange(lo, hi)
            spin.setDecimals(dec)
            spin.setSingleStep(step)
            spin.setValue(default)
            spin.setSuffix(suffix)
            spin.setAlignment(Qt.AlignmentFlag.AlignRight)
            if key in ("level", "ascension"):
                spin.valueChanged.connect(lambda _v, k=key: self._sync_ascension(k))
            else:
                spin.valueChanged.connect(self._recalc)
            self.spins[key] = spin
            grid, row = grids[group], rows[group]
            rows[group] += 1
            self.field_labels[key] = QLabel(label)
            grid.addWidget(self.field_labels[key], row, 0)
            grid.addWidget(spin, row, 1)
            if key in SIM_SLIDERS:
                s_lo, s_hi, s_step = SIM_SLIDERS[key]
                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(s_lo, s_hi)
                slider.setSingleStep(s_step)
                slider.setValue(int(default))
                slider.valueChanged.connect(lambda v, k=key: self.spins[k].setValue(float(v)))
                self.sliders[key] = slider
                grid.addWidget(slider, row, 2)
            grid.setColumnStretch(2, 1)
        for group in ("char", "enemy", "scenario"):
            lay.addWidget(groups[group])

        compare = QGroupBox("Сравнение сценариев")
        compare_l = QVBoxLayout(compare)
        self.compare_table = QTableWidget(0, 8)
        self.compare_table.setHorizontalHeaderLabels(
            ["Сценарий", "Уровни (перс. / враг)", "Общая АТК", "Множитель защиты",
             "Множитель резиста", "Средний урон", "Крит-удар", "Потеря урона"])
        self.compare_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.compare_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.compare_table.setShowGrid(False)
        self.compare_table.verticalHeader().setVisible(False)
        self.compare_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.compare_table.setMinimumHeight(170)
        compare_l.addWidget(self.compare_table)
        self.compare_hint = make_label("—", "simHint", wrap=True)
        compare_l.addWidget(self.compare_hint)
        lay.addWidget(compare)

        metrics = QGroupBox("Оценка характеристик")
        metrics_l = QGridLayout(metrics)
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.1, 500)
        self.step_spin.setDecimals(1)
        self.step_spin.setValue(10.0)
        self.step_spin.setSuffix(" %")
        self.step_spin.valueChanged.connect(self._recalc)
        self.crit_value_label = QLabel("—")
        self.atk_gain_label = QLabel("—")
        self.elem_gain_label = QLabel("—")
        self.factors_label = QLabel("—")
        self.ideal_label = make_label("—", "simIdeal", wrap=True)
        rows_m = (("Шаг прироста (Δ)", self.step_spin),
                  ("Крит-масса (КМ)", self.crit_value_label),
                  ("Прирост от АТК %", self.atk_gain_label),
                  ("Прирост от стихии", self.elem_gain_label),
                  ("Множители", self.factors_label))
        for i, (text, widget) in enumerate(rows_m):
            metrics_l.addWidget(QLabel(text), i, 0)
            metrics_l.addWidget(widget, i, 1)
        metrics_l.addWidget(self.ideal_label, len(rows_m), 0, 1, 2)
        metrics_l.setColumnStretch(0, 1)
        lay.addWidget(metrics)

        weights = QGroupBox("Вес характеристик")
        weights_l = QVBoxLayout(weights)
        self.weights_table = QTableWidget(0, 4)
        self.weights_table.setHorizontalHeaderLabels(
            ["Характеристика", "Шаг", "Прирост урона", "Вес (АТК % = 1,00)"])
        self.weights_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.weights_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.weights_table.setShowGrid(False)
        self.weights_table.verticalHeader().setVisible(False)
        self.weights_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.weights_table.setMinimumHeight(320)
        weights_l.addWidget(self.weights_table)
        self.best_label = make_label("—", "simHint", wrap=True)
        weights_l.addWidget(self.best_label)
        lay.addWidget(weights)
        lay.addStretch(1)

        self.char_combo.currentIndexChanged.connect(self._on_char)
        self.weapon_combo.currentIndexChanged.connect(self._on_weapon)
        self.element_combo.currentIndexChanged.connect(self._on_element)
        self.role_combo.currentIndexChanged.connect(self._recalc)
        self.hidden_combo.currentIndexChanged.connect(self._recalc)
        return page

    # ---------- списки персонажей и дуг ----------
    def _characters(self) -> list:
        out = [(n, 5) for n in dict.fromkeys(ROSTER_EVENT_S + ROSTER_STANDARD_S)]
        out += [(n, 4) for n in ROSTER_A if n not in dict(out)]
        return out

    def _weapons(self) -> list:
        items = []
        for full, rank, _banner in ARC_KNOWN.values():
            name = full[len(DUGA_PREFIX):] if full.startswith(DUGA_PREFIX) else full
            items.append((name, rank))
        return sorted(set(items), key=lambda t: (-t[1], t[0].lower()))

    def _fill_lists(self):
        with blocked(self.char_combo, self.weapon_combo):
            self.char_combo.clear()
            for name, rank in self._characters():
                self.char_combo.addItem(QIcon(make_pixmap(name, rank, 32)),
                                        f"{name} · {rank_letter(rank)}", (name, rank))
            self.weapon_combo.clear()
            self.weapon_combo.addItem(SIM_NO_WEAPON, None)
            weapons = self._weapons()
            self._weapon_keys = tuple(weapons)
            for name, rank in weapons:
                self.weapon_combo.addItem(QIcon(make_pixmap(DUGA_PREFIX + name, rank, 32)),
                                          f"{name} · {rank_letter(rank)}", (name, rank))

    def reload_lists(self):
        """Перечитывает списки после refresh() главного окна; выбор сохраняется,
        список пересобирается только если он изменился."""
        if tuple(self._weapons()) == self._weapon_keys:
            return
        char, weapon = self.char_combo.currentData(), self.weapon_combo.currentData()
        self._fill_lists()
        with blocked(self.char_combo, self.weapon_combo):
            for combo, data in ((self.char_combo, char), (self.weapon_combo, weapon)):
                idx = combo.findData(data)
                combo.setCurrentIndex(max(idx, 0))

    def _restore_selection(self):
        if self.db is None:
            return
        for combo, key in ((self.char_combo, SIM_SETTING_CHAR), (self.weapon_combo, SIM_SETTING_ARC)):
            saved = self.db.get_setting(key, "")
            for i in range(combo.count()):
                data = combo.itemData(i)
                if data is not None and data[0] == saved:
                    with blocked(combo):
                        combo.setCurrentIndex(i)
                    break

    # ---------- профили персонажа и дуги ----------
    def _char_profile(self, name: str, rank: int) -> dict:
        prof = dict(SIM_CHAR_DEFAULTS.get(rank, SIM_CHAR_DEFAULTS[4]))
        extra = (self.overrides.get("characters") or {}).get(name)
        if isinstance(extra, dict):
            prof.update({k: v for k, v in extra.items()
                         if k in prof or k in ("element", "role", "betas")})
        for key in ("hp", "atk", "def", "alpha", "gamma", "dmg"):
            prof[key] = self._num(prof.get(key), SIM_CHAR_DEFAULTS[4][key])
        return prof

    def _weapon_profile(self, name: str, rank: int) -> dict:
        prof = dict(SIM_WEAPON_DEFAULTS.get(rank, SIM_WEAPON_DEFAULTS[3]))
        extra = (self.overrides.get("weapons") or {}).get(name)
        if isinstance(extra, dict):
            prof.update({k: v for k, v in extra.items() if k in prof})
        for key in prof:
            prof[key] = self._num(prof[key], SIM_WEAPON_DEFAULTS[3][key])
        return prof

    @staticmethod
    def _num(value, default=0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    # ---------- выбор ----------
    def _load_selection(self, *_):
        """Подставляет роль, стихию и скрытый бонус выбранного персонажа."""
        char = self.char_combo.currentData()
        if char is None:
            return
        name, rank = char
        prof = self._char_profile(name, rank)
        role = prof.get("role") if prof.get("role") in SIM_ROLES else SIM_ROLE_BY_NAME.get(name, "dps")
        element = prof.get("element") if prof.get("element") in SIM_ELEMENTS else SIM_ELEMENTS[0]
        hidden = prof.get("hidden") if prof.get("hidden") in dict((v, k) for k, v in SIM_HIDDEN_KINDS) \
            else "element_dmg"
        with blocked(self.role_combo, self.element_combo, self.hidden_combo):
            self.role_combo.setCurrentIndex(self.role_combo.findData(role))
            self.element_combo.setCurrentIndex(self.element_combo.findData(element))
            self.hidden_combo.setCurrentIndex(self.hidden_combo.findData(hidden))
        self._update_element_label()
        self._update_portrait_panel()
        self._recalc()

    def _save_selection(self):
        if self.db is not None:
            char, weapon = self.char_combo.currentData(), self.weapon_combo.currentData()
            self.db.set_setting(SIM_SETTING_CHAR, char[0] if char else "")
            self.db.set_setting(SIM_SETTING_ARC, weapon[0] if weapon else "")

    def _on_char(self, *_):
        self._save_selection()
        self._load_selection()

    def _on_weapon(self, *_):
        self._save_selection()
        self._update_portrait_panel()
        self._recalc()

    def _on_element(self, *_):
        self._update_element_label()
        self._update_portrait_panel()
        self._recalc()

    def _update_element_label(self):
        element = self.element_combo.currentData() or SIM_ELEMENTS[0]
        self.field_labels["element_dmg"].setText(f"Урон стихии ({element}) % (модули)")

    def _reset_fields(self, *_):
        with blocked(*self.spins.values()):
            for key, _l, _lo, _hi, _d, _s, default, _sf, _g in SIM_FIELDS:
                self.spins[key].setValue(default)
        self._sync_ascension("ascension")

    def _sync_ascension(self, source: str):
        """Связывает уровень и ранг возвышения: уровень выше порога повышает ранг,
        а ранг ограничивает максимальный уровень."""
        level, asc = int(self.spins["level"].value()), int(self.spins["ascension"].value())
        if source == "level":
            asc = max(asc, sim_required_ascension(level))
        else:
            level = min(level, sim_level_cap(asc))
        with blocked(self.spins["level"], self.spins["ascension"]):
            self.spins["level"].setValue(level)
            self.spins["ascension"].setValue(asc)
        self._recalc()

    # ---------- портрет ----------
    def _portrait_pixmap(self, name: str, rank: int) -> QPixmap:
        if name not in self._portraits:
            path = find_portrait_path(name)
            pm = QPixmap(str(path)) if path else QPixmap()
            if pm.isNull():
                pm = make_pixmap(name, rank, 360)
            self._portraits[name] = pm
        return self._portraits[name]

    def _update_portrait_panel(self):
        char = self.char_combo.currentData()
        if char is None:
            return
        name, rank = char
        weapon = self.weapon_combo.currentData()
        element = self.element_combo.currentData() or SIM_ELEMENTS[0]
        self.name_label.setText(name)
        arc = f"Дуга: {weapon[0]}" if weapon else SIM_NO_WEAPON
        self.sub_label.setText(f"Ранг {rank_letter(rank)} · {element}\n{arc}")
        self.name_label.setStyleSheet(f"color: {RARITY_COLORS.get(rank, '#ffd740')};")
        self._portrait_src = self._portrait_pixmap(name, rank)
        self._scale_portrait()

    def _scale_portrait(self):
        if self._portrait_src is None or self._portrait_src.isNull():
            return
        w, h = max(self.portrait.width(), 1), max(self.portrait.height(), 1)
        self.portrait.setPixmap(scale_smooth(self._portrait_src, w, h))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_portrait()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._scale_portrait)

    # ---------- расчёт ----------
    @staticmethod
    def _fmt(value: float) -> str:
        return f"{value:,.0f}".replace(",", " ")

    def _compose(self, level: int, enemy: int, asc: int):
        """Собирает параметры движка для персонажа на уровне L. Возвращает (p, info) или None."""
        char = self.char_combo.currentData()
        if char is None:
            return None
        name, rank = char
        prof = self._char_profile(name, rank)
        stats = sim_character_stats(prof, self.role_combo.currentData() or "dps", level, asc)
        weapon = self.weapon_combo.currentData()
        wp = self._weapon_profile(*weapon) if weapon else {}
        weapon_atk = sim_weapon_atk(wp, int(self.spins["weapon_level"].value())) if wp else 0.0
        hidden = sim_hidden_bonus(asc, rank)
        hidden_kind = self.hidden_combo.currentData()
        sp = {k: s.value() for k, s in self.spins.items()}
        phase = sim_phase_bonuses(int(sp["phase"]))
        skill = sim_skill_ratio(sp["skill"], sp["skill_k"], sp["skill_level"])
        p = {
            "atk_base": stats["atk"] + weapon_atk,                      # ATK_белая
            "atk_pct": sp["atk_pct"] + wp.get("atk_pct", 0.0),
            "atk_flat": sp["atk_flat"],
            "skill": skill,
            "dmg": sp["dmg"] + prof["dmg"] + wp.get("dmg", 0.0) + phase["dmg"],
            "element_dmg": sp["element_dmg"] + wp.get("element_dmg", 0.0) + phase["element_dmg"]
                           + (hidden if hidden_kind == "element_dmg" else 0.0),
            "crit": SIM_BASE_CRIT + sp["crit"] + wp.get("crit", 0.0)
                    + (hidden if hidden_kind == "crit" else 0.0),
            "crit_dmg": SIM_BASE_CRIT_DMG + sp["crit_dmg"] + wp.get("crit_dmg", 0.0) + phase["crit_dmg"],
            "level": level, "enemy_level": enemy, "resist": sp["resist"], "shred": sp["shred"],
            "def_shred": sp["def_shred"], "def_ignore": sp["def_ignore"],
        }
        info = {"hp": stats["hp"], "char_atk": stats["atk"], "def": stats["def"],
                "weapon_atk": weapon_atk, "hidden": hidden, "hidden_kind": hidden_kind,
                "phase": phase, "skill": skill}
        return p, info

    def _sync_sliders(self):
        for key, slider in self.sliders.items():
            value = int(round(self.spins[key].value()))
            with blocked(slider):
                slider.setValue(_sim_clamp(value, slider.minimum(), slider.maximum()))

    def _recalc(self, *_):
        self._sync_sliders()
        level = int(self.spins["level"].value())
        asc = int(self.spins["ascension"].value())
        enemy = int(self.spins["enemy_level"].value())
        composed = self._compose(level, enemy, asc)
        if composed is None:
            return
        p, info = composed
        r = sim_calculate(p)
        step = self.step_spin.value()

        self.cards["white"].setText(self._fmt(p["atk_base"]))
        self.cards["atk"].setText(self._fmt(r["atk"]))
        self.cards["with_bonus"].setText(self._fmt(r["with_bonus"]))
        self.cards["average"].setText(self._fmt(r["average"]))
        self.cards["final"].setText(self._fmt(r["final"]))
        self.cards["crit_hit"].setText(self._fmt(r["crit_hit"]))

        self._update_progression(p, info, level, asc)
        self.crit_value_label.setText(f"{r['crit_value']:.1f}")
        marginal = sim_marginal(p, step)
        self.atk_gain_label.setText(f"+{marginal['atk']:.2f} % за +{step:g} % АТК")
        self.elem_gain_label.setText(f"+{marginal['element']:.2f} % за +{step:g} % стихии")
        self.factors_label.setText(
            f"крит ×{r['crit_mult']:.3f} · резист ×{r['resist_factor']:.3f} · "
            f"защита ×{r['defense_factor']:.3f}")
        self._update_ideal(p, r)
        self._fill_scenarios(p, level, enemy, asc)
        self._fill_weights(p, step)

    def _update_progression(self, p: dict, info: dict, level: int, asc: int):
        lb = self.stat_labels
        lb["hp"].setText(self._fmt(info["hp"]))
        lb["char_atk"].setText(self._fmt(info["char_atk"]))
        lb["def"].setText(self._fmt(info["def"]))
        lb["weapon_atk"].setText(self._fmt(info["weapon_atk"]))
        lb["white"].setText(self._fmt(p["atk_base"]))
        kind = dict((v, k) for k, v in SIM_HIDDEN_KINDS).get(info["hidden_kind"], "")
        lb["hidden"].setText(f"+{info['hidden']:.0f} % ({kind})" if info["hidden"] else "не открыт")
        parts = [f"+{v:g} % {SIM_PHASE_NAMES[k]}" for _n, k, v in SIM_PHASE_AFFIXES
                 if info["phase"][k] > 0 and k in SIM_PHASE_NAMES]
        lb["phase"].setText(", ".join(parts) if parts else "не открыты")
        lb["skill"].setText(f"{info['skill']:.1f} %")
        lb["totals"].setText(f"{p['crit']:.1f} % / {p['crit_dmg']:.1f} % / "
                             f"{p['dmg'] + p['element_dmg']:.1f} %")
        lb["consts"].setText(f"выносливость {SIM_BASE_STAMINA} · восполнение энергии {SIM_BASE_REGEN} %")
        cap = sim_level_cap(asc)
        role = SIM_ROLES.get(self.role_combo.currentData() or "dps", SIM_ROLES["dps"])
        if level >= cap and cap < SIM_MAX_LEVEL:
            nxt = f"Достигнут предел {cap} ур. — для роста нужно возвышение до ранга {asc + 1}."
        elif cap >= SIM_MAX_LEVEL:
            nxt = "Максимальное возвышение достигнуто."
        else:
            nxt = f"Предел уровня при ранге {asc}: {cap}."
        self.asc_hint.setText(f"{nxt} Роль «{role[0]}»: приоритетный скрытый стат — {role[4]}.")

    def _update_ideal(self, p: dict, r: dict):
        ideal, cur = r["ideal_crit"], p["crit"]
        if p["crit_dmg"] / 2 > 100 and cur >= 100:
            text, color = "Шанс крита упёрся в 100 % — дальше растите крит. урон.", "#66bb6a"
        elif abs(cur - ideal) <= 2.5:
            text, color = f"Баланс критов идеальный: шанс {cur:.1f} % ≈ {ideal:.1f} % (крит. урон / 2).", "#66bb6a"
        elif cur < ideal:
            text, color = (f"Шанс крита ниже идеала: {cur:.1f} % из {ideal:.1f} % — "
                           f"выгоднее добавлять шанс крита."), "#ffb74d"
        else:
            text, color = (f"Шанс крита выше идеала: {cur:.1f} % при идеале {ideal:.1f} % — "
                           f"выгоднее добавлять крит. урон."), "#ffb74d"
        self.ideal_label.setText(text)
        self.ideal_label.setStyleSheet(f"color: {color};")

    def _fill_scenarios(self, p_now: dict, level: int, enemy: int, asc: int):
        under = int(self.spins["under_level"].value())
        boss = int(self.spins["boss_level"].value())
        under_asc = sim_required_ascension(under) if under != level else asc
        scenarios = (("Равный бой", level, level, asc),
                     ("Текущие настройки", level, enemy, asc),
                     ("Отставание от эндгейм-босса", under, boss, under_asc))
        results = []
        for title, lv, en, a in scenarios:
            composed = self._compose(lv, en, a)
            if composed is None:
                return
            results.append((title, lv, en, sim_calculate(composed[0])))
        equal_final = results[0][3]["final"]
        table = self.compare_table
        table.setRowCount(len(results))
        for i, (title, lv, en, r) in enumerate(results):
            loss = (1 - r["final"] / equal_final) * 100 if equal_final > 0 else 0.0
            cells = (title, f"{lv} / {en}", self._fmt(r["atk"]), f"{r['defense_factor']:.4f}",
                     f"{r['resist_factor']:.4f}", self._fmt(r["final"]), self._fmt(r["crit_hit"]),
                     f"−{loss:.2f} %" if loss > 0.005 else "0 %")
            for j, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if j:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if j == 7 and loss > 0.005:
                    item.setForeground(QBrush(QColor("#ff8a65")))
                table.setItem(i, j, item)
        table.resizeRowsToContents()
        # чистая потеря из-за защиты: те же статы, меняется только уровень врага
        eq_def = sim_calculate(dict(p_now, enemy_level=level))["final"]
        boss_def = sim_calculate(dict(p_now, enemy_level=boss))["final"]
        pure = (1 - boss_def / eq_def) * 100 if eq_def > 0 else 0.0
        self.compare_hint.setText(
            f"Только из-за защиты: враг {boss} ур. вместо {level} ур. снижает урон на {pure:.2f} % "
            f"при тех же характеристиках.")

    def _fill_weights(self, p: dict, step: float):
        rows = sim_stat_weights(p, step)
        table = self.weights_table
        table.setRowCount(len(rows))
        best = max(rows, key=lambda t: t[2]) if rows else None
        for i, (label, delta, gain, weight) in enumerate(rows):
            cells = (label, f"+{delta:g}", f"+{gain:.2f} %", f"{weight:.2f}".replace(".", ","))
            for j, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if j:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if best is not None and rows[i] is best:
                    item.setForeground(QBrush(QColor("#ffd740")))
                table.setItem(i, j, item)
        table.resizeRowsToContents()
        if best is not None and best[2] > 0:
            self.best_label.setText(f"Самая выгодная добавка при текущих статах: {best[0]} "
                                    f"(+{best[2]:.2f} % к итоговому урону).")
        else:
            self.best_label.setText("Недостаточно данных для оценки.")
