"""Неблокирующее уведомление поверх окна."""

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget


# ----------------------------------------------------------------------------
# НОВОЕ: неблокирующее уведомление (toast) поверх окна
# ----------------------------------------------------------------------------
class ToastNotification(QLabel):
    """Всплывающая плашка внизу окна: плавно появляется, висит несколько секунд и гаснет.
    Не перехватывает мышь и не открывает диалогов."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "QLabel#toast { background-color: rgba(24, 28, 48, 238); color: #ffffff;"
            " border: 1px solid rgba(255, 215, 64, 170); border-radius: 14px;"
            " padding: 14px 28px; font-size: 15px; font-weight: bold; }")
        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.hide()

    def show_message(self, text: str, msec: int = 4500):
        self.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            self.move(max(0, (parent.width() - self.width()) // 2),
                      max(0, parent.height() - self.height() - 72))
        self.raise_()
        self.show()
        self._fade(1.0, hide_after=False)
        self._timer.start(msec)

    def _fade_out(self):
        self._fade(0.0, hide_after=True)

    def _fade(self, end: float, hide_after: bool):
        self._anim.stop()
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self._anim.setDuration(260)
        self._anim.setStartValue(self._fx.opacity())
        self._anim.setEndValue(end)
        if hide_after:
            self._anim.finished.connect(self.hide)
        self._anim.start()
