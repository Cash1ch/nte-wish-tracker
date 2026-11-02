"""Главное окно: собирается из миксинов по вкладкам."""

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QApplication, QLabel, QMainWindow, QMessageBox, QTabWidget, QWidget

from ..achievements import AchievementManager
from ..catalog import ARC_KNOWN, ROSTER_KNOWN
from ..config import (
    ANIM_DEFAULT_EFFECT, ANIM_EFFECT_KEY, ANIM_EFFECTS, ANIM_ENABLED_KEY, APP_TITLE, BANNER_AUTODETECT,
    BANNER_REFRESH_MS, BANNER_TICK_MS, SEARCH_DELAY_MS, TIME_SAVE_DELAY_MS,
)
from ..constellation.tab import ConstellationTab
from ..database import Database
from ..errors import DatabaseError
from ..icons import _ICON_CACHE, _PATH_CACHE
from ..ocr.names import refresh_master_names
from ..simulation.tab import SimulationTab
from ..stats import build_timeline, compute_stats, history_entries
from ..ui.music import BackgroundMusic, MusicControls
from ..ui.theme import apply_app_style, apply_glass_shadows, draw_glass_backdrop, reset_background_cache
from ..ui.toast import ToastNotification
from ..workers.banner_feed import _LIVE_OCR_THREADS
from ..workers.ocr_threads import _LIVE_BATCH_THREADS
from .banners import BannersMixin
from .dataio import DataIoMixin
from .extras import ExtrasMixin
from .history import HistoryMixin
from .manual import ManualMixin
from .map import MapMixin
from .mass import MassMixin
from .profiles import ProfilesMixin
from .screenshot import ScreenshotMixin
from .staff import StaffMixin


class MainWindow(
        BannersMixin,
        StaffMixin,
        ExtrasMixin,
        HistoryMixin,
        ManualMixin,
        ScreenshotMixin,
        MassMixin,
        MapMixin,
        ProfilesMixin,
        DataIoMixin,
        QMainWindow,
    ):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.rows, self.rewards, self.history = [], [], []
        # known: {имя в нижнем регистре: (имя, ранг, баннер)} — подсказки формы и OCR
        self.stats, self.pity_at, self.known = {}, {}, {}

        # Таймеры отложенных действий (создаются ДО построения вкладок).
        # Поиск в истории не перестраивает таблицу на каждую букву, а время формы
        # не пишется в БД на каждое движение стрелок в поле даты.
        self._hist_timer = self._make_timer(SEARCH_DELAY_MS, self._refresh_history)
        self._dt_timer = self._make_timer(TIME_SAVE_DELAY_MS, self._save_form_dt)

        self.setWindowTitle(APP_TITLE)
        self.resize(1120, 800)

        # НОВОЕ: сохранённые настройки фоновой анимации (читаются ДО построения вкладок)
        self._anim_enabled = self.db.get_setting(ANIM_ENABLED_KEY, "1") != "0"
        effect = self.db.get_setting(ANIM_EFFECT_KEY, ANIM_DEFAULT_EFFECT)
        self._anim_effect = effect if effect in dict(ANIM_EFFECTS) else ANIM_DEFAULT_EFFECT

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        for build, title in ((self._build_staff, "Стафф"),
                             (self._build_history, "История"),
                             (self._build_add, "Добавить крутку"),
                             (self._build_map, "Карта"),
                             (self._build_constellation, "Созвездие"),
                             (self._build_settings, "Настройки")):
            self.tabs.addTab(build(), title)
        self.tabs.currentChanged.connect(self._on_main_tab_changed)
        apply_glass_shadows(self.tabs)  # НОВОЕ: тени под всеми блоками QGroupBox

        # НОВОЕ: фоновая музыка. Панель управления встаёт в правый верхний угол строки
        # вкладок — компактно и на одном уровне с остальным интерфейсом. Нет файла или
        # QtMultimedia — панель просто неактивна, приложение работает как обычно.
        self.music = BackgroundMusic(db, self)
        self.achievements = AchievementManager(db)   # НОВОЕ: достижения
        self._ach_queue, self._ach_toast = [], None
        self._time_mark = time.monotonic()           # учёт времени в приложении (только пока окно активно)
        self._time_timer = QTimer(self)
        self._time_timer.setInterval(30000)
        self._time_timer.timeout.connect(self._tick_app_time)
        self._time_timer.start()
        self.music_controls = MusicControls(self.music)
        self.tabs.setCornerWidget(self.music_controls, Qt.Corner.TopRightCorner)
        self.music.start()  # трек сразу запускается и играет по кругу

        self.refresh()

        # НОВОЕ: автоопределение текущего баннера. Запускается ПОСЛЕ построения интерфейса
        # и работает в фоне — окно открывается сразу, даже без интернета.
        self._banner_thread = None
        self._banner_info = None          # последний ответ сервера (имя и сроки) или None
        # Таймер обратного отсчёта: пересчитывает панель баннеров («Стафф») по datetime.now()
        # раз в 30 секунд.
        # Идёт ВСЕГДА, даже если запрос не удался: тогда на плитках «Время не указано».
        self._banner_tick = QTimer(self)
        self._banner_tick.setInterval(BANNER_TICK_MS)
        self._banner_tick.timeout.connect(self._update_banner_countdown)
        self._banner_tick.start()
        self._banner_user_picked = False  # True, если пользователь сам менял «Баннер (пул)»
        self.in_banner.activated.connect(self._on_banner_user_picked)  # activated — только от человека
        self.shot_banner.activated.connect(self._on_banner_user_picked)  # то же — на вкладке «Скриншот»
        self.mass_banner.activated.connect(self._on_banner_user_picked)   # и на «Скриншоты разом»
        if BANNER_AUTODETECT:
            self._start_banner_fetch()
            # ОБНОВЛЕНО: периодическое перечитывание banners.json — новые баннеры и сроки
            # подхватываются без перезапуска; сами сроки приходят из JSON, а не из кода
            self._banner_refresh = QTimer(self)
            if BANNER_REFRESH_MS > 0:
                self._banner_refresh.setInterval(BANNER_REFRESH_MS)
                self._banner_refresh.timeout.connect(self._refresh_banner_fetch)
                self._banner_refresh.start()

    def _make_timer(self, interval_ms: int, slot) -> QTimer:
        """Одноразовый таймер: повторный start() перезапускает отсчёт (debounce)."""
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(interval_ms)
        timer.timeout.connect(slot)
        return timer

    def paintEvent(self, event):
        """НОВОЕ: рисует градиентный фон окна — «подложку» для стеклянных панелей."""
        painter = QPainter(self)
        draw_glass_backdrop(painter, self.rect())
        painter.end()

    def closeEvent(self, event):
        """При закрытии окна сохраняем время формы, если запись ещё ждёт своей очереди,
        а также громкость музыки и останавливаем плеер (НОВОЕ)."""
        self._map_shutdown()
        if self._dt_timer.isActive():
            self._dt_timer.stop()
            self._save_form_dt()
        fate = getattr(self, "_fortune_dlg", None)    # колесо: остановить таймеры и звуки
        if fate is not None:
            fate.close()
        self.fate_glow.stop()
        game = getattr(self, "_minigame_dlg", None)   # мини-игра: остановить таймер и сохранить рекорд
        if game is not None:
            game.close()
        self.music.shutdown()
        self._banner_tick.stop()
        if getattr(self, "_banner_refresh", None) is not None:
            self._banner_refresh.stop()
        self._stop_banner_thread()  # НОВОЕ: не оставляем работающий QThread при выходе
        self._stop_ocr_thread()
        self._stop_mass_thread()    # НОВОЕ: поток «Скриншоты разом»
        super().closeEvent(event)

    def _stop_mass_thread(self):
        """НОВОЕ: аккуратно гасит поток «Скриншоты разом» и «порции» разбора при закрытии окна."""
        for name in ("_mass_clock", "_mass_pump"):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.stop()
        job, self._mass_job = getattr(self, "_mass_job", None), None
        if job is not None:
            job.close()
        thread = getattr(self, "_mass_thread", None)
        if thread is None:
            return
        try:
            thread.progress.disconnect()
            thread.file_done.disconnect()
            thread.file_failed.disconnect()
            thread.finished.disconnect()
        except TypeError:
            pass
        thread.requestInterruption()      # остановится после текущего файла
        if thread.isRunning() and not thread.wait(5000):
            _LIVE_BATCH_THREADS.add(thread)
            thread.setParent(None)
            thread.finished.connect(lambda t=thread: _LIVE_BATCH_THREADS.discard(t))
        self._mass_thread = None

    def _stop_ocr_thread(self):
        """НОВОЕ: аккуратно гасит поток OCR при закрытии окна (как и поток баннеров)."""
        thread = getattr(self, "_ocr_thread", None)
        if thread is None:
            return
        try:
            thread.done.disconnect()
            thread.failed.disconnect()
        except TypeError:
            pass
        if thread.isRunning() and not thread.wait(3000):
            _LIVE_OCR_THREADS.add(thread)
            thread.setParent(None)
            thread.finished.connect(lambda t=thread: _LIVE_OCR_THREADS.discard(t))
        self._ocr_thread = None

    # ---------- диалоги ----------
    def info(self, text, title="Информация"):
        QMessageBox.information(self, title, text)

    def warn(self, text, title="Внимание"):
        QMessageBox.warning(self, title, text)

    def error(self, text, title="Ошибка"):
        QMessageBox.critical(self, title, text)

    def ask(self, text, title="Подтверждение") -> bool:
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        return QMessageBox.question(self, title, text, yes | no, no) == yes

    @staticmethod
    def _set_row_visible(label: QLabel, widget: QWidget, visible: bool):
        label.setVisible(visible)
        widget.setVisible(visible)

    def _show_toast(self, text: str):
        if getattr(self, "_toast", None) is None:
            self._toast = ToastNotification(self)
        self._toast.show_message(text)

    # ---------- общее обновление ----------
    def refresh(self, *_):
        """Перечитывает базу и обновляет все вкладки. Время формы не затрагивается."""
        try:
            self.rows = self.db.fetch_all()
            self.rewards = self.db.fetch_rewards()
        except DatabaseError as e:
            self.error(str(e))
            return
        _PATH_CACHE.clear()
        _ICON_CACHE.clear()
        reset_background_cache()                     # НОВОЕ: фон перечитывается вместе с иконками
        apply_app_style(QApplication.instance())
        self.update()
        events = build_timeline(self.rows, self.rewards)
        self.stats, self.pity_at = compute_stats(events)
        self.history = history_entries(events, self.pity_at)
        # known: {имя в нижнем регистре: (имя, ранг, баннер)} — подсказки формы и OCR.
        # Названия-заглушки («Персонаж», «Дуга») и кешбэк в подсказки не попадают.
        self.known = {}
        for r in self.rows:
            if r.get("cashback") or r["name"] in ("Персонаж", "Дуга"):
                continue
            self.known[r["name"].lower()] = (r["name"], r["rarity"], r["banner"])
        # НОВОЕ: составы персонажей (ROSTER_*) — в подсказки названий, автоопределение
        # ранга, OCR и список привязки, даже если персонаж ещё не выпадал
        for key, value in ROSTER_KNOWN.items():
            self.known.setdefault(key, value)
        # НОВОЕ: дуги A ранга из мастер-справочника (ARC_KNOWN) — подсказки и автоопределение ранга
        for key, value in ARC_KNOWN.items():
            self.known.setdefault(key, value)
        # НОВОЕ: мастер-справочник OCR пополняется названиями из базы (костюмы, планеры…)
        refresh_master_names(self.rewards)
        self._refresh_type_icons()
        self._refresh_staff()
        self._refresh_profile_ui()
        self._refresh_history()
        self._refresh_add_helpers()
        if getattr(self, "sim_tab", None) is not None:
            self.sim_tab.reload_lists()
        self._check_achievements()      # НОВОЕ: импорт, ручное добавление, смена профиля

    def _on_main_tab_changed(self, idx: int):
        on_map = self.tabs.widget(idx) is getattr(self, "_map_holder", None)
        if on_map and self._map_view is None:
            self._init_map_view()
        self._map_set_active(on_map)

    def _build_constellation(self) -> QWidget:
        """НОВОЕ: вкладка «Созвездие» — интерактивная сеть узлов вокруг портрета персонажа."""
        self.constellation_tab = ConstellationTab(self)
        return self.constellation_tab

    def _build_simulation(self) -> QWidget:
        self.sim_tab = SimulationTab(self.db)
        return self.sim_tab
