"""Вкладка «Созвездие»: графические элементы (связи, хаб, узлы, сцена)."""

import math

from PyQt6.QtCore import pyqtSignal, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient,
    QTransform,
)
from PyQt6.QtWidgets import (
    QFrame, QGraphicsBlurEffect, QGraphicsObject, QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsScene,
    QGraphicsView,
)

from .geometry import (
    CONSTELLATION_CENTER, CONSTELLATION_R_OUT, CONSTELLATION_SCENE, CONSTELLATION_TYPES,
    CONSTELLATION_ZOOM_MAX, CONSTELLATION_ZOOM_MIN,
)


class ConstellationLink(QGraphicsPathItem):
    """Светящаяся линия сети: несколько прозрачных слоёв разной толщины + тонкая яркая жила."""

    def __init__(self, path: QPainterPath, color: str, scale: float = 1.0, parent=None):
        super().__init__(path, parent)
        self._color = QColor(color)
        self._scale = scale
        self._lit = True
        self.setPen(QPen(self._color, 16))       # нужен только для расчёта границ (свечение)
        self.setZValue(1)

    def set_lit(self, lit: bool):
        if lit != self._lit:
            self._lit = lit
            self.update()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        k = 1.0 if self._lit else 0.45
        for width, alpha in ((14.0, 22), (8.0, 48), (4.0, 90)):
            c = QColor(self._color)
            c.setAlpha(int(alpha * k))
            pen = QPen(c, width * self._scale)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawPath(self.path())
        core = QColor(255, 205, 255, 235 if self._lit else 150)
        painter.setPen(QPen(core, (1.6 if self._lit else 1.1) * self._scale))
        painter.drawPath(self.path())



class ConstellationHub(QGraphicsObject):
    """Центральная карточка: портрет, обрезанный линиями звезды (внутренний пятиугольник большой
    пентаграммы), с неоновой кромкой и белой плашкой имени."""
    PLATE = QRectF(-122.0, 62.0, 244.0, 54.0)
    clicked = pyqtSignal()

    def __init__(self, name: str, pixmap: QPixmap, color: str = "#ff4fd8"):
        super().__init__()
        self._name, self._pm, self._color = name, pixmap, QColor(color)
        self._press = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setPos(CONSTELLATION_CENTER[0], CONSTELLATION_CENTER[1])
        self.setZValue(5)                       # выше линий, но ниже узлов (ключевой предмет остаётся виден)
        self.setAcceptHoverEvents(True)
        # внутренний пятиугольник: вершины в точках пересечения линий большой пентаграммы
        inner = CONSTELLATION_R_OUT * math.cos(math.radians(72)) / math.cos(math.radians(36))
        self._shape = QPainterPath()
        for i in range(5):
            a = math.radians(-90 + 72 * i)
            pt = QPointF(inner * math.cos(a), inner * math.sin(a))
            if i == 0:
                self._shape.moveTo(pt)
            else:
                self._shape.lineTo(pt)
        self._shape.closeSubpath()

    def set_pixmap(self, pixmap):
        self._pm = pixmap
        self.update()

    def mousePressEvent(self, event):
        self._press = event.scenePos() if event.button() == Qt.MouseButton.LeftButton else None
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._press is not None and event.button() == Qt.MouseButton.LeftButton:
            moved = (event.scenePos() - self._press).manhattanLength()
            self._press = None
            if moved < 6:
                self.clicked.emit()
        event.accept()

    def shape(self) -> QPainterPath:
        return self._shape

    def boundingRect(self) -> QRectF:
        return self._shape.boundingRect().adjusted(-30, -30, 30, 30).united(self.PLATE.adjusted(-12, -12, 12, 12))

    def paint(self, painter, option, widget=None):
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                               | QPainter.RenderHint.TextAntialiasing)
        box = self._shape.boundingRect()
        painter.save()
        painter.setClipPath(self._shape)
        painter.fillRect(box, QColor(12, 10, 20))
        if self._pm is not None and not self._pm.isNull():
            scaled = self._pm.scaled(box.size().toSize(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation)
            dpr = max(scaled.devicePixelRatio(), 1.0)
            w, h = scaled.width() / dpr, scaled.height() / dpr
            painter.drawPixmap(QRectF(box.center().x() - w / 2, box.top(), w, h).toRect(), scaled)
        else:
            painter.setPen(QColor(255, 255, 255, 120))
            font = QFont(); font.setPointSizeF(60); font.setBold(True)
            painter.setFont(font)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self._name[:1].upper())
        painter.restore()
        # неоновая кромка по линиям звезды
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for width, alpha in ((14.0, 22), (8.0, 48), (4.0, 90)):
            c = QColor(self._color)
            c.setAlpha(alpha)
            pen = QPen(c, width)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            painter.setPen(pen)
            painter.drawPath(self._shape)
        painter.setPen(QPen(QColor(255, 205, 255, 235), 1.8))
        painter.drawPath(self._shape)
        # белая плашка с именем
        painter.save()
        painter.translate(self.PLATE.center())
        painter.rotate(-2.0)
        plate = QRectF(-self.PLATE.width() / 2, -self.PLATE.height() / 2, self.PLATE.width(), self.PLATE.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 120))
        painter.drawRect(plate.translated(4, 5))
        painter.setBrush(QColor(244, 244, 248))
        painter.drawRect(plate)
        font = QFont(); font.setBold(True); font.setItalic(True); font.setPointSizeF(19)
        text = self._name.upper()
        while QFontMetricsF(font).horizontalAdvance(text) > plate.width() - 22 and font.pointSizeF() > 8:
            font.setPointSizeF(font.pointSizeF() - 1)
        painter.setFont(font)
        painter.setPen(QColor(12, 12, 16))
        painter.drawText(plate, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()



class ConstellationNode(QGraphicsObject):
    """Круглый узел сети: иконка предмета, тонкая светящаяся рамка, отметка «получено»."""
    clicked = pyqtSignal(object)
    _icon_cache = None
    _icon_cache_px = 0
    no_glow = False        # общий переключатель «Отключить свечение»: ореолы вокруг иконок не рисуются

    def __init__(self, node_id: str, type_key: str, x: float, y: float):
        super().__init__()
        self.node_id, self.type_key = node_id, type_key
        self.label, self.kind, color, self.radius, self.glyph, self.desc = CONSTELLATION_TYPES[type_key]
        self.color = QColor(color)
        self.lit = True
        self._icon = None
        self._hover = 0.0
        self._press = None
        self.setPos(x, y)
        self.setZValue(10)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.valueChanged.connect(self._on_anim)

    def _on_anim(self, value):
        self._hover = float(value)
        self.update()

    def set_icon(self, pm):
        self._icon = pm if pm is not None and not pm.isNull() else None
        self._icon_cache, self._icon_cache_px = None, 0
        self.update()

    def _icon_for_paint(self, side: float, scale: float):
        """Иконка, заранее приведённая к реальному размеру на экране (качественное уменьшение без «лесенки»).
        Заполняет круг целиком без растягивания: лишнее по длинной стороне обрезается по центру."""
        px = max(1, int(round(side * max(scale, 0.01))))
        if self._icon_cache is None or self._icon_cache_px != px:
            self._icon_cache = self._icon.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                 Qt.TransformationMode.SmoothTransformation)
            self._icon_cache_px = px
        return self._icon_cache, px

    def boundingRect(self) -> QRectF:
        r = self.radius + 22.0
        return QRectF(-r, -r, 2 * r, 2 * r)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addEllipse(QPointF(0, 0), self.radius + 2, self.radius + 2)
        return path

    def hoverEnterEvent(self, event):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0)
        self._anim.start()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        self._press = event.scenePos() if event.button() == Qt.MouseButton.LeftButton else None
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._press is not None and event.button() == Qt.MouseButton.LeftButton:
            moved = (event.scenePos() - self._press).manhattanLength()
            self._press = None
            if moved < 6:
                self.clicked.emit(self)
        event.accept()

    def paint(self, painter, option, widget=None):
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                               | QPainter.RenderHint.TextAntialiasing)
        r = self.radius
        strength = (1.0 if self.lit else 0.45) + 0.55 * self._hover
        painter.setPen(Qt.PenStyle.NoPen)
        if not ConstellationNode.no_glow:             # «Отключить свечение» убирает ореол вокруг иконки
            glow = QRadialGradient(QPointF(0, 0), r + 20)
            gc = QColor(self.color)
            gc.setAlpha(int(min(255, 120 * strength)))
            glow.setColorAt(0.55, gc)
            gc2 = QColor(self.color)
            gc2.setAlpha(0)
            glow.setColorAt(1.0, gc2)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(QPointF(0, 0), r + 20, r + 20)
        painter.setBrush(QColor(14, 8, 22, 235))
        painter.drawEllipse(QPointF(0, 0), r, r)
        inner = r - 5
        clip = QPainterPath()
        clip.addEllipse(QPointF(0, 0), inner, inner)
        painter.save()
        painter.setClipPath(clip)
        painter.setOpacity(1.0 if self.lit else 0.55)
        if self._icon is not None:
            scaled, px = self._icon_for_paint(2 * inner, painter.worldTransform().m11())
            src_rect = QRectF((scaled.width() - px) / 2.0, (scaled.height() - px) / 2.0, float(px), float(px))
            painter.drawPixmap(QRectF(-inner, -inner, 2 * inner, 2 * inner), scaled, src_rect)
        else:
            font = QFont(); font.setPointSizeF(max(10.0, r * 0.62))
            painter.setFont(font)
            painter.setPen(self.color)
            painter.drawText(QRectF(-inner, -inner, 2 * inner, 2 * inner),
                             Qt.AlignmentFlag.AlignCenter, self.glyph)
        painter.restore()
        ring = QColor(self.color if self.lit else QColor(255, 110, 230))
        ring.setAlpha(255 if self.lit or self._hover > 0.3 else 190)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(ring, 2.0 + 1.2 * self._hover))
        painter.drawEllipse(QPointF(0, 0), r, r)



class ConstellationView(QGraphicsView):
    """Полотно с плавным масштабом (колесо), панорамой (перетаскивание фона) и автоподгонкой."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.scene().setSceneRect(CONSTELLATION_SCENE)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                            | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)  # фон привязан к окну
        self._bg_pm = None              # свой фон (QPixmap) или None
        self._bg_cache = (None, None)   # (ключ: размер окна и размытие, подготовленная копия)
        self._bg_blur = 0               # размытие фона: 0 — оригинал, 100 — максимум
        self._fit_scale = 1.0
        self._auto_fit = True      # пока пользователь не менял масштаб — сеть сама вписывается в окно

    def fit_all(self):
        """Вписывает всю сеть в окно и центрирует её."""
        self.resetTransform()
        self.fitInView(CONSTELLATION_SCENE, Qt.AspectRatioMode.KeepAspectRatio)
        self._fit_scale = max(self.transform().m11(), 1e-6)
        self.centerOn(CONSTELLATION_SCENE.center())
        self._auto_fit = True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._auto_fit:
            self.fit_all()
        else:   # пользователь приблизил карту: сохраняем масштаб, но обновляем границы допустимого
            self._fit_scale = self._compute_fit_scale()

    def _compute_fit_scale(self) -> float:
        vp = self.viewport().size()
        return max(1e-6, min(vp.width() / CONSTELLATION_SCENE.width(),
                             vp.height() / CONSTELLATION_SCENE.height()))

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_fit:
            self.fit_all()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if not delta:
            return
        factor = 1.0015 ** delta                      # плавный шаг: зависит от величины прокрутки
        current = self.transform().m11()
        target = min(max(current * factor, self._fit_scale * CONSTELLATION_ZOOM_MIN),
                     self._fit_scale * CONSTELLATION_ZOOM_MAX)
        if abs(target - current) < 1e-9:
            event.accept()
            return
        self.scale(target / current, target / current)
        self._auto_fit = abs(target - self._fit_scale) < 1e-3
        if self._auto_fit:
            self.fit_all()
        event.accept()

    def set_background(self, pixmap):
        """Свой задний фон (None — стандартный тёмный). Рисуется на всё окно и не масштабируется картой."""
        self._bg_pm = pixmap if pixmap is not None and not pixmap.isNull() else None
        self._bg_cache = (None, None)
        self.viewport().update()

    def set_bg_blur(self, value: int):
        """Размытие заднего фона: 0 — исходное качество, дальше плавная градация до сильного размытия."""
        self._bg_blur = max(0, min(100, int(value)))
        self._bg_cache = (None, None)
        self.viewport().update()

    @staticmethod
    def _blurred(pm: QPixmap, strength: int, scale: float = 1.0) -> QPixmap:
        """Настоящее гауссово размытие (без «кубиков»): радиус пропорционален размеру картинки, поэтому
        вид одинаков на экране и на HD-скриншоте; края зеркально достраиваются, чтобы не темнели."""
        if strength <= 0 or pm.isNull():
            return pm
        w, h = pm.width(), pm.height()
        radius = 0.035 * max(w, h) * (strength / 100.0) ** 1.4      # плавный старт от оригинала
        if radius < 0.4:
            return pm
        d = max(1, min(4, int(radius / 8)))                          # большое размытие считаем на уменьшенной копии
        img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        if d > 1:
            img = img.scaled(max(1, w // d), max(1, h // d), Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        iw, ih = img.width(), img.height()
        r = radius / d
        pad = max(1, min(int(r * 2.5) + 2, iw - 1, ih - 1))
        mh, mv, mb = img.mirrored(True, False), img.mirrored(False, True), img.mirrored(True, True)
        canvas = QImage(iw + 2 * pad, ih + 2 * pad, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.GlobalColor.transparent)
        p = QPainter(canvas)
        for image, (x, y) in ((img, (pad, pad)), (mh, (pad - iw, pad)), (mh, (pad + iw, pad)),
                              (mv, (pad, pad - ih)), (mv, (pad, pad + ih)),
                              (mb, (pad - iw, pad - ih)), (mb, (pad + iw, pad - ih)),
                              (mb, (pad - iw, pad + ih)), (mb, (pad + iw, pad + ih))):
            p.drawImage(x, y, image)
        p.end()
        scene = QGraphicsScene()
        item = QGraphicsPixmapItem(QPixmap.fromImage(canvas))
        fx = QGraphicsBlurEffect()
        fx.setBlurRadius(r)
        fx.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
        item.setGraphicsEffect(fx)
        scene.addItem(item)
        out = QImage(canvas.size(), QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        scene.render(p, QRectF(out.rect()), QRectF(canvas.rect()))
        p.end()
        result = QPixmap.fromImage(out.copy(pad, pad, iw, ih))
        if d > 1:
            result = result.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        return result

    def _scaled_background(self):
        size = self.viewport().size()
        key = (size, self._bg_blur)
        if self._bg_cache[0] != key:
            scaled = self._bg_pm.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                        Qt.TransformationMode.SmoothTransformation)
            self._bg_cache = (key, self._blurred(scaled, self._bg_blur))
        return self._bg_cache[1]

    def render_hd(self, long_side: int = 3840) -> QImage:
        """Снимок видимой области в высоком качестве: длинная сторона — long_side пикселей
        (по умолчанию 4K), фон, свечение, линии, узлы и подписи рисуются сразу в большом размере."""
        vp = self.viewport().rect()
        k = long_side / max(vp.width(), vp.height(), 1)
        size = QSize(max(1, round(vp.width() * k)), max(1, round(vp.height() * k)))
        img = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(8, 6, 14))
        p = QPainter(img)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                         | QPainter.RenderHint.TextAntialiasing)
        target = QRectF(0.0, 0.0, float(size.width()), float(size.height()))
        if self._bg_pm is not None:
            scaled = self._bg_pm.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                        Qt.TransformationMode.SmoothTransformation)
            scaled = self._blurred(scaled, self._bg_blur, k)
            p.drawPixmap((size.width() - scaled.width()) // 2, (size.height() - scaled.height()) // 2, scaled)
            p.fillRect(target, QColor(8, 6, 14, 150))
        source = self.mapToScene(vp).boundingRect()
        p.save()                                       # фоновое свечение рисуется в координатах сцены
        t = QTransform()
        t.scale(target.width() / source.width(), target.height() / source.height())
        t.translate(-source.x(), -source.y())
        p.setTransform(t)
        grad = QRadialGradient(QPointF(*CONSTELLATION_CENTER), 640.0)
        grad.setColorAt(0.0, QColor(60, 16, 70, 90))
        grad.setColorAt(0.6, QColor(30, 8, 40, 50))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(source, QBrush(grad))
        p.restore()
        self.scene().render(p, target, source, Qt.AspectRatioMode.IgnoreAspectRatio)
        p.end()
        return img

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor(8, 6, 14))
        if self._bg_pm is not None:
            painter.save()
            painter.resetTransform()                  # рисуем в координатах окна, а не сцены
            vp = self.viewport().rect()
            scaled = self._scaled_background()
            painter.drawPixmap((vp.width() - scaled.width()) // 2, (vp.height() - scaled.height()) // 2, scaled)
            painter.fillRect(vp, QColor(8, 6, 14, 150))   # тёмная подложка — линии и узлы остаются читаемыми
            painter.restore()
        grad = QRadialGradient(QPointF(*CONSTELLATION_CENTER), 640.0)
        grad.setColorAt(0.0, QColor(60, 16, 70, 90))
        grad.setColorAt(0.6, QColor(30, 8, 40, 50))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect, QBrush(grad))
