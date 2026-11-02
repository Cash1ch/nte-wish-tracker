"""Окно Колеса Фортуны."""

import traceback

from PyQt6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QSize, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFrame, QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from .sounds import FortuneSounds
from .themes import FORTUNE_DEFAULT_OPTIONS, FORTUNE_MAX_OPTIONS, FORTUNE_MIN_OPTIONS, FORTUNE_THEMES
from .wheel import _fortune_draw_paw, FORTUNE_PAW_SPOTS, FortuneWheel


# ---------- окно ----------
# ---------- адаптивное оформление окна колеса ----------
def _fortune_px(value: float, k: float) -> int:
    return max(1, int(round(value * k)))



def _fortune_stylesheet(k: float, theme: str = "classic") -> str:
    """Таблица стилей окна колеса для выбранной темы. Все размеры шрифтов, отступов и скруглений
    умножаются на коэффициент масштаба k (зависит от размера окна), поэтому текст и кнопки одинаково
    хорошо смотрятся и на маленьком окне, и на развёрнутом, и на 4K-мониторе."""
    f = lambda v: _fortune_px(v, k)
    T = FORTUNE_THEMES.get(theme, FORTUNE_THEMES["classic"])
    spin, spin_fg, spin_border, spin_hover = T["spin"]
    dis_fg, dis_bg, dis_border = T["btn_dis"]
    sd_bg, sd_fg, sd_border = T["spin_dis"]
    return f"""
        QDialog {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {T['bg'][0]}, stop:1 {T['bg'][1]}); }}
        QScrollArea {{ background: transparent; border: none; }}
        QScrollArea > QWidget > QWidget {{ background: transparent; }}
        QFrame#fortuneCard {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {T['card'][0]}, stop:1 {T['card'][1]});
            border: 1px solid {T['card_border']}; border-radius: {f(16)}px; }}
        QLabel#fortuneTitle {{ color: {T['title']}; font-family: Georgia, 'Palatino Linotype', serif;
            font-size: {f(22)}px; font-weight: bold; letter-spacing: {f(3)}px; background: transparent; }}
        QLabel#fortuneIntro {{ color: {T['intro']}; font-family: Georgia, 'Palatino Linotype', serif;
            font-size: {f(15)}px; font-style: italic; background: transparent; }}
        QFrame#fortunePanel {{ background: {T['panel_bg']}; border: 1px solid {T['panel_border']};
            border-radius: {f(12)}px; }}
        QLabel#fortuneHead {{ color: {T['head']}; font-size: {f(15)}px; font-weight: bold; background: transparent; }}
        QLabel#fortuneHint {{ color: {T['hint']}; font-size: {f(12)}px; background: transparent; }}
        QListWidget {{ background: {T['list_bg']}; color: {T['list_fg']}; border: 1px solid {T['field_border']};
            border-radius: {f(8)}px; font-size: {f(14)}px; }}
        QListWidget::item {{ padding: {f(5)}px {f(6)}px; }}
        QListWidget::item:selected {{ background: {T['select']}; color: {T['select_fg']}; }}
        QLineEdit {{ background: {T['list_bg']}; color: {T['edit_fg']}; border: 1px solid {T['field_border']};
            border-radius: {f(8)}px; padding: {f(6)}px; font-size: {f(14)}px; }}
        QPushButton {{ background: {T['btn_bg']}; color: {T['btn_fg']}; border: 1px solid {T['btn_border']};
            border-radius: {f(8)}px; padding: {f(6)}px {f(10)}px; font-size: {f(12)}px; text-align: center; }}
        QPushButton:hover {{ background: {T['btn_hover']}; }}
        QPushButton:disabled {{ color: {dis_fg}; background: {dis_bg}; border-color: {dis_border}; }}
        QPushButton#fortuneSpin {{ background: {spin}; color: {spin_fg}; border: {max(2, f(2))}px solid {spin_border};
            border-radius: {f(14)}px; font-family: Georgia, serif; font-size: {f(22)}px; font-weight: bold;
            padding: {f(10)}px {f(40)}px; }}
        QPushButton#fortuneSpin:hover {{ background: {spin_hover}; }}
        QPushButton#fortuneSpin:disabled {{ background: {sd_bg}; color: {sd_fg}; border-color: {sd_border}; }}
        QCheckBox {{ color: {T['check']}; font-size: {f(13)}px; spacing: {f(6)}px; }}
        QLabel#fortuneStyleLabel {{ color: {T['check']}; font-size: {f(13)}px; background: transparent; }}
        QComboBox {{ background: {T['btn_bg']}; color: {T['btn_fg']}; border: 1px solid {T['btn_border']};
            border-radius: {f(8)}px; padding: {f(4)}px {f(10)}px; font-size: {f(13)}px; min-width: {f(130)}px; }}
        QComboBox:hover {{ background: {T['btn_hover']}; }}
        QComboBox:disabled {{ color: {dis_fg}; background: {dis_bg}; border-color: {dis_border}; }}
        QComboBox::drop-down {{ border: none; width: {f(22)}px; }}
        QComboBox QAbstractItemView {{ background: {T['list_bg']}; color: {T['list_fg']};
            border: 1px solid {T['field_border']}; selection-background-color: {T['select']};
            selection-color: {T['select_fg']}; outline: none; font-size: {f(13)}px; }}
        QSplitter::handle {{ background: transparent; }}
    """



def _fortune_card_stylesheet(k: float, theme: str = "classic") -> str:
    f = lambda v: _fortune_px(v, k)
    W = FORTUNE_THEMES.get(theme, FORTUNE_THEMES["classic"])["win"]
    return f"""
        QFrame#winCard {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {W['bg'][0]}, stop:1 {W['bg'][1]});
            border: {max(2, f(2))}px solid {W['border']}; border-radius: {f(18)}px; }}
        QLabel#winTop {{ color: {W['top']}; font-family: Georgia, serif; font-size: {f(13)}px; letter-spacing: {f(3)}px;
            background: transparent; }}
        QLabel#winText {{ color: {W['text']}; font-family: Georgia, serif; font-size: {f(26)}px; font-weight: bold;
            background: transparent; }}
        QLabel#winSub {{ color: {W['sub']}; font-family: Georgia, serif; font-size: {f(16)}px; font-style: italic;
            background: transparent; }}
        QPushButton {{ background: {W['btn_bg']}; color: {W['btn_fg']}; border: 1px solid {W['btn_border']};
            border-radius: {f(10)}px; padding: {f(6)}px {f(22)}px; font-size: {f(14)}px; font-weight: bold; }}
        QPushButton:hover {{ background: {W['btn_hover']}; }}
    """



class _FitScroll(QScrollArea):
    """Прокручиваемая область, которая по высоте подгоняется под содержимое (перенос строк учитывается),
    но не выше заданного максимума: если места не хватает, текст плавно прокручивается."""

    def sizeHint(self):
        inner = self.widget()
        if inner is None or inner.layout() is None:
            return super().sizeHint()
        width = max(120, self.viewport().width() or self.width())
        height = inner.layout().totalHeightForWidth(width)
        return QSize(inner.sizeHint().width(), max(40, height) + 2 * self.frameWidth())

    def minimumSizeHint(self):
        return QSize(120, 60)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.updateGeometry()                                  # от ширины зависит число строк текста, а значит и высота



class FortuneDialog(QDialog):
    """Колесо Фортуны: вступительный текст, редактируемый список вариантов, колесо и «Удачи!».
    Не блокирует главное окно. При закрытии таймеры и звуки останавливаются."""

    def __init__(self, get_master, duck_music, get_style=None, set_style=None, parent=None, on_spin=None):
        super().__init__(parent)
        self._spin_done_cb = on_spin                          # колбэк: колесо прокручено (для достижений)
        self.setWindowTitle("Колесо Фортуны")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setModal(False)
        # Окно свободно изменяется: есть кнопки «развернуть» / «свернуть» и «уголок» для растягивания,
        # фиксированных размеров нет (задан только небольшой минимум).
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint
                            | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowCloseButtonHint)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(750, 500)                         # меньше окно не сжимается: элементы не наезжают друг на друга
        self.resize(1040, 760)
        self._duck = duck_music
        self._opts = []                                       # при каждом открытии окна «Варианты судьбы» пусты
        self._busy = False
        self._k = 1.0                                         # коэффициент масштаба шрифтов и отступов
        self._vertical = False                                # узкое окно: панель и колесо друг под другом
        self._fitting = False                                 # защита от повторного входа при подборе подписей кнопок
        self._save_style = set_style
        self._elim_on = False                                    # режим «На выбывание»
        self._pool = []                                          # индексы вариантов, которые ещё на колесе
        self._eliminated = set()                                 # индексы выбывших вариантов
        self._run_done = False                                   # круг «На выбывание» завершён (остался один вариант)
        self._elim_pending = -1                                  # индекс (на колесе) варианта, который сейчас выбывает
        self._elim_timer = QTimer(self)
        self._elim_timer.setSingleShot(True)
        self._elim_timer.timeout.connect(self._apply_elimination)
        try:
            saved = get_style() if get_style else "classic"      # сохранённый выбор стиля
        except Exception:  # noqa: BLE001
            saved = "classic"
        if saved is True:                                        # совместимость со старой настройкой «Стиль NTE»
            saved = "nte"
        self._theme = saved if saved in FORTUNE_THEMES else "classic"
        self.sounds = FortuneSounds(get_master, self, self._theme)
        expand = QSizePolicy.Policy.Expanding
        pref = QSizePolicy.Policy.Preferred

        root = QVBoxLayout(self)
        self._root = root
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        # --- вступительная карточка: переносит строки и прокручивается, если не хватает высоты ---
        card = QFrame()
        card.setObjectName("fortuneCard")
        clay = QVBoxLayout(card)
        self._card_layout = clay
        clay.setContentsMargins(22, 14, 22, 16)
        clay.setSpacing(6)
        self.title_label = QLabel(FORTUNE_THEMES[self._theme]["title_text"])
        self.title_label.setObjectName("fortuneTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        clay.addWidget(self.title_label)
        intro = self.intro_label = QLabel(FORTUNE_THEMES[self._theme]["intro_text"])   # текст зависит от «Стиль NTE»
        intro.setObjectName("fortuneIntro")
        intro.setWordWrap(True)                               # автоперенос строк
        intro.setAlignment(Qt.AlignmentFlag.AlignCenter)
        intro.setSizePolicy(expand, pref)
        clay.addWidget(intro)
        self.intro_scroll = _FitScroll()
        self.intro_scroll.setWidgetResizable(True)
        self.intro_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.intro_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.intro_scroll.setSizePolicy(expand, QSizePolicy.Policy.Maximum)
        self.intro_scroll.setWidget(card)
        root.addWidget(self.intro_scroll, 0)

        # --- основная часть: разделитель (сплиттер) «варианты | колесо» ---
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(10)
        root.addWidget(self.splitter, 1)

        self.panel = QFrame()
        self.panel.setObjectName("fortunePanel")
        self.panel.setMinimumWidth(260)                       # левая панель не уже 260 px, колесо занимает остальное место
        self.panel.setSizePolicy(expand, expand)
        self.panel.installEventFilter(self)                   # при смене ширины панели подбираем подписи кнопок
        play = QVBoxLayout(self.panel)
        self._panel_layout = play
        play.setContentsMargins(12, 12, 12, 12)
        play.setSpacing(8)
        head = QLabel("Варианты судьбы")
        head.setObjectName("fortuneHead")
        play.addWidget(head)
        hint = QLabel("Впишите свои варианты, и Госпожа Удача решит всё за вас.")
        hint.setObjectName("fortuneHint")
        hint.setWordWrap(True)
        play.addWidget(hint)
        self.list = QListWidget()
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.list.setSizePolicy(expand, expand)
        play.addWidget(self.list, 1)
        # поле ввода и кнопки: 1-я строка — поле + «Добавить», дальше — по кнопке на всю ширину панели
        grid = QGridLayout()
        self._panel_grid = grid
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.new_edit = QLineEdit()
        self.new_edit.setPlaceholderText("Новый вариант…")
        self.new_edit.setMaxLength(60)
        self.new_edit.setMinimumWidth(90)
        self.add_btn = QPushButton("Добавить")
        self.del_btn = QPushButton("Удалить выбранное")
        self.reset_btn = QPushButton("Примерные варианты")
        self.clear_btn = QPushButton("Очистить всё")
        self.new_edit.setSizePolicy(expand, pref)
        self.add_btn.setSizePolicy(QSizePolicy.Policy.Minimum, pref)    # ширина «Добавить» считается по тексту
        for wdg in (self.del_btn, self.reset_btn, self.clear_btn):
            wdg.setSizePolicy(expand, pref)
        grid.addWidget(self.new_edit, 0, 0)
        grid.addWidget(self.add_btn, 0, 1)
        grid.addWidget(self.del_btn, 1, 0, 1, 2)
        grid.addWidget(self.reset_btn, 2, 0, 1, 2)
        grid.addWidget(self.clear_btn, 3, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)
        play.addLayout(grid)
        self.status = QLabel("")
        self.status.setObjectName("fortuneHint")
        self.status.setWordWrap(True)
        play.addWidget(self.status)
        self.splitter.addWidget(self.panel)

        self.right_box = QWidget()
        self.right_box.setMinimumWidth(300)
        right = QVBoxLayout(self.right_box)
        self._right_layout = right
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        self.wheel = FortuneWheel()
        right.addWidget(self.wheel, 1)
        self.spin_btn = QPushButton("Удачи!")
        self.spin_btn.setObjectName("fortuneSpin")
        self.spin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.spin_btn.setSizePolicy(expand, pref)
        spin_row = QHBoxLayout()                              # кнопка занимает ~60% ширины и растёт вместе с окном
        spin_row.addStretch(1)
        spin_row.addWidget(self.spin_btn, 3)
        spin_row.addStretch(1)
        right.addLayout(spin_row)
        self.splitter.addWidget(self.right_box)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 5)
        self.splitter.setSizes([320, 720])

        # --- нижняя строка: «Звук» и «Стиль NTE» ---
        self.sound_check = QCheckBox("Звук")
        self.sound_check.setChecked(True)
        self.style_label = QLabel("Стиль:")
        self.style_label.setObjectName("fortuneStyleLabel")
        self.style_combo = QComboBox()                        # выбор стиля: оформление и звуки меняются сразу
        for title, key in (("Классический", "classic"), ("Стиль NTE", "nte"), ("Сакура", "sakura"), ("Белые лапки", "paws")):
            self.style_combo.addItem(title, key)
        self.style_combo.setCurrentIndex(max(0, self.style_combo.findData(self._theme)))
        self.style_combo.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.style_combo.setToolTip("Классический · Стиль NTE (киберпанк) · Сакура (японский стиль) · Белые лапки (уютный котёнок)")
        self.elim_check = QCheckBox("На выбывание")
        self.elim_check.setToolTip("После каждой крутки один вариант выбывает — пока не останется только один")
        self._bottom = QHBoxLayout()
        self._bottom.addWidget(self.sound_check)
        self._bottom.addWidget(self.elim_check)
        self._bottom.addWidget(self.style_label)
        self._bottom.addWidget(self.style_combo)
        self._bottom.addStretch(1)
        root.addLayout(self._bottom, 0)

        self._build_win_card()
        self._fill_list()
        self.wheel.set_options(self._opts)
        self.add_btn.clicked.connect(self._add_option)
        self.new_edit.returnPressed.connect(self._add_option)
        self.del_btn.clicked.connect(self._delete_option)
        self.reset_btn.clicked.connect(self._reset_options)
        self.clear_btn.clicked.connect(self._clear_options)
        self.list.itemChanged.connect(self._on_item_changed)
        self.spin_btn.clicked.connect(self._spin)
        self.sound_check.toggled.connect(self._on_sound_toggled)
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        self.elim_check.toggled.connect(self._on_elim_toggled)
        self.wheel.spinFinished.connect(self._on_finished)
        self.wheel.resized.connect(self._on_wheel_resized)
        self.wheel.pegCrossed.connect(self.sounds.tick)
        self.wheel.speedChanged.connect(lambda v: self.sounds.set_spin(v, self.wheel.spinning))
        self.wheel.set_theme(self._theme)
        self._apply_theme()
        self._update_controls()

    def paintEvent(self, event):
        """«Белые лапки»: едва заметные отпечатки лапок на фоне окна (поверх градиента, под виджетами)."""
        super().paintEvent(event)
        if self._theme != "paws":
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        side = float(min(w, h))
        col = QColor(217, 195, 169, 70)
        for fx, fy, fs, fa in FORTUNE_PAW_SPOTS:
            _fortune_draw_paw(p, fx * w, fy * h, fs * side * 1.3, col, fa)
        p.end()

    # ---------- тема оформления ----------
    def _apply_theme(self):
        """Применяет выбранную тему: стили окна, палитру колеса, тексты заголовка и карточки победы,
        неоновое свечение кнопки «Удачи!»."""
        th = FORTUNE_THEMES[self._theme]
        self.wheel.set_theme(self._theme)
        self.title_label.setText(th["title_text"])
        self.intro_label.setText(th["intro_text"])             # вступительная цитата меняется вместе со стилем
        self.win_top.setText(th["win_top"])
        self.win_sub.setText(th["win_sub"])
        if th["spin_glow"]:
            effect = QGraphicsDropShadowEffect(self.spin_btn)
            effect.setOffset(0, 0)
            effect.setBlurRadius(32)
            color = QColor(th["spin_glow"])
            color.setAlpha(190)
            effect.setColor(color)
            self.spin_btn.setGraphicsEffect(effect)
        else:
            self.spin_btn.setGraphicsEffect(None)
        self._apply_scale(force=True)

    def _on_style_changed(self, _index: int = 0):
        """Выбор стиля («Классический» / «Стиль NTE» / «Сакура» / «Белые лапки»): мгновенно меняет оформление, вступительный
        текст и набор звуков; выбор сохраняется в настройках."""
        key = self.style_combo.currentData()
        self._theme = key if key in FORTUNE_THEMES else "classic"
        if self._save_style:
            try:
                self._save_style(self._theme)
            except Exception:  # noqa: BLE001 — сохранение не должно ронять окно
                pass
        self._apply_theme()
        self.sounds.set_theme(self._theme)
        self.update()

    # ---------- адаптивность ----------
    def _apply_scale(self, force: bool = False):
        """Пересчитывает масштаб шрифтов / отступов по размеру окна и подгоняет высоту вступительной карточки."""
        k = min(self.width() / 1040.0, self.height() / 760.0)
        k = max(0.7, min(2.4, round(k / 0.05) * 0.05))        # шаг 5%: стили не пересобираются на каждый пиксель
        if force or abs(k - self._k) > 1e-6:
            self._k = k
            f = lambda v: _fortune_px(v, k)
            self.setStyleSheet(_fortune_stylesheet(k, self._theme))
            self.win_card.setStyleSheet(_fortune_card_stylesheet(k, self._theme))
            self._bottom.setSpacing(f(18))
            self._root.setContentsMargins(f(16), f(14), f(16), f(14))
            self._root.setSpacing(f(12))
            self._card_layout.setContentsMargins(f(22), f(14), f(22), f(16))
            self._card_layout.setSpacing(f(6))
            self._panel_layout.setContentsMargins(f(12), f(12), f(12), f(12))
            self._panel_layout.setSpacing(f(8))
            self._panel_grid.setHorizontalSpacing(f(8))
            self._panel_grid.setVerticalSpacing(f(8))
            self._right_layout.setSpacing(f(10))
            self.spin_btn.setMinimumHeight(f(54))
            for wdg in (self.new_edit, self.add_btn, self.del_btn, self.reset_btn, self.clear_btn):
                wdg.setMinimumHeight(f(34))
        # вступительная карточка: не выше ~30% окна, дальше — прокрутка
        self.intro_scroll.setMaximumHeight(max(90, int(self.height() * 0.30)))
        self.intro_scroll.updateGeometry()
        self._fit_button_texts()

    # подписи кнопок: от полной к короткой; если и короткая не помещается — шрифт уменьшается (не меньше 9 px)
    _BUTTON_TEXTS = (("add_btn", ("Добавить",)),
                     ("del_btn", ("Удалить выбранное", "Удалить")),
                     ("reset_btn", ("Примерные варианты", "Шаблоны")),
                     ("clear_btn", ("Очистить всё", "Очистить все")))

    def eventFilter(self, obj, event):
        if obj is self.panel and event.type() == QEvent.Type.Resize and not self._fitting:
            QTimer.singleShot(0, self._fit_button_texts)
        return super().eventFilter(obj, event)

    def _fit_button_texts(self):
        """Подбирает подпись и размер шрифта кнопок управления вариантами так, чтобы текст никогда не
        обрезался: сначала полная подпись, затем короткая («Удалить», «Шаблоны»), затем меньший шрифт.
        Ширина кнопки «Добавить» считается по её тексту (минимальная ширина задаётся динамически)."""
        if self._fitting:
            return
        self._fitting = True
        try:
            k = self._k
            f = lambda v: _fortune_px(v, k)
            margins = self._panel_layout.contentsMargins()
            panel_w = max(120, self.panel.width() - margins.left() - margins.right())
            pad = 2 * f(10) + 6                                # внутренние отступы кнопки + рамка
            base_px = f(12)
            for attr, texts in self._BUTTON_TEXTS:
                btn = getattr(self, attr)
                avail = (panel_w if attr != "add_btn" else 10 ** 6) - pad
                chosen, size = texts[-1], 9
                found = False
                for px in range(base_px, 8, -1):
                    font = QFont(btn.font())
                    font.setPixelSize(px)
                    metrics = QFontMetricsF(font)
                    for text in texts:
                        if metrics.horizontalAdvance(text) <= avail:
                            chosen, size, found = text, px, True
                            break
                    if found:
                        break
                if btn.text() != chosen:
                    btn.setText(chosen)
                btn.setToolTip(texts[0] if chosen != texts[0] else "")
                style = f"font-size: {size}px;"
                if btn.styleSheet() != style:
                    btn.setStyleSheet(style)
                if attr == "add_btn":                          # «Добавить»: минимальная ширина по тексту
                    font = QFont(btn.font())
                    font.setPixelSize(size)
                    btn.setMinimumWidth(int(QFontMetricsF(font).horizontalAdvance(chosen)) + pad + f(6))
        finally:
            self._fitting = False

    def _set_vertical(self, vertical: bool):
        """Узкое окно: колесо сверху, панель вариантов под ним; широкое — панель слева, колесо справа."""
        if vertical == self._vertical:
            return
        self._vertical = vertical
        self.splitter.setOrientation(Qt.Orientation.Vertical if vertical else Qt.Orientation.Horizontal)
        self.splitter.insertWidget(0, self.right_box if vertical else self.panel)
        self.splitter.setStretchFactor(0, 5 if vertical else 2)
        self.splitter.setStretchFactor(1, 2 if vertical else 5)
        if vertical:
            total = max(200, self.splitter.height())
            self.splitter.setSizes([int(total * 0.62), int(total * 0.38)])
        else:
            total = max(400, self.splitter.width())
            self.splitter.setSizes([int(total * 0.30), int(total * 0.70)])

    # ---------- карточка победы ----------
    def _build_win_card(self):
        self.win_card = QFrame(self.wheel)
        self.win_card.setObjectName("winCard")
        lay = QVBoxLayout(self.win_card)
        lay.setContentsMargins(26, 18, 26, 18)
        lay.setSpacing(8)
        top = self.win_top = QLabel(FORTUNE_THEMES[self._theme]["win_top"])
        top.setObjectName("winTop")
        top.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.win_text = QLabel("")
        self.win_text.setObjectName("winText")
        self.win_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.win_text.setWordWrap(True)
        sub = self.win_sub = QLabel(FORTUNE_THEMES[self._theme]["win_sub"])
        sub.setObjectName("winSub")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        ok = QPushButton("Принять судьбу")
        ok.clicked.connect(self._hide_win_card)
        for wdg in (top, self.win_text, sub):
            lay.addWidget(wdg)
        lay.addWidget(ok, 0, Qt.AlignmentFlag.AlignHCenter)
        self._win_opacity = QGraphicsOpacityEffect(self.win_card)
        self.win_card.setGraphicsEffect(self._win_opacity)
        self._win_anim = QPropertyAnimation(self._win_opacity, b"opacity", self)
        self._win_anim.setDuration(700)
        self._win_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.win_card.hide()

    def _place_win_card(self):
        """Карточка победы по центру колеса; ширина — доля колеса (не больше 520·k), поэтому
        она не вылезает за колесо ни в маленьком, ни в большом окне."""
        wheel = self.wheel
        width = int(min(wheel.width() * 0.86, 520 * self._k))
        self.win_card.setFixedWidth(max(160, width))
        self.win_card.adjustSize()
        self.win_card.move((wheel.width() - self.win_card.width()) // 2,
                           (wheel.height() - self.win_card.height()) // 2)

    def _show_win_card(self, text: str, top: str = None, sub: str = None):
        """Карточка результата. По умолчанию — победный баннер выбранного стиля; для «На выбывание»
        подписи заменяются на «ВЫБЫВАЕТ» и число оставшихся вариантов."""
        th = FORTUNE_THEMES[self._theme]
        self.win_top.setText(top if top is not None else th["win_top"])
        self.win_sub.setText(sub if sub is not None else th["win_sub"])
        self.win_text.setText(text)
        self._place_win_card()
        self.win_card.show()
        self.win_card.raise_()
        self._win_anim.stop()
        self._win_anim.setStartValue(0.0)
        self._win_anim.setEndValue(1.0)
        self._win_anim.start()

    def _hide_win_card(self):
        self._win_anim.stop()
        self.win_card.hide()

    def _on_wheel_resized(self):
        if self.win_card.isVisible():
            self._place_win_card()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_scale()
        if self.win_card.isVisible():
            self._place_win_card()

    # ---------- варианты ----------
    def _fill_list(self):
        self.list.blockSignals(True)
        self.list.clear()
        for text in self._opts:
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._mark_list()

    def _commit(self):
        """Передаёт варианты колесу (любое изменение списка начинает «На выбывание» заново)."""
        self._reset_run(update_wheel=False)
        self.wheel.set_options(self._opts)
        self._update_controls()

    # ---------- режим «На выбывание» ----------
    def _mark_list(self):
        """Выбывшие варианты в списке зачёркнуты и приглушены."""
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            item = self.list.item(i)
            out = i in self._eliminated
            font = item.font()
            font.setStrikeOut(out)
            item.setFont(font)
            if out:
                item.setForeground(QBrush(QColor("#8a80a8")))
            else:
                item.setData(Qt.ItemDataRole.ForegroundRole, None)
        self.list.blockSignals(False)

    def _reset_run(self, update_wheel: bool = True):
        """Новый круг: на колесе снова все варианты, пометки «выбыл» сняты."""
        self._elim_timer.stop()
        self._elim_pending = -1
        self._pool = list(range(len(self._opts)))
        self._eliminated = set()
        self._run_done = False
        self._mark_list()
        if update_wheel:
            self.wheel.set_options(self._opts)

    def _on_elim_toggled(self, on: bool):
        self._elim_on = bool(on)
        self._hide_win_card()
        self._reset_run()
        self._say("Режим «На выбывание»: после каждой крутки один вариант выбывает, пока не останется один."
                  if on else "")
        self._update_controls()

    def _apply_elimination(self):
        """Через паузу после остановки колеса убирает выбывший вариант; когда остался один — объявляет победителя."""
        index = self._elim_pending
        self._elim_pending = -1
        if not (0 <= index < len(self._pool)):
            self._busy = False
            self._update_controls()
            return
        self._eliminated.add(self._pool.pop(index))
        self._mark_list()
        self._hide_win_card()
        self.wheel.set_options([self._opts[i] for i in self._pool])
        self._busy = False
        self._update_controls()
        if len(self._pool) == 1:                              # остался один вариант — он и есть судьба
            self._run_done = True
            self.wheel.highlight(0)
            self._say("Остался один вариант.")
            self.sounds.win()
            self._show_win_card(self._opts[self._pool[0]])
        else:
            self._say(f"Осталось вариантов: {len(self._pool)}")

    def _say(self, text: str):
        self.status.setText(text)

    def _add_option(self):
        if self._busy:
            return
        text = self.new_edit.text().strip()
        if not text:
            self._say("Введите текст нового варианта.")
            return
        if len(self._opts) >= FORTUNE_MAX_OPTIONS:
            self._say(f"Максимум вариантов: {FORTUNE_MAX_OPTIONS}.")
            return
        self._opts.append(text)
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.list.blockSignals(True)
        self.list.addItem(item)
        self.list.blockSignals(False)
        self.new_edit.clear()
        self._say("")
        self._hide_win_card()
        self._commit()

    def _delete_option(self):
        if self._busy:
            return
        row = self.list.currentRow()
        if row < 0:
            self._say("Выберите вариант, который нужно удалить.")
            return
        del self._opts[row]
        self.list.blockSignals(True)
        self.list.takeItem(row)
        self.list.blockSignals(False)
        self._say("")
        self._hide_win_card()
        self._commit()

    def _reset_options(self):
        if self._busy:
            return
        self._opts = list(FORTUNE_DEFAULT_OPTIONS)
        self._fill_list()
        self._say("Подставлены примерные варианты — измените их или очистите список.")
        self._hide_win_card()
        self._commit()

    def _clear_options(self):
        if self._busy:
            return
        self._opts = []
        self._fill_list()
        self._say("Список очищен: впишите свои варианты.")
        self._hide_win_card()
        self._commit()

    def _on_item_changed(self, item):
        if self._busy:
            return
        row = self.list.row(item)
        text = item.text().strip()
        if not (0 <= row < len(self._opts)):
            return
        if not text:                                          # пустой вариант не допускается
            self.list.blockSignals(True)
            item.setText(self._opts[row])
            self.list.blockSignals(False)
            self._say("Вариант не может быть пустым.")
            return
        self._opts[row] = text
        self._say("")
        self._hide_win_card()
        self._commit()

    def _update_controls(self):
        enough = len(self._opts) >= FORTUNE_MIN_OPTIONS
        self.spin_btn.setEnabled(enough and not self._busy)
        for wdg in (self.list, self.new_edit, self.add_btn, self.del_btn, self.reset_btn, self.clear_btn,
                    self.style_combo, self.elim_check):
            wdg.setEnabled(not self._busy)

    # ---------- вращение ----------
    def _spin(self):
        if self._busy or len(self._opts) < FORTUNE_MIN_OPTIONS:
            return
        if self._elim_on and len(self._opts) >= 2 and (self._run_done or len(self._pool) < 2):
            self._reset_run()                                 # предыдущий круг закончен — начинаем новый со всеми вариантами
        if self._elim_on and len(self._pool) >= 2:
            self._say(f"Осталось вариантов: {len(self._pool)}")
        self._hide_win_card()
        self._busy = True
        self._update_controls()                               # кнопка «Удачи!» недоступна, пока колесо крутится
        if not self.wheel.spin():
            self._busy = False
            self._update_controls()

    def _on_finished(self, index: int):
        self.sounds.set_spin(0.0, False)
        if self._spin_done_cb is not None:
            try:
                self._spin_done_cb()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        if self._elim_on and len(self._pool) > 1 and 0 <= index < len(self._pool):
            # «На выбывание»: выпавший вариант выбывает. Сектор подсвечен, карточка сообщает об этом,
            # а через паузу вариант убирается с колеса (кнопки пока недоступны).
            self._elim_pending = index
            self.sounds.tick(260.0)
            self._show_win_card(self._opts[self._pool[index]], top="ВЫБЫВАЕТ",
                                sub=f"Осталось вариантов: {len(self._pool) - 1}")
            self._elim_timer.start(1900)
            return
        self._busy = False
        self._update_controls()
        self.sounds.win()                                     # победный перезвон
        if 0 <= index < len(self.wheel.options):
            shown = self._opts[self._pool[index]] if index < len(self._pool) else self.wheel.options[index]
            self._show_win_card(shown)

    def _on_sound_toggled(self, on: bool):
        self.sounds.enabled = on
        if not on:
            self.sounds.stop_all()
        self.sounds.refresh()

    # ---------- жизненный цикл ----------
    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_started", False):
            self._started = True
            QTimer.singleShot(0, self._fit_button_texts)      # ширина панели известна только после показа
            self._duck(True)                                  # основная музыка приглушается на время окна
            QTimer.singleShot(60, self._start_sounds)         # звуки создаются после показа окна

    def _start_sounds(self):
        self.sounds.prepare()
        self.sounds.start_ambient()

    def done(self, result):
        self._elim_timer.stop()
        self.wheel.stop_now()
        self._win_anim.stop()
        self.sounds.shutdown()
        if getattr(self, "_started", False):
            self._duck(False)
            self._started = False
        super().done(result)
