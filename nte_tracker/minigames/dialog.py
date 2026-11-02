"""Окно выбора мини-игры."""

import traceback

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from .arkanoid import ArkanoidWidget, MINIGAME_ARKANOID_KEY, MINIGAME_PLATFORMER_KEY
from .asteroids import AsteroidsWidget, MINIGAME_ASTEROIDS_KEY
from .audio import GameAudio, MINIGAME_INVADERS_KEY, MINIGAME_SOUND_OFF_KEY
from .invaders import InvadersWidget
from .platformer import PlatformerWidget


class MiniGameDialog(QDialog):
    """Окно мини-игр с меню выбора («Арканоид» / «Платформер»). Не блокирует главное окно:
    пока идёт обработка скриншотов, можно играть и следить за ходом обработки. Игра создаётся
    при выборе и полностью освобождается при возврате в меню или закрытии окна: таймер
    останавливается, рекорд сохраняется, виджеты удаляются (WA_DeleteOnClose)."""

    GAMES = (
        ("invaders", "Космические захватчики", "Стреляйте по пришельцам и укрывайтесь за щитами",
         InvadersWidget, MINIGAME_INVADERS_KEY,
         "← → — движение · ↑ / Пробел — огонь · P — пауза · Esc — пауза / выход в меню"),
        ("arkanoid", "Арканоид", "Разбивайте блоки мячом и не давайте ему упасть",
         ArkanoidWidget, MINIGAME_ARKANOID_KEY,
         "← → или мышь — платформа · Пробел / ↑ / щелчок — запуск мяча · P — пауза · Esc — пауза / выход"),
        ("platformer", "Платформер", "3 уровня: монеты, Гриб, Огненный цветок и Звезда — доберитесь до флага",
         PlatformerWidget, MINIGAME_PLATFORMER_KEY,
         "← → — бег · Пробел / ↑ — прыжок · F / Ctrl — огненный шар · P — пауза · Esc — пауза / выход в меню"),
        ("asteroids", "Астероиды", "Разбивайте астероиды лазером и не сталкивайтесь с обломками",
         AsteroidsWidget, MINIGAME_ASTEROIDS_KEY,
         "← → / A D — поворот · ↑ / W — тяга · Пробел — огонь · P — пауза · Esc — пауза / выход в меню"),
    )

    def __init__(self, get_high_score, save_high_score, parent=None, on_game_started=None):
        super().__init__(parent)
        self._on_game_started = on_game_started              # колбэк для достижений: игра запущена
        self.setWindowTitle("Поиграй 🎮 — Мини-игры")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setModal(False)
        self.setMinimumSize(320, 420)
        self.resize(640, 720)
        self.setSizeGripEnabled(True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._get_high = get_high_score
        self._save_high = save_high_score
        self.game = None
        try:
            sound_on = int(self._get_high(MINIGAME_SOUND_OFF_KEY) or 0) == 0
        except (TypeError, ValueError):
            sound_on = True
        self.audio = GameAudio(sound_on, self)
        QTimer.singleShot(0, self.audio.prepare)  # звуки готовятся заранее, чтобы первый выстрел не «тонул»
        self.setStyleSheet(
            "QDialog { background: #0b0f1a; }"
            "QPushButton#gameChoice { background: #141b33; color: #e8edff; border: 2px solid #3a4a8a;"
            " border-radius: 12px; padding: 14px; font-size: 16px; font-weight: bold; text-align: left; }"
            "QPushButton#gameChoice:hover, QPushButton#gameChoice:focus { border-color: #ffd84a; background: #1b2548; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        self.sound_cb = QCheckBox("Звук в играх")
        self.sound_cb.setChecked(self.audio.enabled)
        self.sound_cb.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # чтобы Пробел не переключал галочку
        self.sound_cb.setStyleSheet("QCheckBox { color: #9fb4ff; font-size: 13px; }")
        self.sound_cb.toggled.connect(self._on_sound_toggled)
        root.addWidget(self.sound_cb, 0, Qt.AlignmentFlag.AlignRight)
        self.stack = QStackedWidget(self)
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.stack, 1)

        # --- страница 0: меню выбора игры ---
        menu = QWidget()
        mlay = QVBoxLayout(menu)
        mlay.setSpacing(12)
        mlay.addStretch(1)
        title = QLabel("МИНИ-ИГРЫ")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #ffd84a; font-size: 26px; font-weight: bold; letter-spacing: 4px;")
        mlay.addWidget(title)
        sub = QLabel("Выберите игру. Обработка скриншотов идёт в фоне — окно можно оставить открытым.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #9fb4ff; font-size: 13px;")
        mlay.addWidget(sub)
        self._choice_buttons = []
        for idx, (_gid, name, desc, _cls, _key, _hint) in enumerate(self.GAMES):
            btn = QPushButton()
            btn.setObjectName("gameChoice")
            btn.setMinimumHeight(78)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, i=idx: self.open_game(i))
            mlay.addWidget(btn)
            self._choice_buttons.append(btn)
        mlay.addStretch(1)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.close)
        mlay.addWidget(close_btn)
        self.stack.addWidget(menu)

        # --- страница 1: игра ---
        page = QWidget()
        self._game_layout = QVBoxLayout(page)
        self._game_layout.setContentsMargins(0, 0, 0, 0)
        self._game_layout.setSpacing(8)
        self._game_title = QLabel("")
        self._game_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._game_title.setStyleSheet("color: #7da2ff; font-size: 18px; font-weight: bold; letter-spacing: 3px;")
        self._game_layout.addWidget(self._game_title)
        self._game_slot = QVBoxLayout()               # сюда помещается виджет игры
        self._game_layout.addLayout(self._game_slot, 1)
        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setStyleSheet("color: #9fb4ff; font-size: 12px;")
        self._game_layout.addWidget(self._hint)
        row = QHBoxLayout()
        pause_btn = QPushButton("Пауза / продолжить")
        menu_btn = QPushButton("К выбору игры")
        end_btn = QPushButton("Закрыть")
        for btn in (pause_btn, menu_btn, end_btn):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # чтобы Пробел не нажимал кнопки
            row.addWidget(btn)
        pause_btn.clicked.connect(self._toggle_pause)
        menu_btn.clicked.connect(self.back_to_menu)
        end_btn.clicked.connect(self.close)
        self._game_layout.addLayout(row)
        self.stack.addWidget(page)

        self._refresh_menu()

    # ---------- меню ----------
    def _refresh_menu(self):
        for btn, (_gid, name, desc, _cls, key, _hint) in zip(self._choice_buttons, self.GAMES):
            btn.setText(f"{name}\n{desc}\nРекорд: {self._get_high(key)}")

    def open_game(self, index: int):
        """Создаёт выбранную игру и показывает её вместо меню."""
        if self.game is not None:
            return
        gid, name, _desc, cls, key, hint = self.GAMES[index]
        self.game = cls(self._get_high(key), self)
        self.game.highScoreChanged.connect(lambda value, k=key: self._on_high_score(k, value))
        self.game.closeRequested.connect(lambda: QTimer.singleShot(0, self.back_to_menu))
        self.game.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.game.engine.sfx = self.audio.play     # звуки игры (отключаются галочкой «Звук в играх»)
        self._game_slot.addWidget(self.game, 1)
        self._game_title.setText(name.upper())
        self._hint.setText(hint)
        self.stack.setCurrentIndex(1)
        self.game.start_loop()
        self.game.setFocus()
        if self._on_game_started is not None:
            try:
                self._on_game_started(gid)
            except Exception:  # noqa: BLE001 — достижения не должны ломать игру
                traceback.print_exc()

    def back_to_menu(self):
        """Закрывает текущую игру (таймер остановлен, рекорд сохранён, виджет удалён) и возвращает меню."""
        game, self.game = self.game, None
        self.audio.stop_all()
        if game is not None:
            game.engine.sfx = None
            game.shutdown()
            self._game_slot.removeWidget(game)
            game.setParent(None)
            game.deleteLater()
        self.stack.setCurrentIndex(0)
        self._refresh_menu()
        if self._choice_buttons:
            self._choice_buttons[0].setFocus()

    def _toggle_pause(self):
        game = self.game
        if game is None:
            return
        eng = game.engine
        if eng.state == "playing":
            eng.pause()
        elif eng.state == "paused":
            eng.resume()
        game.update()
        game.setFocus()

    def _on_sound_toggled(self, checked: bool):
        self.audio.set_enabled(checked)
        try:
            self._save_high(MINIGAME_SOUND_OFF_KEY, 0 if checked else 1)
        except Exception:  # noqa: BLE001 — настройка звука не должна ронять окно игры
            pass
        if checked:
            self.audio.play("coin")
        if self.game is not None:
            self.game.setFocus()

    def _on_high_score(self, key: str, value: int):
        try:
            self._save_high(key, value)
        except Exception:  # noqa: BLE001 — рекорд не должен ронять окно игры
            pass

    def showEvent(self, event):
        super().showEvent(event)
        if self.game is not None:
            self.game.setFocus()
        elif self._choice_buttons:
            self._choice_buttons[0].setFocus()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange and self.game is not None:
            if not self.isActiveWindow():
                self.game.pause()                # окно потеряло фокус — автопауза
                self.game.stop_loop()            # и таймер кадров не крутится в фоне (OCR не страдает)
                self.audio.stop_all()
            else:
                self.game.start_loop()
                self.game.setFocus()
        super().changeEvent(event)

    def hideEvent(self, event):
        if self.game is not None:
            self.game.pause()
            self.game.stop_loop()
        self.audio.stop_all()
        super().hideEvent(event)

    def done(self, result):
        game, self.game = self.game, None
        if game is not None:
            game.engine.sfx = None
            game.shutdown()                      # остановить таймер и сохранить рекорд
        self.audio.release()                     # остановить и освободить все звуки
        super().done(result)
