"""Раскладка FlowLayout и страница одного пула."""

from datetime import datetime

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtWidgets import QCheckBox, QGroupBox, QHBoxLayout, QLayout, QVBoxLayout, QWidget

from ..catalog import (
    ARC_BANNER, arc_kind_by_name, ARC_POOL_ROSTERS, arc_short_name, BANNER_PANEL_KEYS, BONUS_EVERY,
    DROP_HISTORY_NEWEST_FIRST, EVENT_BANNER, PITY_ARC_EVENT, PITY_ARC_STD, PITY_CHAR_HARD, PITY_CHAR_SOFT,
    POOL_ROSTERS, RARITY_COLORS, STANDARD_BANNER,
)
from ..labels import arc_event_only_stats, fmt_avg
from .banners import (
    arc_period_stats, banner_countdown, banner_period_stats, banner_pull_window, BannerCard, BannerDashboard,
    count_banner_period_pulls,
)
from .staff_widgets import (
    arc_roster_counts, CharTile, clear_grid, CUBE_TITLES, DiceChip, pity_color, POOL_CUBES, roster_counts,
    roster_key,
)
from .widgets import make_label, make_pity_widget, make_stat_card, scroll_page, set_bar, set_last


class FlowLayout(QLayout):
    """НОВОЕ: адаптивная «потоковая» сетка. Плитки идут слева направо и переносятся на
    следующую строку по ширине контейнера: окно шире — в строке больше плиток, уже — плитки
    переносятся вниз (высота зависит от ширины: hasHeightForWidth)."""

    def __init__(self, parent=None, h_spacing: int = 12, v_spacing: int = 14):
        super().__init__(parent)
        self._items = []
        self._hs, self._vs = h_spacing, v_spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)
        self.invalidate()

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            item = self._items.pop(index)
            self.invalidate()
            return item
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, row_h = area.x(), area.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if item.widget() is not None and not item.widget().isVisibleTo(item.widget().parentWidget()):
                continue
            if x > area.x() and x + hint.width() > area.right() + 1:   # не влезает — новая строка
                x = area.x()
                y += row_h + self._vs
                row_h = 0
            if not test_only:
                item.setGeometry(QRect(x, y, hint.width(), hint.height()))
            x += hint.width() + self._hs
            row_h = max(row_h, hint.height())
        return y + row_h - rect.y() + m.bottom()



class PoolPage(QWidget):
    """Независимая страница одного баннера: карточки, плашки кубиков, гарант. ИЗМЕНЕНО:
    блоки «Последние награды A и S» и «Предметы, кубики и кешбэк» удалены; у персонажных
    пулов добавлены история выпадений S и составы персонажей (POOL_ROSTERS)."""

    # ОБНОВЛЕНО: карточки «Всего A (из круток)» и «Бонусная добыча (A)» удалены — остались
    # три главные метрики; (заголовок, цвет акцента)
    CARD_TITLES = ("Всего круток", "Всего S", "Средний гарант (S)")
    CARD_ACCENTS = ("#8ab4ff", "#ffd740", "#7be0a8")
    TILE_ALIGN = Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft

    def __init__(self, key: str):
        super().__init__()
        self.key = key
        # НОВОЕ: состояние панели баннеров (только у ивентового пула)
        self._stats, self._history, self._banner_info = None, [], None
        self._entries = (None, None)       # (текущий баннер, реран) для лёгкого тика таймера
        page, root = scroll_page()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)

        # ОБНОВЛЕНО: три стеклянные карточки на всю ширину панели, растяжка одинаковая
        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.cards = []
        for title, accent in zip(self.CARD_TITLES, self.CARD_ACCENTS):
            frame, value = make_stat_card(title, accent)
            cards.addWidget(frame, 1)          # равные доли ширины
            self.cards.append(value)
        root.addLayout(cards)

        # ИЗМЕНЕНО: плашки кубиков только тех видов, что падают на этом баннере
        # (POOL_CUBES); у «Дуг» плашек нет и строка вообще не создаётся
        self.chips = {}
        cube_kinds = POOL_CUBES.get(key, ())
        if cube_kinds:
            chips = QHBoxLayout()
            chips.setSpacing(8)
            for kind in cube_kinds:
                chip = DiceChip(kind, CUBE_TITLES[kind])
                chips.addWidget(chip)
                self.chips[kind] = chip
            chips.addStretch(1)
            root.addLayout(chips)

        # ИЗМЕНЕНО: у ивентового пула блок «Ивентовые персонажи — сводка» удалён полностью:
        # остаются карточки счётчиков, плашки кубиков, панель баннеров, история выпадений S
        # и составы персонажей. Поля сводки у этого пула не создаются (None / пустые словари).
        self.rar = self.bonus = self.since = None
        self.pity, self.last = {}, {}
        self.is_arc = key == ARC_BANNER
        if key in BANNER_PANEL_KEYS:
            self.dash = BannerDashboard(arc=self.is_arc)
            root.addWidget(self.dash)
        else:
            self._build_summary_box(root)

        self.drop_grid = self.drop_empty = None
        self.hide_std_cb = None
        self.roster_boxes = []  # (группа, сетка, заголовок, ранг, состав)
        if key in POOL_ROSTERS or key in ARC_POOL_ROSTERS:
            self._build_character_sections(root)
        root.addStretch(1)

    def _build_summary_box(self, root: QVBoxLayout):
        """Отдельная плашка с полосой гаранта (пул «Стандартный персонаж»)."""
        key = self.key
        self.rar = self.bonus = self.since = None
        self.pity, self.last = {}, {}
        if key != STANDARD_BANNER:
            return
        box = QGroupBox()
        lay = QVBoxLayout(box)
        wdg, lbl, bar = make_pity_widget()
        self.pity["main"] = (lbl, bar)
        lay.addWidget(wdg)
        root.addWidget(box)

    # ---------- НОВОЕ: история выпадений и составы (только персонажные пулы) ----------
    def _make_grid(self) -> FlowLayout:
        return FlowLayout(h_spacing=12, v_spacing=14)    # ИЗМЕНЕНО: адаптивный перенос по ширине окна

    def _build_character_sections(self, root: QVBoxLayout):
        if self.is_arc:
            drop_box = QGroupBox("История выпадения S")
            empty = "Пока не выпала ни одна дуга S ранга."
            groups = ARC_POOL_ROSTERS[self.key]
        else:
            drop_box = QGroupBox("История выпадения S")
            empty = "Пока не выпал ни один персонаж S ранга."
            groups = POOL_ROSTERS[self.key]
        drop_l = QVBoxLayout(drop_box)
        self.hide_std_cb = None
        if self.is_arc:
            self.hide_std_cb = QCheckBox("Скрыть стандартные дуги")
            self.hide_std_cb.setToolTip("Не показывать стандартные S-дуги в истории выпадения")
            try:
                win = self.window()
                self.hide_std_cb.setChecked(
                    win.db.get_setting("arc_hide_standard", "0", scoped=True) == "1")
            except Exception:
                pass
            self.hide_std_cb.toggled.connect(self._on_hide_std_toggled)
            drop_l.addWidget(self.hide_std_cb)
        self.drop_grid = self._make_grid()
        drop_l.addLayout(self.drop_grid)
        self.drop_empty = make_label(empty, "hint")
        drop_l.addWidget(self.drop_empty)
        root.addWidget(drop_box)

        for idx, (title, rarity, roster) in enumerate(groups):
            group = QGroupBox(title)
            grid = self._make_grid()
            QVBoxLayout(group).addLayout(grid)
            root.addWidget(group)
            self.roster_boxes.append((group, grid, title, rarity, roster))

    def _fill_grid(self, grid: FlowLayout, tiles: list):
        clear_grid(grid)
        for tile in tiles:
            grid.addWidget(tile)
        grid.invalidate()
        parent = grid.parentWidget()
        if parent is not None:
            parent.updateGeometry()

    def _load_hide_setting(self):
        if self.is_arc and self.hide_std_cb is not None and not getattr(self, "_hide_loaded", False):
            try:
                v = self.window().db.get_setting("arc_hide_standard", "0", scoped=True) == "1"
                self._hide_loaded = True
                if v != self.hide_std_cb.isChecked():
                    self.hide_std_cb.blockSignals(True)
                    self.hide_std_cb.setChecked(v)
                    self.hide_std_cb.blockSignals(False)
            except Exception:
                pass

    def _update_cards(self):
        s = getattr(self, "_stats", None)
        if not s:
            return
        total_s, avg = s["r5"], fmt_avg(s["pities"])
        if self.is_arc and self.hide_std_cb is not None and self.hide_std_cb.isChecked():
            total_s, avg = arc_event_only_stats(getattr(self, "_history", []))
        for lbl, v in zip(self.cards, (s["total"], total_s, avg)):
            lbl.setText(str(v))

    def _on_hide_std_toggled(self, checked: bool):
        try:
            self.window().db.set_setting("arc_hide_standard", "1" if checked else "0", scoped=True)
        except Exception:
            pass
        self._update_cards()
        self._refresh_drops(getattr(self, "_drops_history", []))

    def _refresh_drops(self, history: list):
        """Выпадения S этого пула в хронологическом порядке; под иконкой — число круток
        (гарант на момент выпадения), окрашенное от зелёного к красному."""
        self._drops_history = history
        drops = [e for e in history
                 if e["banner"] == self.key and e["kind"] == "main" and e["rarity"] == 5]
        if self.is_arc and getattr(self, "hide_std_cb", None) is not None \
                and self.hide_std_cb.isChecked():
            drops = [e for e in drops
                     if arc_kind_by_name(e.get("name"), e.get("arc_kind") or "") == "event"]
        if not DROP_HISTORY_NEWEST_FIRST:
            drops.reverse()  # history идёт «новые сверху» -> старые первыми
        tiles = []
        for e in drops:
            pulls = e["p5"]
            if self.is_arc:
                is_event = arc_kind_by_name(e.get("name"), e.get("arc_kind") or "") == "event"
                # ивентовая дуга: счёт от прошлой ивентовой (стандартная S не сбрасывает);
                # стандартная: от прошлой любой S-дуги
                pulls = e["ce"] if is_event else e["cs"]
                tip = f"{arc_short_name(e['name'])}\nКруток на дугу: {pulls}\n{e['date']}"
                tiles.append(CharTile(e["name"], 5, str(pulls),
                                      pity_color(pulls, PITY_ARC_EVENT if is_event else PITY_ARC_STD),
                                      tip, e["aliases"], label=arc_short_name(e["name"]),
                                      event=is_event))
                continue
            tip = f"{e['name']}\nКруток на персонажа: {pulls}\n{e['date']}"
            tiles.append(CharTile(e["name"], 5, str(pulls), pity_color(pulls), tip, e["aliases"]))
        self.drop_empty.setVisible(not tiles)
        self._fill_grid(self.drop_grid, tiles)

    @staticmethod
    def _roster_tile(name: str, rarity: int, n: int, label=None) -> CharTile:
        """Плитка состава: выпавшие — «×N» цветом ранга, ещё не выпадавшие — приглушены."""
        if n:
            return CharTile(name, rarity, f"×{n}", RARITY_COLORS[rarity],
                            f"{label or name}\nВыпадений: {n}", label=label)
        return CharTile(name, rarity, "—", "#b4b9cc", f"{label or name}\nЕщё не выпадала"
                        if label else f"{name}\nЕщё не выпадал", dim=True, label=label)

    def _refresh_rosters(self, history: list):
        counts = arc_roster_counts(history) if self.is_arc else roster_counts(history, self.key)
        lab = arc_short_name if self.is_arc else (lambda _n: None)
        for group, grid, title, rarity, roster in self.roster_boxes:
            tiles, owned, seen = [], 0, set()
            if self.is_arc and rarity == 5:
                other = [g for g in self.roster_boxes if g[4] is not roster and g[3] == 5]
                known_here = {roster_key(n) for n in roster}
                known_other = {roster_key(n) for g in other for n in g[4]}
            else:
                known_here, known_other = set(), set()
            for name in roster:
                rk = roster_key(name)
                seen.add(rk)
                n = counts.get((rarity, rk), (name, 0))[1]
                owned += bool(n)
                tiles.append(self._roster_tile(name, rarity, n, lab(name)))
            # персонажи из истории, которых нет в составе, не пропадают — идут в конце
            for (r, rk), (name, n) in counts.items():
                if r == rarity and rk not in seen and rk not in known_other:
                    tiles.append(self._roster_tile(name, rarity, n, lab(name)))
            group.setTitle(f"{title} — получено {owned} из {len(roster)}")
            self._fill_grid(grid, tiles)

    # ---------- НОВОЕ: панель баннеров (только ивентовый пул) ----------
    def set_banners(self, info) -> bool:
        """Принимает ответ сервера (имя, сроки, реран) и обновляет панель.
        Возвращает True, если нужен таймер обратного отсчёта."""
        self._banner_info = info
        return self.refresh_banners(reload=True)

    def refresh_banners(self, reload: bool = False) -> bool:
        """Перерисовывает обе половины панели по текущему времени (datetime.now()).
        Возвращает True, пока хотя бы у одного баннера идёт или ожидается отсчёт."""
        if self.key not in BANNER_PANEL_KEYS or self._stats is None:
            return False
        info = self._banner_info
        # ИСПРАВЛЕНО: основной баннер может быть не указан (в JSON только реран) — тогда
        # левая половина «Не определён», а правая всё равно показывает реран
        # «activated» — момент первого появления баннера (нижняя граница учёта круток,
        # если в JSON нет даты старта); без него отметка терялась бы при пересборке записи
        if self.is_arc:
            current = dict(info["arc"]) if info and info.get("arc") else None
            rerun = dict(info["arc_rerun"]) if info and info.get("arc_rerun") else None
        else:
            current = ({"name": info["name"], "start": info.get("start"), "end": info.get("end"),
                        "activated": info.get("activated")}
                       if info and info.get("name") else None)
            rerun = info.get("rerun") if info else None
        self._entries = (current, rerun)
        now, ticking = datetime.now(), False
        for card, entry, is_current in ((self.dash.current, current, True),
                                        (self.dash.rerun, rerun, False)):
            card.setVisible(entry is not None or info is None)
            ticking |= self._fill_card(card, entry, is_current, now, reload)
        return ticking

    def tick_countdowns(self):
        """Тик QTimer: дёшево обновляет только подписи отсчёта обеих половин панели
        (статистика и гарант не пересчитываются)."""
        if self.key not in BANNER_PANEL_KEYS:
            return
        now = datetime.now()
        for card, entry in zip((self.dash.current, self.dash.rerun), self._entries):
            text, tip, kind = banner_countdown(entry, now)
            card.set_period(text, tip, kind)

    def _fill_arc_card(self, card: BannerCard, entry, is_current: bool, now, reload: bool) -> bool:
        s = self._stats
        card.set_banner(entry["name"] if entry else "", reload)
        text, tip, kind = banner_countdown(entry, now)
        card.set_period(text, tip, kind)
        lines = []
        std, ev = s["counter_std"], s["counter_ev"]
        if entry:
            lo, hi = self._banner_window(entry)
            st = arc_period_stats(self._history, lo, hi)
            std, ev = st["std"], st["ev"]
            lines.append(f"Круток за период: {st['pulls']} · S: {st['s']}")
            finish = f"{hi:%d.%m.%Y}" if hi else "…"
            if entry.get("start"):
                lines.append(f"Период: {entry['start']:%d.%m.%Y} — {finish}")
            elif lo:
                lines.append(f"Учёт с {lo:%d.%m.%Y %H:%M} (старт не указан) — {finish}")
            else:
                lines.append(f"Период: … — {finish}")
        elif is_current:
            lines.append(f"Круток в пуле: {s['total']} · S: {s['r5']}")
        else:
            lines.append("Реран дуги пока не объявлен в banners.json")
        card.set_arc_pity(std, ev)
        lines.append(f"До гаранта S дуги: {max(0, PITY_ARC_STD - std)} · "
                     f"ивентовой S дуги: {max(0, PITY_ARC_EVENT - ev)}")
        card.set_stats("\n".join(lines))
        return kind == "live"

    def _fill_card(self, card: BannerCard, entry, is_current: bool, now, reload: bool) -> bool:
        if self.is_arc:
            return self._fill_arc_card(card, entry, is_current, now, reload)
        s = self._stats
        card.set_banner(entry["name"] if entry else "", reload)
        text, tip, kind = banner_countdown(entry, now)
        card.set_period(text, tip, kind)
        lines = []
        # ОБНОВЛЕНО: гарант плитки считается ТОЛЬКО по крауткам внутри окна баннера;
        # без баннера (нет данных JSON) показывается общий счётчик пула
        pity = s["counter"]
        if entry:
            # ИСПРАВЛЕНО: считаем только крутки ВНУТРИ окна баннера [lo; hi]. Раньше при
            # заданной лишь дате окончания в счётчик попадали все старые крутки пула
            # (в том числе добавленные задним числом).
            lo, hi = self._banner_window(entry)
            st = banner_period_stats(self._history, EVENT_BANNER, lo, hi)
            pulls, s_count, pity = st["pulls"], st["s"], st["pity"]
            lines.append(f"Круток за период: {pulls} · S: {s_count}")
            finish = f"{hi:%d.%m.%Y}" if hi else "…"
            if entry.get("start"):
                lines.append(f"Период: {entry['start']:%d.%m.%Y} — {finish}")
            elif lo:
                lines.append(f"Учёт с {lo:%d.%m.%Y %H:%M} (старт не указан) — {finish}")
            else:
                lines.append(f"Период: … — {finish}")
        elif is_current:
            # баннер не определён (нет ответа сервера) — показываем общий итог пула
            lines.append(f"Круток в пуле: {s['total']} · S: {s['r5']}")
        else:
            lines.append("Реран пока не объявлен в banners.json")
        card.set_pity(min(pity, PITY_CHAR_HARD))     # «До гаранта: X/90» — по периоду баннера
        lines.append(f"До жёсткого гаранта осталось: {max(0, PITY_CHAR_HARD - pity)}")
        card.set_stats("\n".join(lines))
        return kind == "live"

    @staticmethod
    def _banner_window(entry):
        """Окно учёта круток баннера -> (start_time, end_time) — см. banner_pull_window."""
        return banner_pull_window(entry)

    def _window_stats(self, start, end):
        """(круток, из них S) ивентового пула СТРОГО внутри окна баннера
        start_time <= дата крутки <= end_time — см. count_banner_period_pulls."""
        return count_banner_period_pulls(self._history, EVENT_BANNER, start, end)

    def update_data(self, s: dict, history: list):
        self._stats, self._history = s, history   # нужны панели баннеров
        self._load_hide_setting()
        self._update_cards()
        for kind, chip in self.chips.items():
            chip.set_count(s["qty"].get(kind, 0))
        if self.rar is not None:   # блока сводки у ивентового пула больше нет
            self.rar.setText(f"B: {s['r3']}   A: {s['r4']}   S: {s['r5']}")
            self.bonus.setText(f"{s['bonus']} из {s['total'] // BONUS_EVERY} положенных "
                               f"(за каждые {BONUS_EVERY} круток)")

        if self.key == STANDARD_BANNER:
            c, (lbl, bar) = s["counter"], self.pity["main"]
            text = f"Текущий: {c}/{PITY_CHAR_HARD}   ·   До жёсткого гаранта: {max(0, PITY_CHAR_HARD - c)}"
            if c + 1 >= PITY_CHAR_SOFT:
                text += "   ·   🔥 Мягкий гарант активен"
            lbl.setText(text)
            set_bar(bar, c, PITY_CHAR_HARD, soft=PITY_CHAR_SOFT - 1, hard=PITY_CHAR_HARD - 1)

        for tag in self.last:      # пусто у ивентового пула (сводка удалена)
            set_last(*self.last[tag], s[tag])
        if self.key in POOL_ROSTERS or self.key in ARC_POOL_ROSTERS:
            self._refresh_drops(history)
            self._refresh_rosters(history)
        if self.key in BANNER_PANEL_KEYS:
            self.refresh_banners(reload=True)  # reload: «Перечитать иконки» подхватывает и арт
