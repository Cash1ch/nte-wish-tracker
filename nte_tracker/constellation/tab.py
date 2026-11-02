"""Вкладка «Созвездие»."""

import re
import traceback
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QCursor, QImage, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QMenu, QMessageBox, QSizePolicy, QSlider,
    QVBoxLayout, QWidget,
)

from ..catalog import FIXED_RARITY, ROSTER_EVENT_S, ROSTER_STANDARD_S
from ..icons import find_icon_path, make_pixmap
from ..ui.widgets import make_button, make_label
from .geometry import (
    CONSTELLATION_BG_BLUR_KEY, CONSTELLATION_CENTER, CONSTELLATION_DEFAULT_CHAR, CONSTELLATION_EDGES,
    CONSTELLATION_NO_GLOW_KEY, CONSTELLATION_NODES, CONSTELLATION_RINGS,
)
from .items import ConstellationHub, ConstellationLink, ConstellationNode, ConstellationView


class ConstellationTab(QWidget):
    """Вкладка «Созвездие»: выбор персонажа и сеть узлов; по клику на деталь можно загрузить свою иконку."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.nodes = []
        self._char = CONSTELLATION_DEFAULT_CHAR

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(make_label("Персонаж:"))
        self.char_combo = QComboBox()
        names = list(dict.fromkeys(ROSTER_EVENT_S + ROSTER_STANDARD_S))
        if CONSTELLATION_DEFAULT_CHAR not in names:
            names.insert(0, CONSTELLATION_DEFAULT_CHAR)
        for n in names:
            self.char_combo.addItem(n, n)
        self.char_combo.setCurrentIndex(max(0, self.char_combo.findData(self._char)))
        self.char_combo.currentIndexChanged.connect(self._on_char_changed)
        top.addWidget(self.char_combo)
        top.addStretch(1)
        self.glow_check = QCheckBox("Отключить свечение")
        self.glow_check.setToolTip("Убрать ореолы вокруг иконок (действует и на скриншот)")
        ConstellationNode.no_glow = self.win.db.get_setting(CONSTELLATION_NO_GLOW_KEY, "0", scoped=True) == "1"
        self.glow_check.setChecked(ConstellationNode.no_glow)
        self.glow_check.toggled.connect(self._on_glow_toggled)
        top.addWidget(self.glow_check)
        top.addWidget(make_button("Скриншот HD…", self._save_screenshot))
        top.addWidget(make_button("Загрузить фон…", self._choose_background))
        top.addWidget(make_button("Убрать фон", self._clear_background))
        lay.addLayout(top)

        blur_row = QHBoxLayout()
        blur_row.addWidget(make_label("Размытие фона:"))
        self.blur_slider = QSlider(Qt.Orientation.Horizontal)
        self.blur_slider.setRange(0, 100)
        self.blur_slider.setToolTip("0 — оригинальное качество, правее — сильнее размытие")
        self.blur_value = make_label("0")
        self.blur_value.setMinimumWidth(32)
        blur_row.addWidget(self.blur_slider, 1)
        blur_row.addWidget(self.blur_value)
        lay.addLayout(blur_row)
        self._blur_save = QTimer(self)
        self._blur_save.setSingleShot(True)
        self._blur_save.setInterval(400)
        self._blur_save.timeout.connect(
            lambda: self.win.db.set_setting(CONSTELLATION_BG_BLUR_KEY, str(self.blur_slider.value()), scoped=True))

        self.view = ConstellationView()
        self.view.setMinimumSize(320, 320)
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay.addWidget(self.view, 1)
        self.view.set_background(self._load_stored(self._background_key()))
        try:
            saved_blur = int(self.win.db.get_setting(CONSTELLATION_BG_BLUR_KEY, "0", scoped=True) or 0)
        except (TypeError, ValueError):
            saved_blur = 0
        self.blur_slider.setValue(max(0, min(100, saved_blur)))
        self.blur_value.setText(str(self.blur_slider.value()))
        self.view.set_bg_blur(self.blur_slider.value())
        self.blur_slider.valueChanged.connect(self._on_blur_changed)
        self.rebuild()

    # ---------- свои иконки ----------
    def _assets_dir(self) -> Path:
        d = self.win.db.path.parent / "assets" / "constellation"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _safe(text: str) -> str:
        return re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_") or "x"

    def _pick_image(self, title: str):
        """Диалог выбора картинки; возвращает QPixmap или None."""
        path, _ = QFileDialog.getOpenFileName(self, title, "",
                                              "Изображения (*.png *.jpg *.jpeg *.webp *.bmp);;Все файлы (*)")
        if not path:
            return None
        pm = QPixmap(path)
        if pm.isNull():
            QMessageBox.warning(self, "Ошибка", "Не удалось открыть изображение.")
            return None
        return pm

    def _store_image(self, setting_key: str, file_stem: str, pm: QPixmap) -> bool:
        """Сохраняет копию картинки рядом с базой (assets/constellation) и запоминает имя файла в настройках."""
        name = f"{self._safe(file_stem)}.png"
        try:
            ok = pm.save(str(self._assets_dir() / name), "PNG")
        except OSError:
            ok = False
        if not ok:
            QMessageBox.warning(self, "Ошибка", "Не удалось сохранить изображение.")
            return False
        self.win.db.set_setting(setting_key, name, scoped=True)
        return True

    def _load_stored(self, setting_key: str):
        name = self.win.db.get_setting(setting_key, "", scoped=True) or ""
        if not name:
            return None
        path = self._assets_dir() / name
        pm = QPixmap(str(path)) if path.exists() else QPixmap()
        return pm if not pm.isNull() else None

    def _forget(self, setting_key: str):
        name = self.win.db.get_setting(setting_key, "", scoped=True) or ""
        self.win.db.set_setting(setting_key, "", scoped=True)
        if name:
            try:
                (self._assets_dir() / name).unlink()
            except OSError:
                pass

    def _node_key(self, node) -> str:
        return f"constellation_icon:{self._char}:{node.node_id}"

    def _portrait_key(self) -> str:
        return f"constellation_portrait:{self._char}"

    def _background_key(self) -> str:
        return "constellation_background"

    def _choose_background(self):
        pm = self._pick_image("Загрузить задний фон")
        if pm is None:
            return
        if max(pm.width(), pm.height()) > 1920:        # слишком большие картинки уменьшаем
            pm = pm.scaled(1920, 1920, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        if self._store_image(self._background_key(), "constellation_background", pm):
            self.view.set_background(pm)

    def _on_blur_changed(self, value: int):
        self.blur_value.setText(str(value))
        self.view.set_bg_blur(value)
        self._blur_save.start()

    def _on_glow_toggled(self, checked: bool):
        ConstellationNode.no_glow = checked
        self.win.db.set_setting(CONSTELLATION_NO_GLOW_KEY, "1" if checked else "0", scoped=True)
        self.view.scene().update()
        self.view.viewport().update()

    def _save_screenshot(self):
        """Сохраняет видимую область созвездия в высоком качестве (4K, PNG / JPEG / WEBP)."""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default = str(Path.home() / f"созвездие_{self._safe(self._char)}_{stamp}.png")
        path, chosen = QFileDialog.getSaveFileName(
            self, "Сохранить скриншот", default,
            "PNG (*.png);;JPEG (*.jpg *.jpeg);;WEBP (*.webp)")
        if not path:
            return
        suffix = Path(path).suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
            suffix = ".jpg" if "JPEG" in chosen else (".webp" if "WEBP" in chosen else ".png")
            path += suffix
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            img = self.view.render_hd(3840)
            if suffix in (".jpg", ".jpeg"):
                img = img.convertToFormat(QImage.Format.Format_RGB32)
            fmt = {".png": "PNG", ".jpg": "JPG", ".jpeg": "JPG", ".webp": "WEBP"}[suffix]
            ok = img.save(path, fmt, 100)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            ok = False
        finally:
            QApplication.restoreOverrideCursor()
        if ok:
            QMessageBox.information(self, "Скриншот", f"Скриншот сохранён:\n{path}\nРазмер: {img.width()}×{img.height()}")
        else:
            QMessageBox.warning(self, "Ошибка", "Не удалось сохранить скриншот.")

    def _clear_background(self):
        self._forget(self._background_key())
        self.view.set_background(None)

    def _change_node_icon(self, node):
        pm = self._pick_image(f"Иконка: {node.label}")
        if pm is None:
            return
        side = 512                                 # квадрат по центру (без растягивания), с запасом резкости
        pm = pm.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation)
        pm = pm.copy((pm.width() - side) // 2, (pm.height() - side) // 2, side, side)
        if self._store_image(self._node_key(node), f"{self._char}_{node.node_id}", pm):
            node.set_icon(pm)

    def _reset_node_icon(self, node):
        self._forget(self._node_key(node))
        node.set_icon(self._node_icon(node))

    def _change_portrait(self):
        pm = self._pick_image(f"Портрет: {self._char}")
        if pm is None:
            return
        if pm.width() > 1000:
            pm = pm.scaledToWidth(1000, Qt.TransformationMode.SmoothTransformation)
        if self._store_image(self._portrait_key(), f"{self._char}_portrait", pm):
            self.hub.set_pixmap(pm)

    def _reset_portrait(self):
        self._forget(self._portrait_key())
        self.hub.set_pixmap(self._default_portrait())

    def _node_icon(self, node: ConstellationNode):
        custom = self._load_stored(self._node_key(node))
        if custom is not None:
            return custom
        if find_icon_path(node.label) is None:
            return None                                # нет файла — рисуется символ-заглушка
        size = int(node.radius * 2)
        return make_pixmap(node.label, FIXED_RARITY.get(node.kind or "", 4), size, thin=True)

    def _hub_pixmap(self) -> QPixmap:
        custom = self._load_stored(self._portrait_key())
        return custom if custom is not None else self._default_portrait()

    def _default_portrait(self) -> QPixmap:
        path = find_icon_path(self._char)
        if path:
            pm = QPixmap(str(path))
            if not pm.isNull():
                return pm
        return QPixmap()

    # ---------- построение сцены ----------
    def _on_char_changed(self, *_):
        self._char = self.char_combo.currentData() or CONSTELLATION_DEFAULT_CHAR
        self.rebuild()

    def rebuild(self):
        """Пересобирает сцену для выбранного персонажа (масштаб и положение сохраняются)."""
        scene = self.view.scene()
        scene.clear()
        self.nodes = []
        cx, cy = CONSTELLATION_CENTER

        for radius in CONSTELLATION_RINGS:             # концентрические кольца
            path = QPainterPath()
            path.addEllipse(QPointF(cx, cy), radius, radius)
            ring = ConstellationLink(path, "#d83fd0", 0.7)
            ring.setZValue(0)
            scene.addItem(ring)

        counters = {}
        for type_key, x, y, tag in CONSTELLATION_NODES:
            counters[type_key] = counters.get(type_key, 0) + 1
            node = ConstellationNode(f"{type_key}-{counters[type_key]}", type_key, x, y)
            node.tag = tag
            node.set_icon(self._node_icon(node))
            node.clicked.connect(self._on_node_clicked)
            self.nodes.append(node)

        by_tag = {n.tag: n for n in self.nodes}        # линии строго по схеме CONSTELLATION_EDGES
        for tag_a, tag_b in CONSTELLATION_EDGES:
            a, b = by_tag[tag_a], by_tag[tag_b]
            path = QPainterPath(a.pos())
            path.lineTo(b.pos())
            link = ConstellationLink(path, "#ff4fd8", 0.8)
            link.setZValue(2)
            scene.addItem(link)

        for n in self.nodes:
            scene.addItem(n)
        self.hub = ConstellationHub(self._char, self._hub_pixmap())
        self.hub.clicked.connect(self._on_hub_clicked)
        scene.addItem(self.hub)
        if self.view._auto_fit:
            self.view.fit_all()

    # ---------- клики ----------
    def _on_node_clicked(self, node: ConstellationNode):
        menu = QMenu(self)
        load = menu.addAction("Загрузить иконку…")
        reset = None
        if self.win.db.get_setting(self._node_key(node), "", scoped=True):
            reset = menu.addAction("Убрать свою иконку")
        chosen = menu.exec(QCursor.pos())
        if chosen is load:
            self._change_node_icon(node)
        elif chosen is reset and reset is not None:
            self._reset_node_icon(node)

    def _on_hub_clicked(self):
        menu = QMenu(self)
        load = menu.addAction("Загрузить портрет…")
        reset = None
        if self.win.db.get_setting(self._portrait_key(), "", scoped=True):
            reset = menu.addAction("Убрать свой портрет")
        chosen = menu.exec(QCursor.pos())
        if chosen is load:
            self._change_portrait()
        elif chosen is reset and reset is not None:
            self._reset_portrait()
