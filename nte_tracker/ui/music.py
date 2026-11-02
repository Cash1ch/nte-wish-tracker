"""Фоновая музыка и панель управления громкостью."""

from PyQt6.QtCore import pyqtSignal, QObject, QSize, Qt, QTimer, QUrl
from PyQt6.QtWidgets import QHBoxLayout, QSlider, QStyle, QToolButton, QWidget

from ..compat import QAudioOutput, QMediaPlayer
from ..config import MUSIC_DEFAULT_VOLUME, MUSIC_FILE, MUSIC_MUTED_KEY, MUSIC_SAVE_DELAY_MS, MUSIC_VOLUME_KEY
from ..database import Database
from ..errors import blocked
from ..labels import _safe_int
from ..paths import find_music_file
from .falling_background import volume_to_linear
from .widgets import make_label


class BackgroundMusic(QObject):
    """Фоновая музыка: QMediaPlayer + QAudioOutput, бесконечный цикл.

    Класс ничего не знает об интерфейсе и никогда не бросает исключений наружу:
    при любой проблеме (нет модуля QtMultimedia, нет файла, сбой бэкенда, ошибка
    декодера) музыка просто отключается, выставляется текст причины в error_text и
    излучается сигнал availability_changed — панель управления тогда блокируется.

    Громкость (0..100) и состояние «звук выключен» хранятся в таблице settings базы
    данных и восстанавливаются при следующем запуске.
    """

    availability_changed = pyqtSignal()  # изменилась доступность музыки / текст ошибки

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._ducked = False     # НОВОЕ: музыка приглушена (открыто «Колесо Фортуны»)
        self.player = None       # QMediaPlayer (None, если музыка недоступна)
        self.audio = None        # QAudioOutput
        self.path = None         # Path найденного файла
        self.error_text = ""     # причина недоступности (пусто — всё в порядке)

        # Громкость и mute читаем из БД; при порче значения берём значения по умолчанию
        self.volume = max(0, min(100, _safe_int(
            db.get_setting(MUSIC_VOLUME_KEY), MUSIC_DEFAULT_VOLUME)))
        self.muted = db.get_setting(MUSIC_MUTED_KEY, "0") == "1"

        # Запись в БД с задержкой: ползунок шлёт десятки сигналов в секунду
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(MUSIC_SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save_settings)

        self._init_player()

    @property
    def available(self) -> bool:
        """True, если плеер создан и не сообщил об ошибке."""
        return self.player is not None and not self.error_text

    # ---------- инициализация ----------
    def _init_player(self):
        if QMediaPlayer is None or QAudioOutput is None:
            self.error_text = ("Музыка недоступна: модуль QtMultimedia не найден "
                               "(переустановите PyQt6).")
            return
        self.path = find_music_file()
        if self.path is None:
            self.error_text = (f"Музыка отключена: файл не найден.\n"
                               f"Положите трек в «{MUSIC_FILE}» рядом с программой.")
            return
        try:
            self.audio = QAudioOutput(self)
            self.player = QMediaPlayer(self)
            self.player.setAudioOutput(self.audio)
            try:
                self.player.setLoops(QMediaPlayer.Loops.Infinite)  # бесконечный цикл
            except (AttributeError, TypeError):
                self.player.setLoops(-1)                           # то же числом
            self.player.errorOccurred.connect(self._on_error)
            self.player.mediaStatusChanged.connect(self._on_status)
            self._apply_volume()
            self.audio.setMuted(self.muted)
            self.player.setSource(QUrl.fromLocalFile(str(self.path)))
        except Exception as e:  # noqa: BLE001 — сбой мультимедиа-бэкенда не должен ронять программу
            self._fail(f"Не удалось запустить музыку: {e}")

    def _fail(self, text: str):
        """Отключает музыку (один раз): запоминает причину и уведомляет интерфейс."""
        if self.error_text:
            return
        self.error_text = text
        if self.player is not None:
            try:
                self.player.stop()
            except Exception:  # noqa: BLE001
                pass
        self.availability_changed.emit()

    def _on_error(self, error, text=""):
        self._fail(f"Ошибка воспроизведения музыки: {text or error}")

    def _on_status(self, status):
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._fail(f"Не удалось открыть файл музыки:\n{self.path}")

    # ---------- управление ----------
    def start(self):
        """Запускает воспроизведение (вызывается один раз при старте приложения)."""
        if self.available:
            try:
                self.player.play()
            except Exception as e:  # noqa: BLE001
                self._fail(f"Не удалось запустить музыку: {e}")

    def _apply_volume(self):
        if self.audio is not None:
            self.audio.setVolume(volume_to_linear(self.volume) * (0.25 if self._ducked else 1.0))

    def set_ducked(self, ducked: bool):
        """Приглушает основную музыку на время «Колеса Фортуны» (настройка громкости не меняется)."""
        self._ducked = bool(ducked)
        self._apply_volume()

    def set_volume(self, percent: int):
        """Громкость 0..100: применяется сразу (QAudioOutput.setVolume), в БД — с задержкой."""
        self.volume = max(0, min(100, int(percent)))
        self._apply_volume()
        self._save_timer.start()

    def set_muted(self, muted: bool):
        """Включает / выключает звук (воспроизведение при этом не останавливается)."""
        self.muted = bool(muted)
        if self.audio is not None:
            self.audio.setMuted(self.muted)
        self._save_timer.start()

    def save_settings(self):
        """Записывает громкость и mute в БД."""
        self._save_timer.stop()
        self.db.set_setting(MUSIC_VOLUME_KEY, str(self.volume))
        self.db.set_setting(MUSIC_MUTED_KEY, "1" if self.muted else "0")

    def shutdown(self):
        """Сохраняет настройки и освобождает плеер (вызывается при закрытии окна)."""
        self.save_settings()
        if self.player is not None:
            try:
                self.player.stop()
                self.player.setSource(QUrl())  # отпускаем файл
            except Exception:  # noqa: BLE001
                pass



class MusicControls(QWidget):
    """Компактная панель музыки: кнопка «звук вкл/выкл» + ползунок 0–100 + подпись в %.
    Размещается в правом верхнем углу строки вкладок (QTabWidget.setCornerWidget).
    Если музыка недоступна — вся панель заблокирована, причина видна в подсказке."""

    def __init__(self, music: BackgroundMusic, parent=None):
        super().__init__(parent)
        self.music = music

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 8, 2)
        lay.setSpacing(6)

        self.btn_mute = QToolButton()
        self.btn_mute.setIconSize(QSize(18, 18))
        self.btn_mute.setFixedSize(30, 28)
        self.btn_mute.clicked.connect(self._toggle_mute)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(music.volume)
        self.slider.setFixedWidth(110)
        self.slider.valueChanged.connect(self._on_slider)  # меняет громкость в реальном времени

        self.value_lbl = make_label("", "musicValue")
        self.value_lbl.setFixedWidth(36)
        self.value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        for w in (self.btn_mute, self.slider, self.value_lbl):
            lay.addWidget(w)

        music.availability_changed.connect(self._refresh_view)
        self._refresh_view()

    def _refresh_view(self):
        """Приводит значок, подсказки, подпись и доступность в соответствие с плеером."""
        m = self.music
        silent = m.muted or m.volume == 0
        icon = (QStyle.StandardPixmap.SP_MediaVolumeMuted if silent
                else QStyle.StandardPixmap.SP_MediaVolume)
        self.btn_mute.setIcon(self.style().standardIcon(icon))
        self.value_lbl.setText("—" if not m.available else ("0%" if silent else f"{m.volume}%"))

        if m.available:
            tip_btn = "Включить звук" if m.muted else "Выключить звук"
            tip_slider = "Громкость фоновой музыки"
        else:
            tip_btn = tip_slider = m.error_text
        self.btn_mute.setToolTip(tip_btn)
        self.slider.setToolTip(tip_slider)
        self.value_lbl.setToolTip(tip_slider)
        self.btn_mute.setEnabled(m.available)
        self.slider.setEnabled(m.available)

    def _on_slider(self, value: int):
        self.music.set_volume(value)
        if value > 0 and self.music.muted:  # потянули ползунок — звук включается сам
            self.music.set_muted(False)
        self._refresh_view()

    def _toggle_mute(self):
        m = self.music
        m.set_muted(not m.muted)
        if not m.muted and m.volume == 0:  # включили звук при нулевой громкости — не молчим
            with blocked(self.slider):
                self.slider.setValue(MUSIC_DEFAULT_VOLUME)
            m.set_volume(MUSIC_DEFAULT_VOLUME)
        self._refresh_view()
