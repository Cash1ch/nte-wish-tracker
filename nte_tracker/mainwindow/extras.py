"""Достижения, профиль, Колесо Фортуны и мини-игры (обработчики событий окна)."""

import time
import traceback

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from ..achievements import APP_SECONDS_KEY, FORTUNE_SPINS_KEY, MINIGAME_PLAYS_KEY
from ..fortune.dialog import FortuneDialog
from ..fortune.themes import FORTUNE_NTE_KEY, FORTUNE_STYLE_KEY, FORTUNE_THEMES
from ..labels import _safe_int
from ..minigames.dialog import MiniGameDialog
from ..ui.achievement_widgets import AchievementToast, play_achievement_sound
from ..ui.falling_background import volume_to_linear
from ..ui.profile_avatar import ProfileDialog


class ExtrasMixin:
    """Достижения, профиль, Колесо Фортуны и мини-игры (обработчики событий окна)."""

    # ---------- НОВОЕ: достижения ----------
    def _check_achievements(self, *_):
        """Пересчитывает достижения активного профиля и показывает уведомления о новых."""
        mgr = getattr(self, "achievements", None)
        if mgr is None:
            return
        try:
            fresh = mgr.evaluate(self.stats, self.history)
        except Exception:  # noqa: BLE001 — достижения не должны ронять обновление данных
            traceback.print_exc()
            return
        if fresh:
            self._ach_queue.extend(fresh)
            if self._ach_toast is None:
                self._show_next_achievement()

    def _tick_app_time(self):
        now = time.monotonic()
        delta = min(int(now - self._time_mark), 120)
        self._time_mark = now
        if delta <= 0 or not self.db.profile_id:
            return
        if QApplication.applicationState() != Qt.ApplicationState.ApplicationActive:
            return
        total = _safe_int(self.db.get_setting(APP_SECONDS_KEY, "0", scoped=True)) + delta
        self.db.set_setting(APP_SECONDS_KEY, str(total), scoped=True)
        self._check_achievements()

    def _on_minigame_started(self, gid: str):
        """Мини-игра запущена: считаем запуски и пробованные игры профиля."""
        n = _safe_int(self.db.get_setting(MINIGAME_PLAYS_KEY, "0", scoped=True)) + 1
        self.db.set_setting(MINIGAME_PLAYS_KEY, str(n), scoped=True)
        self.db.set_setting(f"minigame_tried_{gid}", "1", scoped=True)
        self._check_achievements()

    def _on_fortune_spin(self):
        """Колесо фортуны прокручено: считаем вращение профиля и проверяем достижения."""
        n = _safe_int(self.db.get_setting(FORTUNE_SPINS_KEY, "0", scoped=True)) + 1
        self.db.set_setting(FORTUNE_SPINS_KEY, str(n), scoped=True)
        self._check_achievements()

    def _show_next_achievement(self):
        if not self._ach_queue:
            self._ach_toast = None
            return
        ach = self._ach_queue.pop(0)
        host = QApplication.activeModalWidget() or QApplication.activeWindow() or self
        toast = AchievementToast(host, ach)
        self._ach_toast = toast
        toast.destroyed.connect(self._on_achievement_toast_gone)
        toast.start()
        play_achievement_sound(getattr(self, "music", None))

    def _on_achievement_toast_gone(self, *_):
        self._ach_toast = None
        QTimer.singleShot(250, self._show_next_achievement)

    def open_profile_dialog(self, *_):
        """Открывает окно профиля (аватарка, имя, статистика) по клику на «Профиль: …»."""
        if not self.db.profile_id:
            return
        self._check_achievements()
        dlg = ProfileDialog(self.db, self.stats, self.history, self,
                            self.achievements, self._check_achievements)
        dlg.exec()
        self._update_profile_label()
        if dlg.renamed and hasattr(self, "_refresh_profile_ui"):
            self._refresh_profile_ui()

    def open_fortune_wheel(self):
        """Безопасная обёртка: ошибка при создании окна показывается сообщением, а не закрывает приложение."""
        try:
            self._open_fortune_wheel()
        except Exception as exc:  # noqa: BLE001
            self._fortune_dlg = None
            traceback.print_exc()
            QMessageBox.warning(self, "Колесо Фортуны", f"Не удалось открыть колесо: {exc}")

    def _open_fortune_wheel(self):
        """Открывает «Колесо Фортуны» (одно окно на приложение). Окно не модальное: обработка
        скриншотов в фоновых потоках и главное окно продолжают работать как обычно."""
        dlg = getattr(self, "_fortune_dlg", None)
        if dlg is not None:
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return

        def get_master():
            return volume_to_linear(self.music.volume), self.music.muted

        def get_style():
            name = self.db.get_setting(FORTUNE_STYLE_KEY, "") or ""
            if name in FORTUNE_THEMES:
                return name
            # прежняя настройка «Стиль NTE» (1 / 0), если новая ещё не сохранена
            return "nte" if (self.db.get_setting(FORTUNE_NTE_KEY, "0") or "0") == "1" else "classic"

        def set_style(name):
            self.db.set_setting(FORTUNE_STYLE_KEY, name if name in FORTUNE_THEMES else "classic")

        dlg = FortuneDialog(get_master, self.music.set_ducked, get_style, set_style, self,
                            self._on_fortune_spin)
        dlg.finished.connect(self._on_fortune_closed)
        self._fortune_dlg = dlg
        dlg.show()

    def _on_fortune_closed(self, *_args):
        self._fortune_dlg = None                 # окно удалится само (WA_DeleteOnClose)

    def open_minigame(self):
        """Открывает окно мини-игры (одно на приложение). Окно не модальное: обработка
        скриншотов в фоновых потоках и главное окно продолжают работать как обычно."""
        dlg = getattr(self, "_minigame_dlg", None)
        if dlg is not None:
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return
        def get_high(key):
            try:
                return int(self.db.get_setting(key, "0") or 0)
            except (TypeError, ValueError):
                return 0

        def save_high(key, value):
            self.db.set_setting(key, str(int(value)))

        dlg = MiniGameDialog(get_high, save_high, self, self._on_minigame_started)
        dlg.finished.connect(self._on_minigame_closed)
        self._minigame_dlg = dlg
        dlg.show()

    def _on_minigame_closed(self, *_args):
        self._minigame_dlg = None                # окно удалится само (WA_DeleteOnClose)
