"""Поиск и отрисовка иконок персонажей, дуг и предметов."""

import re

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)

from .catalog import (
    ARC_A_NAMES, ARC_B_NAMES, ARC_KNOWN, ARC_S_NAMES, arc_short_name, DUGA_PREFIX, ICON_EXTS, RARITY_COLORS,
)
from .paths import asset_dirs


# ----------------------------------------------------------------------------
# Иконки
# ----------------------------------------------------------------------------
_PATH_CACHE = {}



_ICON_CACHE = {}



_ICON_DPR_OVERRIDE = None   # временно задаётся при экспорте «Поделиться» (сверх-разрешение)



def icon_dpr() -> float:
    """НОВОЕ: плотность пикселей экрана (масштаб Windows/macOS: 1.0, 1.25, 1.5, 2.0 ...).
    Берётся максимум по всем мониторам, чтобы иконки были чёткими на самом плотном из них.
    Иконки рисуются сразу в физическом разрешении — тогда Qt не растягивает маленькую
    картинку (именно это и давало «мыло» и пикселизацию на HiDPI-экранах)."""
    if _ICON_DPR_OVERRIDE:
        return float(_ICON_DPR_OVERRIDE)
    try:
        screens = QGuiApplication.screens()
        return max([1.0] + [float(sc.devicePixelRatio()) for sc in screens])
    except Exception:
        return 1.0



def scale_smooth(pm: QPixmap, width: int, height: int,
                 mode=Qt.AspectRatioMode.KeepAspectRatio, dpr: float = None) -> QPixmap:
    """НОВОЕ: единая функция качественного масштабирования QPixmap.
    Всегда Qt.TransformationMode.SmoothTransformation (билинейная фильтрация / усреднение
    площади при уменьшении) вместе с режимом пропорций (по умолчанию KeepAspectRatio).
    Размер (width, height) — логический; картинка строится в физических пикселях
    (× dpr) и получает devicePixelRatio, поэтому на HiDPI остаётся резкой."""
    if dpr is None:
        dpr = icon_dpr()
    out = pm.scaled(max(1, round(width * dpr)), max(1, round(height * dpr)),
                    mode, Qt.TransformationMode.SmoothTransformation)
    out.setDevicePixelRatio(dpr)
    return out



def _name_variants(name: str) -> list:
    safe = re.sub(r'[\\/:*?"<>|]', "", name.strip())
    slug = re.sub(r"\W+", "_", safe.lower(), flags=re.UNICODE).strip("_")
    candidates = [safe, safe.lower(), safe.replace(" ", "_"), safe.lower().replace(" ", "_"),
                  safe.replace(" ", "-"), safe.lower().replace(" ", "-"), slug]
    return list(dict.fromkeys(c for c in candidates if c))



def _search_icon(name: str):
    variants = _name_variants(name)
    lowered = {v.lower() for v in variants}
    for d in asset_dirs():
        if not d.is_dir():
            continue
        for v in variants:
            for ext in ICON_EXTS:
                if (d / (v + ext)).is_file():
                    return d / (v + ext)
        try:
            for p in d.iterdir():
                if p.suffix.lower() in ICON_EXTS and p.stem.lower() in lowered:
                    return p
        except OSError:
            pass
    return None



def icon_candidates(name: str, aliases=()) -> list:
    """НОВОЕ: список имён для поиска иконки по порядку важности: само название, затем
    синонимы. Для каждого имени добавляется вариант без префикса «Дуга - » и без
    скобок с количеством: «Дуга - Клинок» -> «Клинок», «Твердый кубик (5 шт)» ->
    «Твердый кубик»."""
    out = []
    for n in (name, *aliases):
        n = (n or "").strip()
        if not n:
            continue
        out.append(n)
        short = re.sub(r"^(?:Дуга|Планер)\s*-\s*", "", n)
        short = re.sub(r"\s*\([^)]*\)\s*$", "", short).strip()
        if short and short != n:
            out.append(short)
    return list(dict.fromkeys(out))



GENERIC_ARC_ICON_NAMES = ("Дуга", "default_arc", "arc_generic")



_ARC_AB_SHORT = {n.lower() for n in (*ARC_A_NAMES, *ARC_B_NAMES)}



_ARC_S_SHORT = {n.lower() for n in ARC_S_NAMES}



def is_generic_arc(name, aliases=(), rarity=None) -> bool:
    """Дуга A или B ранга -> True (используется единая общая иконка дуги).
    Дуги S ранга всегда сохраняют свои уникальные иконки."""
    if rarity == 5:
        return False
    for n in (name, *aliases):
        raw = str(n or "").strip()
        if not raw:
            continue
        short = arc_short_name(raw).strip().lower()
        has_prefix = raw.lower().startswith(DUGA_PREFIX.lower().strip()) or short != raw.lower()
        if short in _ARC_S_SHORT and has_prefix:
            return False
        if has_prefix:
            if short in _ARC_S_SHORT:
                return False
            if short in _ARC_AB_SHORT or rarity in (3, 4):
                return True
        known = ARC_KNOWN.get(raw.lower())
        if known is not None:
            return known[1] in (3, 4)
        if raw.lower() == "дуга" and rarity in (3, 4):
            return True
    return False



def find_generic_arc_icon_path():
    key = ("__generic_arc__",)
    if key not in _PATH_CACHE:
        _PATH_CACHE[key] = next((p for p in map(_search_icon, GENERIC_ARC_ICON_NAMES) if p), None)
    return _PATH_CACHE[key]



def find_icon_path(name: str, aliases=(), rarity=None):
    """Ищет файл иконки по названию (и синонимам) в assets/ и icons/ вместе с
    подпапками. Возвращает Path или None. Для дуг A и B ранга всегда возвращается
    единая общая иконка (default_arc / arc_generic); уникальные иконки — только у S."""
    aliases = tuple(aliases)
    if is_generic_arc(name, aliases, rarity):
        return find_generic_arc_icon_path()
    names = tuple(icon_candidates(name, aliases))
    if names not in _PATH_CACHE:
        _PATH_CACHE[names] = next((p for p in map(_search_icon, names) if p), None)
    return _PATH_CACHE[names]



def _initials(name: str) -> str:
    words = re.findall(r"\w+", name or "", flags=re.UNICODE)
    if not words:
        return "?"
    return words[0][:2].upper() if len(words) == 1 else (words[0][0] + words[1][0]).upper()



# НОВОЕ: параметры «стеклянных» иконок
ICON_RADIUS_RATIO = 0.25     # радиус скругления = 25 % стороны (56 px -> 12 px)



ICON_SHADOW_MIN_SIZE = 40    # у иконок меньше этого размера тени нет (не уменьшать картинку)



def make_pixmap(name: str, rarity: int, size: int = 48, aliases=(), thin: bool = False) -> QPixmap:
    """Иконка в стиле «стекло» (Glassmorphism) для персонажей, дуг и предметов.
    ИЗМЕНЕНО: плавное скругление углов; полупрозрачная подложка (видна у PNG с прозрачным
    фоном) и диагональный блик; тонкая светлая полупрозрачная кромка; кольцо цвета ранга
    (S — золотое, A — фиолетовое, B — синее); мягкая тень (несколько слоёв прозрачного
    чёрного) рисуется внутри самой картинки, поэтому размеры иконок в интерфейсе не меняются.
    Запасной вариант: если файла иконки нет — прозрачная заглушка с инициалами."""
    aliases = tuple(aliases)
    # ИЗМЕНЕНО (качество): иконка рисуется в ФИЗИЧЕСКИХ пикселях экрана. px — размер в
    # пикселях, dpr = px / size — точный коэффициент, чтобы логический размер остался
    # ровно size (иконки в интерфейсе не меняют размер), а картинка была резкой.
    px = max(1, round(size * icon_dpr()))
    dpr = px / size
    key = (name, rarity, size, aliases, px, thin)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    color = QColor(RARITY_COLORS.get(rarity, RARITY_COLORS[3]))
    pm = QPixmap(px, px)
    pm.setDevicePixelRatio(dpr)          # дальше все координаты — логические (как раньше)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    # ИЗМЕНЕНО: сглаживание линий, картинок и текста (заглушка с инициалами тоже без «лесенки»)
    p.setRenderHints(QPainter.RenderHint.Antialiasing
                     | QPainter.RenderHint.SmoothPixmapTransform
                     | QPainter.RenderHint.TextAntialiasing)

    # «Тело» иконки; по краям оставлено поле под тень (только у крупных иконок)
    pad = size * 0.07 if (size >= ICON_SHADOW_MIN_SIZE and not thin) else 0.0   # ИЗМЕНЕНО: thin — без поля под тень
    body = QRectF(pad, pad * 0.5, size - 2 * pad, size - 2 * pad)
    radius = body.width() * ICON_RADIUS_RATIO

    # 1) мягкая тень: слои прозрачного чёрного со сдвигом вниз, чем дальше — тем шире
    if pad:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 18))
        for i in range(1, 5):
            grow = pad * i / 5
            shadow = body.translated(0, pad * 0.5).adjusted(-grow, -grow, grow, grow)
            p.drawRoundedRect(shadow, radius + grow, radius + grow)

    # 2) содержимое обрезается по скруглённому прямоугольнику
    path = QPainterPath()
    path.addRoundedRect(body, radius, radius)
    p.setClipPath(path)
    p.fillRect(body, QColor(24, 27, 40, 170))  # полупрозрачная тёмная «стеклянная» подложка

    ip = find_icon_path(name, aliases, rarity) if (name or aliases) else None
    img = QPixmap(str(ip)) if ip is not None else None
    if img is not None and not img.isNull():
        # ИЗМЕНЕНО: масштабируем до ФИЗИЧЕСКОГО размера тела иконки (× dpr) с режимами
        # KeepAspectRatioByExpanding (без искажений, лишнее скрывает клип) и
        # SmoothTransformation (сглаживание). Позицию привязываем к целым физическим
        # пикселям, иначе картинка «плывёт» между пикселями и становится мутной.
        bw, bh = max(1, round(body.width() * dpr)), max(1, round(body.height() * dpr))
        scaled = img.scaled(bw, bh, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        ox = round(body.x() * dpr) + (bw - scaled.width()) // 2
        oy = round(body.y() * dpr) + (bh - scaled.height()) // 2
        p.drawPixmap(QPointF(ox / dpr, oy / dpr), scaled)
    else:
        # запасной вариант: полупрозрачная заглушка цвета ранга с инициалами
        tint = QColor(color)
        tint.setAlpha(60)
        p.fillRect(body, tint)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(8, int(size * 0.38)))
        p.setFont(font)
        p.setPen(color)
        p.drawText(body, Qt.AlignmentFlag.AlignCenter,
                   _initials("Дуга" if is_generic_arc(name, aliases, rarity)
                             else (name or next(iter(aliases), ""))))

    # 3) блик: белый диагональный градиент от левого верхнего угла (эффект стекла)
    sheen = QLinearGradient(body.topLeft(), body.bottomRight())
    sheen.setColorAt(0.0, QColor(255, 255, 255, 70))
    sheen.setColorAt(0.45, QColor(255, 255, 255, 18))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillRect(body, QBrush(sheen))
    p.setClipping(False)

    # 4) кольцо цвета ранга и тонкая светлая кромка «края стекла»
    p.setBrush(Qt.BrushStyle.NoBrush)
    ring = 1.0 if thin else max(1.6, size / 20.0)      # ИЗМЕНЕНО: thin — тонкая рамка 1 px
    ring_color = QColor(color)
    ring_color.setAlpha(190 if thin else 225)
    pen = QPen(ring_color)
    pen.setWidthF(ring)
    p.setPen(pen)
    p.drawRoundedRect(body.adjusted(ring / 2, ring / 2, -ring / 2, -ring / 2),
                      radius - ring / 2, radius - ring / 2)
    if not thin:
        rim = QPen(QColor(255, 255, 255, 90))
        rim.setWidthF(1.0)
        p.setPen(rim)
        p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    p.end()

    _ICON_CACHE[key] = pm
    return pm
