"""Вкладка «Стафф»: построение, обновление и кнопка «Поделиться»."""

import tempfile
import traceback
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from ..catalog import POOL_TITLES
from ..fortune.wheel import PulsingGlow
from ..paths import resolve_db_path
from ..share.data import collect_share_data
from ..share.renderer import SHARE_CANVAS_SIZE, SHARE_DIR_NAME, SHARE_TOAST_TEXT, ShareCardRenderer
from ..ui.falling_background import FallingBackground
from ..ui.pool_page import PoolPage
from ..ui.profile_avatar import ClickableProfileLabel
from ..ui.widgets import make_button, make_label


class StaffMixin:
    """Вкладка «Стафф»: построение, обновление и кнопка «Поделиться»."""

    # ---------- вкладка «Стафф» (три независимых пула) ----------
    def _build_staff(self) -> QWidget:
        w = QWidget()
        # НОВОЕ: «Поделиться» — запоминаем контейнер вкладки, именно его снимаем grab()
        self.staff_tab = w
        lay = QVBoxLayout(w)

        # НОВОЕ: верхняя панель вкладки с кнопкой «Поделиться» (справа)
        share_row = QHBoxLayout()
        # НОВОЕ: «Испытай судьбу» — открывает «Колесо Фортуны»; кнопка плавно «дышит» свечением
        self.fate_btn = QPushButton("Испытай судьбу")
        self.fate_btn.setObjectName("fateBtn")
        self.fate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fate_btn.setMinimumHeight(40)
        self.fate_btn.setToolTip("Не можешь решиться? Пусть решит Госпожа Фортуна")
        self.fate_btn.setStyleSheet(
            "QPushButton#fateBtn { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #5a3a9a, stop:1 #34205f);"
            " color: #ffe9a8; border: 2px solid #d9b45a; border-radius: 12px; padding: 6px 24px;"
            " font-family: Georgia, 'Palatino Linotype', serif; font-size: 16px; font-weight: bold; }"
            "QPushButton#fateBtn:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #6c47b8, stop:1 #402874);"
            " border-color: #ffe27a; }"
            "QPushButton#fateBtn:pressed { background: #2a1850; }")
        self.fate_btn.clicked.connect(self.open_fortune_wheel)
        self.fate_glow = PulsingGlow(self.fate_btn, "#ffd166", self)
        policy_fate = self.fate_btn.sizePolicy()
        policy_fate.setRetainSizeWhenHidden(True)
        self.fate_btn.setSizePolicy(policy_fate)
        share_row.addWidget(self.fate_btn)
        share_row.addStretch(1)
        self.share_save_btn = make_button("Сохранить как…", self.share_staff_save_as)
        self.share_save_btn.setToolTip("Собрать карточку статистики и сохранить её в PNG-файл")
        share_row.addWidget(self.share_save_btn)
        self.share_btn = make_button("Поделиться", self.share_staff_screenshot)
        self.share_btn.setToolTip("Собрать карточку статистики в высоком разрешении (4K) и "
                                  "скопировать в буфер обмена (Shift+клик — ещё и «Сохранить как…»)")
        share_row.addWidget(self.share_btn)
        lay.addLayout(share_row)

        self.legacy_note = make_label(name="hint", wrap=True)
        lay.addWidget(self.legacy_note)

        # НОВОЕ: никнейм активного профиля — прямо над строкой подвкладок пулов
        self.profile_label = ClickableProfileLabel()
        self.profile_label.clicked.connect(self.open_profile_dialog)
        lay.addWidget(self.profile_label, 0, Qt.AlignmentFlag.AlignLeft)
        self._update_profile_label()

        self.pool_tabs = QTabWidget()
        self.pools = {key: PoolPage(key) for key in POOL_TITLES}
        for key, page in self.pools.items():
            self.pool_tabs.addTab(page, POOL_TITLES[key])
        lay.addWidget(self.pool_tabs, 1)
        # НОВОЕ: фоновая анимация — слой ниже строки подвкладок и под всеми карточками
        self.staff_anim = FallingBackground(self.pool_tabs, self._anim_enabled, self._anim_effect)
        return w

    def _update_profile_label(self):
        prof = self.db.active_profile() if self.db.profile_id else None
        self.profile_label.setText(f"Профиль: {prof['name']}" if prof else "")

    def _refresh_staff(self):
        self._update_profile_label()
        legacy = sum(1 for r in self.rewards if not r.get("banner"))
        self.legacy_note.setText(
            f"Старых предметов без баннера: {legacy}. Они видны в истории, но не входят в сводки "
            f"пулов — удалите их и добавьте заново с выбором баннера." if legacy else "")
        self.legacy_note.setVisible(bool(legacy))
        for key, page in self.pools.items():
            page.update_data(self.stats[key], self.history)

    # ---------- НОВОЕ: «Поделиться» — внутренний рендерер карточки статистики ----------
    def share_staff_screenshot(self, *_):
        """Рисует карточку ShareCardRenderer в памяти (без снимка экрана и окна), кладёт её
        в буфер обмена, сохраняет PNG-копию и показывает toast-уведомление. Shift+клик —
        дополнительно диалог «Сохранить как…»."""
        shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        self._share_render_and_export(ask_path=shift)

    def share_staff_save_as(self, *_):
        """Та же карточка, но с обязательным диалогом «Сохранить как…»."""
        self._share_render_and_export(ask_path=True)

    def _share_render_and_export(self, ask_path: bool):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            page = self.pool_tabs.currentWidget()          # снимаем ТЕКУЩУЮ открытую страницу
            data = collect_share_data(self, getattr(page, "key", None))
            image = ShareCardRenderer(data, SHARE_CANVAS_SIZE).render()   # QImage ARGB32
        except Exception:
            traceback.print_exc()
            image = None
        finally:
            QApplication.restoreOverrideCursor()
        if image is None or image.isNull():
            self.warn("Не удалось сделать скриншот вкладки «Стафф».")
            return

        QApplication.clipboard().setPixmap(QPixmap.fromImage(image))

        saved = self._share_save_png(image, ask_path)
        if saved:
            self.statusBar().showMessage(f"PNG-копия сохранена: {saved}", 6000)
        self._show_toast(SHARE_TOAST_TEXT)

    def _share_save_png(self, image: QImage, ask_path: bool):
        """Сохраняет PNG без потерь. ask_path=False — тихо в папку screenshots рядом с базой
        данных; True — через QFileDialog. Возвращает путь или None (отмена / ошибка)."""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"NTE_Stats_{stamp}.png"
        try:
            folder = resolve_db_path().parent / SHARE_DIR_NAME
            default = folder / name
        except Exception:
            folder, default = None, Path(tempfile.gettempdir()) / name
        if ask_path:
            start = str(default if folder is not None else name)
            path, _flt = QFileDialog.getSaveFileName(
                self, "Сохранить скриншот", start, "Изображение PNG (*.png)")
            if not path:
                return None
            if not path.lower().endswith(".png"):
                path += ".png"
        else:
            path = str(default)
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            if not image.save(path, "PNG"):
                raise OSError("QImage.save вернул False")
        except Exception:
            traceback.print_exc()
            if ask_path:
                self.warn("Не удалось сохранить PNG-файл скриншота.")
            return None
        return path
