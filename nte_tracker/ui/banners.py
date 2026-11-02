"""Панель баннеров и статистика за период баннера."""

from datetime import datetime

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..catalog import (
    ARC_BANNER, arc_full_name, arc_kind_by_name, arc_short_name, ICON_DIR_NAMES, ICON_EXTS, PITY_ARC_EVENT,
    PITY_ARC_STD, PITY_CHAR_HARD, PITY_CHAR_SOFT,
)
from ..config import (
    BANNER_ART_DIRS, BANNER_CARD_MIN_HEIGHT, BANNER_CARD_RADIUS, BANNER_ENDED_TEXT, BANNER_NO_TIME_TEXT,
    DATE_FMT,
)
from ..icons import _ICON_DPR_OVERRIDE, _name_variants, _PATH_CACHE
from ..ocr.names import NON_PITY_RE
from ..paths import search_roots
from ..workers.banner_feed import format_remaining, parse_banner_datetime
from .staff_widgets import roster_key
from .theme import add_glass_shadow
from .widgets import make_pity_widget, set_bar


# ----------------------------------------------------------------------------
# Раздел «Стафф»: страница одного пула
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# НОВОЕ: панель баннеров («Текущий ивентовый персонаж» и «Реран персонажа»)
# ----------------------------------------------------------------------------
def banner_countdown(entry, now):
    """Отсчёт баннера -> (текст, подсказка, вид), вид: «live» / «ended» / «none».

    Идёт, осталось сутки и больше -> «До конца: 5 дн. 12 ч.»
    Идёт, осталось меньше суток   -> «Осталось: 03 ч. 45 мин.»
    Ещё не начался                -> «Начнётся через …»
    Срок вышел                    -> «Баннер завершён»
    Нет баннера / времени конца   -> «Время не указано» (интернета нет, JSON без даты)"""
    if not entry:
        return BANNER_NO_TIME_TEXT, "", "none"
    start, end = entry.get("start"), entry.get("end")
    if end and now >= end:
        return BANNER_ENDED_TEXT, f"Завершился {end:%d.%m.%Y %H:%M}", "ended"
    if start and now < start:
        return (f"Начнётся через {format_remaining((start - now).total_seconds())}",
                f"Начало: {start:%d.%m.%Y %H:%M}", "live")
    if end:
        left = (end - now).total_seconds()
        prefix = "До конца:" if left >= 86400 else "Осталось:"
        return f"{prefix} {format_remaining(left)}", f"Окончание: {end:%d.%m.%Y %H:%M}", "live"
    return BANNER_NO_TIME_TEXT, "", "none"



def _banner_art_folders() -> list:
    """Папки с артом в порядке приоритета: assets/banners/, затем assets/characters/ (и
    icons/...). Каждая просматривается рядом со скриптом и рядом с базой данных."""
    roots = search_roots()
    return [root / base / sub for sub in BANNER_ART_DIRS
            for root in roots for base in ICON_DIR_NAMES]



def _find_art(variants: list):
    """Первый файл арта, имя которого совпало с одним из вариантов (png/jpg/jpeg/webp).
    Сначала точное имя, затем нестрогое сравнение (регистр, «_» / «-», «ё» = «е»)."""
    wanted = {roster_key(v) for v in variants}
    for folder in _banner_art_folders():
        if not folder.is_dir():
            continue
        for v in variants:
            for ext in ICON_EXTS:
                if (folder / (v + ext)).is_file():
                    return folder / (v + ext)
        try:
            for f in folder.iterdir():
                if f.suffix.lower() in ICON_EXTS and roster_key(f.stem) in wanted:
                    return f
        except OSError:
            pass
    return None



def _search_banner_art(name: str, generic=()):
    """Ищет файл арта: СНАЧАЛА по имени персонажа (Лакримоза.png / Лакримоза.jpg …), и только
    если такого нет — по общим именам generic (для рерана — rerun.png). Так арт конкретного
    персонажа всегда важнее общей заглушки."""
    specific = list(dict.fromkeys(_name_variants(name) + _name_variants(name.replace("ё", "е"))))
    common = list(dict.fromkeys(v for g in generic for v in _name_variants(g)))
    for variants in (specific, common):
        found = _find_art(variants) if variants else None
        if found is not None:
            return found
    return None



def load_banner_art(name: str, generic=()):
    """QPixmap арта баннера или None (нет файла / не открылся) — тогда рисуется стекло."""
    key = ("banner_art", name, tuple(generic))
    if key not in _PATH_CACHE:             # _PATH_CACHE очищается в refresh()
        _PATH_CACHE[key] = _search_banner_art(name, generic)
    path = _PATH_CACHE[key]
    if path is None:
        return None
    pm = QPixmap(str(path))
    return None if pm.isNull() else pm



class BannerCard(QFrame):
    """Плитка баннера: название, отсчёт, «До гаранта: Х/90», статистика.

    Фон рисуется в paintEvent:
      * есть арт (assets/banners/ или assets/characters/) — картинка «cover» по размеру
        плитки, скруглённая, с затемнением снизу для читаемости текста;
      * арта нет или он не загрузился — стеклянная плитка: полупрозрачная светлая
        заливка, блик сверху, скругление BANNER_CARD_RADIUS и тонкая светлая рамка.
    Размытия фона Qt не умеет, поэтому «матовость» имитируется заливкой и бликом."""

    # Стили подписи отсчёта: идёт — золотистый текст; завершён — тихий значок (бейдж) с
    # полупрозрачной заливкой и рамкой; времени нет — приглушённый текст
    PERIOD_STYLES = {
        "live": "color: #ffd740; font-size: 13px; font-weight: bold;",
        "ended": ("color: rgba(255, 255, 255, 200); font-size: 12px; padding: 2px 10px;"
                  "background-color: rgba(255, 255, 255, 30);"
                  "border: 1px solid rgba(255, 255, 255, 70); border-radius: 9px;"),
        "none": "color: rgba(255, 255, 255, 150); font-size: 12px;",
    }

    def __init__(self, caption: str, empty_text: str, art_names=(), arc: bool = False):
        """art_names — общие имена файлов арта на случай, если картинки с именем персонажа
        нет (для рерана — «rerun», для основного баннера — «current», «event»)."""
        super().__init__()
        self.setObjectName("bannerCard")
        self.setMinimumHeight(BANNER_CARD_MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._empty_text, self._art, self._art_name = empty_text, None, None
        self._art_names = tuple(art_names)
        self._scaled, self._scaled_key = None, None   # кэш арта, уже подогнанного под плитку
        add_glass_shadow(self, blur=24, dy=6, alpha=80)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(4)
        self.caption = QLabel(caption)
        self.caption.setStyleSheet(
            "color: rgba(255, 255, 255, 170); font-size: 12px; font-weight: bold;")
        self.title = QLabel(empty_text)
        self.title.setWordWrap(True)
        self.title.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: bold;")
        self.period = QLabel("")
        self.period.setStyleSheet("color: #ffd740; font-size: 13px;")
        self.arc = arc
        self.icon = None
        self.arc_bars = {}
        boxes = []
        if arc:
            self.pity_lbl = self.bar = None
            tips = {"std": "Сбрасывается при выпадении ЛЮБОЙ S дуги (стандартной или ивентовой)",
                    "ev": "Сбрасывается только при выпадении ИВЕНТОВОЙ S дуги"}
            for tag in ("std", "ev"):
                bx, lbl, bar = make_pity_widget()
                lbl.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: bold;")
                lbl.setToolTip(tips[tag])
                self.arc_bars[tag] = (lbl, bar)
                boxes.append(bx)
        else:
            box, self.pity_lbl, self.bar = make_pity_widget()
            self.pity_lbl.setStyleSheet("color: #ffffff; font-size: 15px; font-weight: bold;")
            self.pity_lbl.setToolTip("Гарант ивентового пула в приложении общий для всех "
                                     "ивентовых персонажей")
            boxes.append(box)
        self.stats = QLabel("")
        self.stats.setWordWrap(True)
        self.stats.setStyleSheet("color: rgba(255, 255, 255, 190); font-size: 12px;")
        period_row = QHBoxLayout()         # подпись не растягивается на всю ширину: бейдж компактный
        period_row.addWidget(self.period)
        period_row.addStretch(1)
        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(self.caption)
        left.addWidget(self.title)
        left.addLayout(period_row)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addLayout(left, 1)
        lay.addLayout(head)
        lay.addStretch(1)
        for box in boxes:
            lay.addWidget(box)
        lay.addWidget(self.stats)

    def set_banner(self, name: str, reload: bool = False):
        """Название и арт. Арт перечитывается с диска только при смене имени или reload."""
        if reload or name != self._art_name:
            self._art_name = name
            if self.arc:
                art = None
                if name:
                    art = (load_banner_art(arc_short_name(name))
                           or load_banner_art(arc_full_name(name), self._art_names))
                self._art = art
            else:
                self._art = load_banner_art(name, self._art_names) if name else None
            self._scaled = self._scaled_key = None   # арт сменился — подгонку делаем заново
            self.update()
        if self.arc:
            self.title.setText(arc_short_name(name) or self._empty_text)
            return
        self.title.setText(name or self._empty_text)

    def set_period(self, text: str, tip: str = "", kind: str = "none"):
        """Подпись отсчёта (видна всегда: либо время, либо «Время не указано»)."""
        self.period.setText(text)
        self.period.setToolTip(tip)
        style = self.PERIOD_STYLES.get(kind, self.PERIOD_STYLES["none"])
        if self.period.styleSheet() != style:   # стиль меняем только при смене вида
            self.period.setStyleSheet(style)

    def set_pity(self, cur: int):
        text = f"До гаранта: {cur}/{PITY_CHAR_HARD}"
        if cur + 1 >= PITY_CHAR_SOFT:
            text += "  ·  🔥 мягкий гарант"
        self.pity_lbl.setText(text)
        set_bar(self.bar, cur, PITY_CHAR_HARD, soft=PITY_CHAR_SOFT - 1, hard=PITY_CHAR_HARD - 1)

    def set_arc_pity(self, std: int, ev: int):
        for tag, cur, target, title in (("std", std, PITY_ARC_STD, "Стандартная S дуга"),
                                        ("ev", ev, PITY_ARC_EVENT, "Ивентовая S дуга")):
            lbl, bar = self.arc_bars[tag]
            lbl.setText(f"{title} (каждые {target}): {cur}/{target}  ·  "
                        f"До гаранта: {max(0, target - cur)}")
            set_bar(bar, cur, target, hard=target - 1)

    def set_stats(self, text: str):
        self.stats.setText(text)

    def _cover_art(self):
        """Арт, подогнанный под плитку по принципу «cover»: пропорции СОХРАНЯЮТСЯ, картинка
        увеличивается/уменьшается так, чтобы закрыть всю плитку, лишнее обрезается по центру.
        Масштабирование — Qt.TransformationMode.SmoothTransformation (сглаживание), с учётом
        плотности пикселей экрана (HiDPI). Результат кэшируется и пересчитывается только при
        смене картинки или размера плитки, поэтому тик таймера и перерисовка остаются лёгкими."""
        src = self._art
        if src is None or src.isNull():
            return None
        dpr = _ICON_DPR_OVERRIDE or self.devicePixelRatioF()   # при экспорте — сверх-разрешение
        w, h = round(self.width() * dpr), round(self.height() * dpr)
        if w < 1 or h < 1:
            return None
        if self._scaled is None or self._scaled_key != (w, h):
            scaled = src.scaled(QSize(w, h), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation)
            scaled = scaled.copy((scaled.width() - w) // 2, (scaled.height() - h) // 2, w, h)
            scaled.setDevicePixelRatio(dpr)
            self._scaled, self._scaled_key = scaled, (w, h)
        return self._scaled

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing
                         | QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, BANNER_CARD_RADIUS, BANNER_CARD_RADIUS)
        p.setClipPath(path)                # всё рисуем внутри скруглённого контура
        art = self._cover_art()
        if art is not None:
            # арт уже подогнан под плитку (_cover_art), клип по скруглённому контуру выше
            p.drawPixmap(QPointF(0, 0), art)
            shade = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
            shade.setColorAt(0.0, QColor(8, 10, 24, 60))    # сверху почти прозрачно
            shade.setColorAt(1.0, QColor(8, 10, 24, 215))   # снизу темно — под текстом
            p.fillRect(rect, QBrush(shade))
            border = QColor(255, 255, 255, 75)
        else:
            # СТЕКЛЯННЫЙ запасной вариант: полупрозрачная заливка + блик в верхней половине
            glass = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
            glass.setColorAt(0.0, QColor(255, 255, 255, 48))
            glass.setColorAt(1.0, QColor(255, 255, 255, 12))
            p.fillPath(path, QBrush(glass))
            gloss = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.center().y())
            gloss.setColorAt(0.0, QColor(255, 255, 255, 38))
            gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillRect(QRectF(rect.left(), rect.top(), rect.width(), rect.height() / 2),
                       QBrush(gloss))
            border = QColor(255, 255, 255, 60)
        p.setClipping(False)
        p.setPen(QPen(border, 1))          # тонкая полупрозрачная рамка
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()



class BannerDashboard(QWidget):
    """Две симметричные половины: слева «Текущий ивентовый персонаж», справа «Реран персонажа»."""

    def __init__(self, arc: bool = False):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        # Обе половины построены одинаково; различаются только запасные имена арта:
        # current.* / event.* для основного баннера и rerun.* для рерана
        if arc:
            self.current = BannerCard("Дуга текущего персонажа", "Не определена",
                                      art_names=("arc_current", "arc", "current_arc"), arc=True)
            self.rerun = BannerCard("Дуга реран персонажа", "Не объявлена",
                                    art_names=("arc_rerun", "rerun_arc"), arc=True)
        else:
            self.current = BannerCard("Текущий ивентовый персонаж", "Не определён",
                                      art_names=("current", "event"))
            self.rerun = BannerCard("Реран персонажа", "Не объявлен", art_names=("rerun",))
        lay.addWidget(self.current, 1)     # одинаковая растяжка -> половины равны
        lay.addWidget(self.rerun, 1)



def banner_pull_window(entry):
    """ОБНОВЛЕНО: окно учёта круток баннера -> (start_time, end_time) из banners.json.
    Это поля «start» / «end» записи баннера (event_start_time / event_end_time,
    rerun_start_time / rerun_end_time, start_time / end_time и т. д. — см. parse_banner_payload).
    Если в JSON нет даты старта, нижней границей служит момент, когда приложение впервые
    увидело баннер (entry["activated"]), — иначе в счётчик попали бы ВСЕ старые крутки пула.
    Отсутствие даты окончания означает «без верхней границы»."""
    if not entry:
        return None, None
    return entry.get("start") or entry.get("activated"), entry.get("end")



def _history_datetime(value):
    """Дата записи истории (pulled_at) -> naive datetime или None, если не распознана."""
    dt = parse_banner_datetime(value)
    if dt is None:
        try:
            dt = datetime.strptime(str(value), DATE_FMT)
        except (TypeError, ValueError):
            return None
    return dt



def banner_period_stats(history: list, banner_key: str, start, end) -> dict:
    """ОБНОВЛЕНО: статистика баннера СТРОГО за его период -> {"pulls", "s", "pity"}.

    Считаются только обычные крутки (kind == "main": без бонусов, кешбэка и предметов) пула
    banner_key, у которых ДАТА ЗАПИСИ (pulled_at) лежит в окне  start <= дата <= end  (обе
    границы включительно; None — граница не задана). Крутки до start (в том числе добавленные
    «задним числом»), после end и с нераспознанной датой НЕ входят ни в одно значение:
      pulls — «Круток за период»;
      s     — сколько из них S (ранг 5);
      pity  — «До гаранта: X/90»: число круток пула после последней S (хронологически, до
              конца окна); гарант переносится между баннерами и сбрасывается только выпавшей S.
    Функция универсальна: окно целиком берётся из start / end записи banners.json, поэтому
    при смене персонажей и дат в JSON никакой код менять не нужно."""
    rows, all_rows = [], []
    for e in reversed(history):               # history — «новые сверху»; идём от старых к новым
        # OCR-ФИКС 7: считаются обычные крутки и предметы, занявшие крутку (n — число);
        # «Страна сна» / «Подарок за очки» (kind bonus, n = «•») не входят никуда
        counted_item = e["kind"] == "item" and str(e.get("n", "•")).isdigit()
        if e["banner"] != banner_key or (e["kind"] != "main" and not counted_item):
            continue
        if NON_PITY_RE.search(e.get("name") or ""):
            continue
        dt = _history_datetime(e["date"])
        if dt is None or (end and dt > end):
            continue                          # после окончания баннера (или дата не распознана)
        rarity = e["rarity"] if e["kind"] == "main" else 0
        all_rows.append((dt, rarity))         # для гаранта: все крутки пула до конца окна
        if start and dt < start:
            continue                          # до старта — в «круток за период» не входит
        rows.append((dt, rarity))
    rows.sort(key=lambda r: r[0])             # сортировка устойчивая: равное время — по порядку записи
    all_rows.sort(key=lambda r: r[0])
    pulls, s_count, pity = 0, 0, 0
    for _dt, rarity in rows:
        pulls += 1
        if rarity == 5:
            s_count += 1
    # ИСПРАВЛЕНО: гарант ПЕРЕНОСИТСЯ между баннерами пула — число круток после последней S
    # (за всё время, а не только в окне); сбрасывается только выпадением S
    for _dt, rarity in all_rows:
        pity += 1
        if rarity == 5:                       # предметы (rarity 0) гарант не сбрасывают
            pity = 0                          # S сбрасывает гарант
    if banner_key != ARC_BANNER:
        pity = min(pity, PITY_CHAR_HARD)      # гарант персонажей — не больше 90
    return {"pulls": pulls, "s": s_count, "pity": pity}



def arc_period_stats(history: list, start, end) -> dict:
    """Статистика баннера дуг: «круток за период» и S — только в окне [start; end];
    счётчики гарантов (std — стандартная S дуга, ev — ивентовая S дуга) ПЕРЕНОСЯТСЯ между
    баннерами: считаются по всем круткам пула до конца окна и сбрасываются только выпавшей S."""
    rows, all_rows = [], []
    for e in reversed(history):
        counted_item = e["kind"] == "item" and str(e.get("n", "•")).isdigit()
        if e["banner"] != ARC_BANNER or (e["kind"] != "main" and not counted_item):
            continue
        if NON_PITY_RE.search(e.get("name") or ""):
            continue
        dt = _history_datetime(e["date"])
        if dt is None or (end and dt > end):
            continue
        is_main = e["kind"] == "main"
        kind = arc_kind_by_name(e.get("name"), e.get("arc_kind") or "") if is_main else ""
        row = (dt, e["rarity"] if is_main else 0, kind)
        all_rows.append(row)
        if start and dt < start:
            continue
        rows.append(row)
    rows.sort(key=lambda r: r[0])
    all_rows.sort(key=lambda r: r[0])
    pulls, s_count, std, ev = 0, 0, 0, 0
    for _dt, rarity, _kind in rows:
        pulls += 1
        if rarity == 5:
            s_count += 1
    for _dt, rarity, kind in all_rows:
        std += 1
        ev += 1
        if rarity == 5:
            std = 0
            if kind == "event":
                ev = 0
    return {"pulls": pulls, "s": s_count, "std": std, "ev": ev}



def count_banner_period_pulls(history: list, banner_key: str, start, end):
    """Совместимая обёртка: («Круток за период», из них S) — см. banner_period_stats."""
    st = banner_period_stats(history, banner_key, start, end)
    return st["pulls"], st["s"]
