"""Аватарка и окно «Профиль»."""

import traceback

from PyQt6.QtCore import pyqtSignal, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel, QMenu,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizeGrip, QTabWidget, QVBoxLayout, QWidget,
)

from ..achievements import ACH_GOLD
from ..catalog import ARC_BANNER
from ..database import Database
from ..errors import DatabaseError
from ..labels import _safe_int
from .achievement_widgets import AchievementCard
from .profile_dialog import (
    clear_profile_avatar, load_profile_avatar, PROFILE_AVATAR_FILTER, PROFILE_GOLD, PROFILE_MINT,
    PROFILE_NEON, PROFILE_PINK, profile_summary, ProfileNameDialog, save_profile_avatar,
)
from .theme import GLASS_SHADOWS
from .widgets import make_button, make_label


class ClickableProfileLabel(QLabel):
    """Подпись «Профиль: …» в шапке «Стафф»: кликабельна, подсвечивается при наведении."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("profileName")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Открыть профиль")
        self.setStyleSheet(
            "QLabel#profileName { color: #ffd740; font-size: 15px; font-weight: bold;"
            " padding: 4px 12px; border: 1px solid transparent; border-radius: 10px; }"
            "QLabel#profileName:hover { color: #fff3b0; background: rgba(255, 215, 64, 30);"
            " border: 1px solid rgba(255, 215, 64, 150); }")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)



class ProfileAvatar(QWidget):
    """Круглая аватарка с неоновым кольцом; без картинки рисует инициал. Клик — выбор файла."""
    clicked = pyqtSignal()

    def __init__(self, size: int = 140, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Нажмите, чтобы открыть меню")
        self._pm, self._cache, self._cache_px = QPixmap(), None, 0
        self._initial, self._hover = "?", False

    def set_pixmap(self, pm: QPixmap):
        self._pm, self._cache = pm, None
        self.update()

    def set_initial(self, text: str):
        self._initial = (text.strip()[:1] or "?").upper()
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def _scaled(self, side: float) -> QPixmap:
        dpr = self.devicePixelRatioF()
        px = max(1, int(side * dpr))
        if self._cache is None or self._cache_px != px:
            self._cache = self._pm.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                          Qt.TransformationMode.SmoothTransformation)
            self._cache.setDevicePixelRatio(dpr)
            self._cache_px = px
        return self._cache

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        d = min(self.width(), self.height())
        ring = QRectF((self.width() - d) / 2, (self.height() - d) / 2, d, d).adjusted(10, 10, -10, -10)
        for i, alpha in enumerate((40, 24, 12)):                     # мягкое неоновое свечение
            glow = QColor(PROFILE_NEON)
            glow.setAlpha(alpha)
            p.setPen(QPen(glow, 3 + i * 4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(ring)
        inner = ring.adjusted(5, 5, -5, -5)
        clip = QPainterPath()
        clip.addEllipse(inner)
        p.save()
        p.setClipPath(clip)
        if not self._pm.isNull():
            pm = self._scaled(inner.width())
            p.drawPixmap(QPointF(inner.x(), inner.y()), pm)
        else:
            grad = QLinearGradient(inner.topLeft(), inner.bottomRight())
            grad.setColorAt(0.0, QColor("#1c2250"))
            grad.setColorAt(1.0, QColor("#4a1a62"))
            p.fillRect(inner, QBrush(grad))
            font = QFont(self.font())
            font.setPixelSize(int(inner.height() * 0.46))
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(PROFILE_NEON))
            p.drawText(inner, Qt.AlignmentFlag.AlignCenter, self._initial)
        if self._hover:
            p.fillRect(inner, QColor(0, 0, 0, 130))
            font = QFont(self.font())
            font.setPixelSize(13)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor("#ffffff"))
            p.drawText(inner, Qt.AlignmentFlag.AlignCenter, "Изменить")
        p.restore()
        grad = QLinearGradient(ring.topLeft(), ring.bottomRight())
        grad.setColorAt(0.0, QColor(PROFILE_NEON))
        grad.setColorAt(1.0, QColor(PROFILE_PINK))
        p.setPen(QPen(QBrush(grad), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(ring.adjusted(1.5, 1.5, -1.5, -1.5))



class ProfileDialog(QDialog):
    """Окно профиля: аватарка, имя (с переименованием), карточки статистики и текущий гарант."""

    MARGIN = 14   # отступ от края окна до панели (место под свечение)

    def __init__(self, db: Database, stats: dict, history: list, parent=None,
                 ach_manager=None, on_changed=None):
        super().__init__(parent)
        self.db = db
        self.ach_manager = ach_manager
        self.on_changed = on_changed
        self.ach_grid = None
        self.pid = db.profile_id
        self.summary = profile_summary(stats, history)
        self.renamed = False
        self._fading = self._fade_done = False
        self._anim = None
        self.setObjectName("profileDialog")
        self.setWindowTitle("Профиль")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("QDialog#profileDialog { background: transparent; }")
        self.setModal(True)
        self.setMinimumSize(560, 520)
        self.resize(780, 720)

        m = self.MARGIN + 10
        root = QVBoxLayout(self)
        root.setContentsMargins(m, m - 4, m, m - 4)
        root.setSpacing(10)

        # --- шапка ---
        head = QHBoxLayout()
        title = make_label("ПРОФИЛЬ ИГРОКА")
        title.setStyleSheet(f"color: {PROFILE_NEON}; font-size: 17px; font-weight: bold; letter-spacing: 3px;")
        head.addWidget(title)
        head.addStretch(1)
        x_btn = QPushButton("✕")
        x_btn.setAutoDefault(False)
        x_btn.setFixedSize(30, 30)
        x_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        x_btn.setToolTip("Закрыть")
        x_btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,14); border: 1px solid rgba(255,255,255,50);"
            " border-radius: 15px; color: #e6e6ea; font-size: 13px; padding: 0; }"
            "QPushButton:hover { background: rgba(255,60,90,90); border-color: #ff4d6d; color: #ffffff; }")
        x_btn.clicked.connect(self.reject)
        head.addWidget(x_btn)
        root.addLayout(head)

        # --- шапка профиля и вкладки «Статистика» / «Достижения» ---
        root.addWidget(self._build_hero())
        self.tabs = QTabWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        body = QWidget()
        body.setAutoFillBackground(False)
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 8, 6, 0)
        col.setSpacing(14)
        scroll.setWidget(body)
        col.addLayout(self._build_cards())
        col.addStretch(1)
        self.tabs.addTab(scroll, "Статистика")
        self.tabs.addTab(self._build_achievements_tab(), "Достижения")
        root.addWidget(self.tabs, 1)

        # --- подвал ---
        foot = QHBoxLayout()
        foot.addStretch(1)
        close_btn = make_button("Закрыть", self.reject, "primary")
        close_btn.setMinimumWidth(140)
        close_btn.setMinimumHeight(36)
        close_btn.setDefault(True)
        foot.addWidget(close_btn)
        foot.addWidget(QSizeGrip(self), 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        root.addLayout(foot)

    # ---------- построение интерфейса ----------
    def _build_hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("profileHero")
        hero.setStyleSheet(
            "QFrame#profileHero { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            " stop:0 rgba(0,229,255,26), stop:1 rgba(255,43,214,22));"
            " border: 1px solid rgba(0,229,255,110); border-radius: 18px; }")
        lay = QHBoxLayout(hero)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(22)

        self.avatar = ProfileAvatar(144)
        self.avatar.clicked.connect(self._avatar_menu)
        self.avatar.set_pixmap(load_profile_avatar(self.db))
        lay.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignVCenter)

        info = QVBoxLayout()
        info.setSpacing(6)
        caption = make_label("Имя профиля")
        caption.setStyleSheet("color: #9aa0b4; font-size: 12px; letter-spacing: 1px;")
        info.addWidget(caption)
        self.name_lbl = make_label(self._profile_name(), wrap=True)
        self.name_lbl.setStyleSheet(f"color: {PROFILE_GOLD}; font-size: 28px; font-weight: bold;")
        self.avatar.set_initial(self._profile_name())
        info.addWidget(self.name_lbl)
        info.addStretch(1)
        lay.addLayout(info, 1)
        return hero

    @staticmethod
    def _pity_color(value: int, cap: int) -> str:
        ratio = value / cap if cap else 0
        return PROFILE_MINT if ratio < 0.5 else (PROFILE_GOLD if ratio < 0.8 else "#ff4d6d")

    def _build_banner_card(self, info: dict, accent: str) -> QFrame:
        """Карточка статистики одного пула: ивентовые / стандартные персонажи или дуги."""
        frame = QFrame()
        frame.setObjectName("statCard")
        if GLASS_SHADOWS:
            glow = QGraphicsDropShadowEffect(frame)
            glow.setBlurRadius(30)
            glow.setOffset(0, 0)
            color = QColor(accent)
            color.setAlpha(95)
            glow.setColor(color)
            frame.setGraphicsEffect(glow)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)
        title = make_label(info["title"])
        title.setStyleSheet(f"color: {accent}; font-size: 16px; font-weight: bold;")
        lay.addWidget(title)

        def line(name: str, value: str):
            row = QHBoxLayout()
            lbl = make_label(name)
            lbl.setStyleSheet("color: #9aa0b4;")
            val = make_label(value)
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            val.setStyleSheet(f"color: {accent}; font-weight: bold;")
            row.addWidget(lbl)
            row.addStretch(1)
            row.addWidget(val)
            lay.addLayout(row)

        best = info["best"]
        line("Всего круток", str(info["total"]))
        line("Получено S-ранга", str(info["s"]))
        if info["key"] == ARC_BANNER:
            line("Ивентовых / стандартных S", f"{info['ev']} / {info['st']}")
        line("Средний гарант", info["avg"])
        line("Лучший гарант", f"{_safe_int(best['p5'])} кр. · {best.get('name') or '—'}" if best else "—")

        sub = make_label("Текущий гарант")
        sub.setStyleSheet("color: #9aa0b4; margin-top: 6px;")
        lay.addWidget(sub)
        for name, value, cap in info["pity"]:
            row = QHBoxLayout()
            row.setSpacing(12)
            lbl = make_label(name)
            lbl.setMinimumWidth(130)
            row.addWidget(lbl)
            bar = QProgressBar()
            bar.setRange(0, max(1, cap))
            bar.setValue(min(value, cap))
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            bar.setStyleSheet(
                "QProgressBar { background: rgba(255,255,255,20); border: none; border-radius: 5px; }"
                f"QProgressBar::chunk {{ background: {self._pity_color(value, cap)}; border-radius: 5px; }}")
            row.addWidget(bar, 1)
            num = make_label(f"{value} / {cap}")
            num.setMinimumWidth(64)
            num.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            num.setStyleSheet(f"color: {self._pity_color(value, cap)}; font-weight: bold;")
            row.addWidget(num)
            lay.addLayout(row)
        return frame

    def _build_cards(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(14)
        for info, accent in zip(self.summary, (PROFILE_NEON, PROFILE_PINK, PROFILE_GOLD)):
            col.addWidget(self._build_banner_card(info, accent))
        return col

    def _build_achievements_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 10, 0, 0)
        lay.setSpacing(8)
        self.ach_summary = make_label("")
        self.ach_summary.setStyleSheet(f"color: {ACH_GOLD}; font-size: 15px; font-weight: bold;")
        lay.addWidget(self.ach_summary)
        self.ach_bar = QProgressBar()
        self.ach_bar.setTextVisible(False)
        self.ach_bar.setFixedHeight(12)
        self.ach_bar.setStyleSheet(
            "QProgressBar { background: rgba(255,255,255,20); border: none; border-radius: 6px; }"
            "QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            " stop:0 #ffd740, stop:1 #ff9100); border-radius: 6px; }")
        lay.addWidget(self.ach_bar)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        host = QWidget()
        host.setAutoFillBackground(False)
        self.ach_grid = QGridLayout(host)
        self.ach_grid.setContentsMargins(0, 6, 6, 0)
        self.ach_grid.setHorizontalSpacing(12)
        self.ach_grid.setVerticalSpacing(12)
        self.ach_grid.setColumnStretch(0, 1)
        self.ach_grid.setColumnStretch(1, 1)
        scroll.setWidget(host)
        lay.addWidget(scroll, 1)
        self._reload_achievements()
        return page

    def _reload_achievements(self):
        items = self.ach_manager.all() if self.ach_manager is not None else []
        while self.ach_grid.count():
            item = self.ach_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
                item.widget().deleteLater()
        done = sum(1 for a in items if a["is_unlocked"])
        self.ach_summary.setText(f"Получено: {done} / {len(items)}")
        self.ach_bar.setRange(0, max(1, len(items)))
        self.ach_bar.setValue(done)
        for i, ach in enumerate(items):
            self.ach_grid.addWidget(AchievementCard(ach), i // 2, i % 2, Qt.AlignmentFlag.AlignTop)
        self.ach_grid.setRowStretch(len(items) // 2 + 1, 1)

    def _profile_changed(self):
        """Профиль изменён (аватарка, имя): перепроверить достижения и обновить галерею."""
        if self.on_changed is not None:
            try:
                self.on_changed()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        if self.ach_grid is not None:
            self._reload_achievements()

    # ---------- действия ----------
    def _profile_name(self) -> str:
        prof = self.db.active_profile()
        return prof["name"] if prof else ""

    def _avatar_menu(self, *_):
        """Контекстное меню по клику на аватарку."""
        menu = QMenu(self)
        act_upload = menu.addAction("Загрузить аватар")
        act_rename = menu.addAction("Изменить имя")
        chosen = menu.exec(self.avatar.mapToGlobal(QPoint(0, self.avatar.height())))
        if chosen is act_upload:
            self._upload_avatar()
        elif chosen is act_rename:
            self._rename()

    def _upload_avatar(self, *_):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите изображение", "", PROFILE_AVATAR_FILTER)
        if not path:
            return
        try:
            self.avatar.set_pixmap(save_profile_avatar(self.db, path))
            self._profile_changed()
        except DatabaseError as e:
            QMessageBox.warning(self, "Профиль", str(e))

    def _remove_avatar(self, *_):
        clear_profile_avatar(self.db)
        self.avatar.set_pixmap(QPixmap())
        self._profile_changed()

    def _rename(self, *_):
        dlg = ProfileNameDialog(self.db, self, "Переименование профиля", "Новый никнейм",
                                text=self._profile_name(), ok_text="Сохранить", exclude_id=self.pid)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            clean = self.db.rename_profile(self.pid, dlg.name)
        except DatabaseError as e:
            QMessageBox.warning(self, "Профиль", str(e))
            return
        self.renamed = True
        self.name_lbl.setText(clean)
        self.avatar.set_initial(clean)
        self._profile_changed()

    # ---------- отрисовка панели, перетаскивание, плавное открытие/закрытие ----------
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel = QRectF(self.rect()).adjusted(self.MARGIN, self.MARGIN, -self.MARGIN, -self.MARGIN)
        for i, alpha in enumerate((34, 20, 10, 5)):                  # неоновое свечение вокруг панели
            glow = QColor(PROFILE_NEON)
            glow.setAlpha(alpha)
            p.setPen(QPen(glow, 2 + i * 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(panel, 22, 22)
        grad = QLinearGradient(panel.topLeft(), panel.bottomRight())
        grad.setColorAt(0.0, QColor("#141838"))
        grad.setColorAt(0.55, QColor("#0e1124"))
        grad.setColorAt(1.0, QColor("#1b0f2e"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(panel, 20, 20)
        edge = QLinearGradient(panel.topLeft(), panel.bottomRight())
        edge.setColorAt(0.0, QColor(PROFILE_NEON))
        edge.setColorAt(1.0, QColor(PROFILE_PINK))
        p.setPen(QPen(QBrush(edge), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(panel, 20, 20)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < self.MARGIN + 56:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(event)

    def _animate(self, start: float, end: float, ms: int, on_done=None):
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(ms)
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if on_done:
            self._anim.finished.connect(on_done)
        self._anim.start()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fading:
            self.setWindowOpacity(0.0)
            self._animate(0.0, 1.0, 180)

    def done(self, result):
        """Закрытие (кнопка «Закрыть», ✕, Esc) — через плавное затухание."""
        if self._fade_done:
            QDialog.done(self, result)
            return
        if self._fading:
            return
        self._fading = True

        def finish():
            self._fade_done = True
            QDialog.done(self, result)

        self._animate(self.windowOpacity(), 0.0, 140, finish)
