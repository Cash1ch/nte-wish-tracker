"""Виджеты достижений: значок, карточка, уведомление, награда."""

import math
import tempfile
import traceback
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, QRectF, QSequentialAnimationGroup, Qt,
    QTimer, QUrl,
)
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog, QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QHBoxLayout, QPlainTextEdit,
    QProgressBar, QVBoxLayout, QWidget,
)

from ..compat import QSoundEffect
from ..achievements import ACH_GOLD, ACH_TOAST_HOLD_MS
from ..fortune.sounds import _fortune_write_wav
from .theme import GLASS_SHADOWS
from .widgets import make_button, make_label


_ACH_SFX_KEEP = []



def _achievement_sound_file() -> Path:
    """Короткий победный перезвон (WAV синтезируется один раз во временной папке)."""
    folder = Path(tempfile.gettempdir()) / "nte_gacha_ach_v1"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "unlock.wav"
    if not path.exists() or path.stat().st_size < 64:
        rate = 22050
        notes = ((659.3, 0.00), (830.6, 0.10), (987.8, 0.20), (1318.5, 0.32))
        samples = []
        for i in range(int(rate * 1.1)):
            t, v = i / rate, 0.0
            for freq, start in notes:
                if t >= start:
                    dt = t - start
                    v += (math.sin(2 * math.pi * freq * dt) + 0.3 * math.sin(4 * math.pi * freq * dt)) \
                         * math.exp(-4.0 * dt) * min(1.0, dt * 200)
            samples.append(v)
        top = max((abs(v) for v in samples), default=1.0) or 1.0
        _fortune_write_wav(path, [v * 0.85 / top for v in samples], rate)
    return path



def play_achievement_sound(music) -> None:
    """Звук получения достижения; молчит, если звук приложения выключен или QtMultimedia нет."""
    if QSoundEffect is None:
        return
    if music is not None and (getattr(music, "muted", False) or getattr(music, "volume", 100) <= 0):
        return
    try:
        fx = QSoundEffect()
        fx.setSource(QUrl.fromLocalFile(str(_achievement_sound_file())))
        volume = getattr(music, "volume", 70) / 100 if music is not None else 0.7
        fx.setVolume(max(0.25, min(1.0, volume)))
        fx.play()
        _ACH_SFX_KEEP.append(fx)
        QTimer.singleShot(3000, lambda: _ACH_SFX_KEEP.remove(fx) if fx in _ACH_SFX_KEEP else None)
    except Exception:  # noqa: BLE001 — звук не должен ломать приложение
        traceback.print_exc()



def paint_achievement_badge(p: QPainter, rect: QRectF, icon: str, unlocked: bool) -> None:
    """Круглый значок достижения: золотой со свечением или приглушённый серый."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    body = rect.adjusted(5, 5, -5, -5)
    if unlocked:
        for i, alpha in enumerate((60, 32, 16)):
            glow = QColor(ACH_GOLD)
            glow.setAlpha(alpha)
            p.setPen(QPen(glow, 2 + i * 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(body)
        grad = QLinearGradient(body.topLeft(), body.bottomRight())
        grad.setColorAt(0.0, QColor("#fff0a0"))
        grad.setColorAt(1.0, QColor("#ff9f00"))
        ring, ink = QColor("#fff6c8"), QColor("#3a2600")
    else:
        grad = QLinearGradient(body.topLeft(), body.bottomRight())
        grad.setColorAt(0.0, QColor("#474b5c"))
        grad.setColorAt(1.0, QColor("#2a2d3a"))
        ring, ink = QColor("#5b6075"), QColor("#868ba0")
    p.setPen(QPen(ring, 2))
    p.setBrush(QBrush(grad))
    p.drawEllipse(body)
    font = QFont(p.font())
    font.setPixelSize(max(10, int(body.height() * 0.46)))
    font.setBold(True)
    p.setFont(font)
    p.setPen(ink)
    p.drawText(body, Qt.AlignmentFlag.AlignCenter, icon)
    p.restore()



def fmt_ach_value(value: int, unit: str = "") -> str:
    """Значение прогресса для карточки: время — «3 ч 05 мин», остальное — число."""
    if unit != "time":
        return str(value)
    hours, minutes = divmod(max(0, int(value)) // 60, 60)
    return f"{hours} ч {minutes:02d} мин" if hours else f"{minutes} мин"



class AchievementBadge(QWidget):
    def __init__(self, icon: str, unlocked: bool, size: int = 64, parent=None):
        super().__init__(parent)
        self.icon, self.unlocked = icon, unlocked
        self.setFixedSize(size, size)

    def paintEvent(self, _event):
        p = QPainter(self)
        paint_achievement_badge(p, QRectF(self.rect()), self.icon, self.unlocked)



class AchievementRewardDialog(QDialog):
    """Награда за достижение (например, рецепт)."""

    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(520, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        head = make_label(f"Награда: {title}")
        head.setStyleSheet(f"color: {ACH_GOLD}; font-size: 18px; font-weight: bold;")
        lay.addWidget(head)
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setPlainText(text)
        lay.addWidget(box, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = make_button("Закрыть", self.accept, "primary")
        close_btn.setMinimumWidth(130)
        row.addWidget(close_btn)
        lay.addLayout(row)



class AchievementCard(QFrame):
    """Карточка достижения: яркая с золотым свечением (получено) или приглушённая с прогрессом."""

    def __init__(self, ach: dict, parent=None):
        super().__init__(parent)
        unlocked = bool(ach["is_unlocked"])
        self.setObjectName("achCard")
        if unlocked:
            self.setStyleSheet(
                "QFrame#achCard { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                " stop:0 rgba(255,215,64,48), stop:1 rgba(255,140,0,26));"
                " border: 1px solid rgba(255,215,64,190); border-radius: 14px; }")
            if GLASS_SHADOWS:
                glow = QGraphicsDropShadowEffect(self)
                glow.setBlurRadius(26)
                glow.setOffset(0, 0)
                glow.setColor(QColor(255, 200, 40, 120))
                self.setGraphicsEffect(glow)
        else:
            self.setStyleSheet(
                "QFrame#achCard { background: rgba(255,255,255,8);"
                " border: 1px solid rgba(255,255,255,28); border-radius: 14px; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 12, 14, 12)
        lay.setSpacing(12)
        lay.addWidget(AchievementBadge(ach["icon"], unlocked), 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        title = make_label(ach["title"], wrap=True)
        title.setStyleSheet(f"color: {'#fff3b0' if unlocked else '#7d8296'}; font-size: 14px; font-weight: bold;")
        desc = make_label(ach["description"], wrap=True)
        desc.setStyleSheet(f"color: {'#d6d2b8' if unlocked else '#5f6478'}; font-size: 11px;")
        col.addWidget(title)
        col.addWidget(desc)
        if unlocked:
            when = ach["unlocked_at"]
            status = make_label(f"✔ Получено{': ' + when if when else ''}")
            status.setStyleSheet(f"color: {ACH_GOLD}; font-size: 11px; font-weight: bold; margin-top: 4px;")
            col.addWidget(status)
            if ach.get("reward_title"):
                btn = make_button(f"Открыть награду: {ach['reward_title']}",
                                  lambda *_: AchievementRewardDialog(
                                      ach["reward_title"], ach["reward_text"], self.window()).exec())
                btn.setAutoDefault(False)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                col.addWidget(btn)
        else:
            cur, target = ach["progress_current"], max(1, ach["progress_target"])
            bar = QProgressBar()
            bar.setRange(0, target)
            bar.setValue(min(cur, target))
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setStyleSheet(
                "QProgressBar { background: rgba(255,255,255,16); border: none; border-radius: 4px; }"
                "QProgressBar::chunk { background: #6b7090; border-radius: 4px; }")
            unit = ach.get("unit", "")
            num = make_label(f"{fmt_ach_value(cur, unit)} / {fmt_ach_value(target, unit)}")
            num.setStyleSheet("color: #7d8296; font-size: 11px; margin-top: 2px;")
            col.addWidget(bar)
            col.addWidget(num)
            if ach.get("reward_title"):
                hint = make_label(f"Награда: {ach['reward_title']}")
                hint.setStyleSheet("color: #7d8296; font-size: 11px;")
                col.addWidget(hint)
        col.addStretch(1)
        lay.addLayout(col, 1)



class AchievementToast(QWidget):
    """Плавающее уведомление «Достижение разблокировано!» поверх окна (не блокирует работу)."""
    PAD = 14

    def __init__(self, host: QWidget, ach: dict):
        super().__init__(host)
        self.ach = ach
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(404 + 2 * self.PAD, (122 if ach.get("reward_title") else 104) + 2 * self.PAD)
        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)
        self._seq = None

    def start(self):
        host = self.parentWidget()
        x = max(8, host.width() - self.width() - 10)
        y = 44
        self.move(x + 44, y)
        self.show()
        self.raise_()
        fade_in = QPropertyAnimation(self._fx, b"opacity")
        fade_in.setDuration(300)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        slide = QPropertyAnimation(self, b"pos")
        slide.setDuration(340)
        slide.setStartValue(QPoint(x + 44, y))
        slide.setEndValue(QPoint(x, y))
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        appear = QParallelAnimationGroup()
        appear.addAnimation(fade_in)
        appear.addAnimation(slide)
        fade_out = QPropertyAnimation(self._fx, b"opacity")
        fade_out.setDuration(450)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        self._seq = QSequentialAnimationGroup(self)
        self._seq.addAnimation(appear)
        self._seq.addPause(ACH_TOAST_HOLD_MS)
        self._seq.addAnimation(fade_out)
        self._seq.finished.connect(self.deleteLater)
        self._seq.start()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel = QRectF(self.rect()).adjusted(self.PAD, self.PAD, -self.PAD, -self.PAD)
        for i, alpha in enumerate((48, 28, 14, 6)):                   # золотое свечение
            glow = QColor(ACH_GOLD)
            glow.setAlpha(alpha)
            p.setPen(QPen(glow, 2 + i * 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(panel, 18, 18)
        bg = QLinearGradient(panel.topLeft(), panel.bottomRight())
        bg.setColorAt(0.0, QColor("#1b1a3a"))
        bg.setColorAt(1.0, QColor("#0c0e1f"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(panel, 16, 16)
        edge = QLinearGradient(panel.topLeft(), panel.bottomRight())
        edge.setColorAt(0.0, QColor("#fff0a0"))
        edge.setColorAt(0.5, QColor(ACH_GOLD))
        edge.setColorAt(1.0, QColor("#ff9100"))
        p.setPen(QPen(QBrush(edge), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(panel, 16, 16)

        badge = QRectF(panel.x() + 14, panel.center().y() - 38, 76, 76)
        paint_achievement_badge(p, badge, self.ach["icon"], True)
        tx = badge.right() + 14
        width = panel.right() - tx - 14
        base = QFont(self.font())

        head = QFont(base)
        head.setPixelSize(12)
        head.setBold(True)
        head.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        p.setFont(head)
        p.setPen(QColor(ACH_GOLD))
        p.drawText(QRectF(tx, panel.y() + 14, width, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Достижение разблокировано!")

        tf = QFont(base)
        tf.setPixelSize(17)
        tf.setBold(True)
        p.setFont(tf)
        p.setPen(QColor("#ffffff"))
        title = QFontMetricsF(tf).elidedText(self.ach["title"], Qt.TextElideMode.ElideRight, width)
        p.drawText(QRectF(tx, panel.y() + 34, width, 24), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   title)

        df = QFont(base)
        df.setPixelSize(12)
        p.setFont(df)
        p.setPen(QColor("#b8bdd4"))
        p.drawText(QRectF(tx, panel.y() + 60, width, 34),
                   int(Qt.AlignmentFlag.AlignLeft.value | Qt.AlignmentFlag.AlignTop.value
                       | Qt.TextFlag.TextWordWrap.value),
                   self.ach["description"])
        if self.ach.get("reward_title"):
            rf = QFont(base)
            rf.setPixelSize(12)
            rf.setBold(True)
            p.setFont(rf)
            p.setPen(QColor(ACH_GOLD))
            p.drawText(QRectF(tx, panel.bottom() - 28, width, 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"Награда: {self.ach['reward_title']}")
