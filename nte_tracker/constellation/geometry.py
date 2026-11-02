"""Вкладка «Созвездие»: константы и геометрия магического круга."""

import json
import math

from PyQt6.QtCore import QRectF


def _map_translate_en_ru(text: str) -> str:
    import urllib.parse
    url = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ru&dt=t&q="
           + urllib.parse.quote(text))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return "".join(part[0] for part in data[0] if part and part[0]).strip()



# ----------------------------------------------------------------------------
# НОВОЕ: вкладка «Созвездие» — интерактивная сеть узлов вокруг портрета персонажа
# (QGraphicsView / QGraphicsScene). Колесо мыши — масштаб, перетаскивание фона — панорама,
# наведение — подсказка, клик — подробности (узлы без привязки к базе можно отмечать вручную).
# Названия типов узлов, подсказки и подписи редактируются в CONSTELLATION_TYPES ниже.
# ----------------------------------------------------------------------------
CONSTELLATION_CENTER = (625.0, 608.0)           # центр колец и портрета в координатах сцены



CONSTELLATION_BG_BLUR_KEY = "constellation_bg_blur"      # настройка профиля: размытие фона 0–100



CONSTELLATION_NO_GLOW_KEY = "constellation_no_glow"   # настройка профиля: «Отключить свечение»



CONSTELLATION_SCENE = QRectF(60.0, 43.0, 1130.0, 1130.0)   # симметрична относительно центра



CONSTELLATION_RINGS = (504.0, 408.0, 380.0)     # радиусы трёх концентрических колец (как на референсе)



CONSTELLATION_ZOOM_MIN, CONSTELLATION_ZOOM_MAX = 0.6, 8.0   # относительно «вписанного» масштаба



CONSTELLATION_DEFAULT_CHAR = "Аканэ Рин"



# тип узла: (название, тип предмета из базы или None, цвет, радиус, символ-заглушка, описание)
CONSTELLATION_TYPES = {
    "dice":   ("Шулерский кубик", "trick_cube", "#ff3b4e", 44.0, "⚃",
               "Кубик для бросков по доске. Берётся из вкладки «История» (тип «Шулерский кубик»)."),
    "record": ("Пластинка", None, "#ff5fa2", 44.0, "◉",
               "Памятная награда персонажа. Отметьте узел кликом, когда получите её."),
    "disc":   ("Диск", None, "#33c8ff", 44.0, "◎",
               "Награда за прохождение ветки доски. Отметьте узел кликом, когда получите её."),
    "orb":    ("Сфера", None, "#4d8dff", 44.0, "●",
               "Редкий ресурс развития. Отметьте узел кликом, когда получите его."),
    "egg":    ("Золотое яйцо", None, "#ffc83d", 24.0, "⬮",
               "Особый коллекционный предмет. Отметьте узел кликом, когда получите его."),
    "core":   ("Огненная капсула", None, "#ff8a1f", 40.0, "✹",
               "Ресурс усиления персонажа. Отметьте узел кликом, когда получите его."),
    "key":    ("Ключевой предмет", None, "#59d6ff", 40.0, "◆",
               "Центральная награда доски. Отметьте узел кликом, когда получите её."),
    "tube":   ("Пробирка", None, "#a86bff", 26.0, "▮",
               "Малый ресурс доски. Отметьте узел кликом, когда получите его."),
}



# ----------------------------------------------------------------------------
# Геометрия «магического круга» (точно по референсу). Все точки считаются от центра:
#   • внешняя декаграмма: 10 слотов через 36° (верхний слот пуст), радиус R_OUT;
#     нечётные слоты (кубики, сферы) — вершины большой пентаграммы (вершина внизу);
#   • «пробирки» стоят там, где линии большой пентаграммы пересекают кольцо R_RING
#     у каждой вершины (по две на вершину);
#   • «ключевой предмет» — внутренняя вершина большой пентаграммы (над портретом);
#   • малая пентаграмма (вершина вверху) R_SMALL: пробирка сверху, два яйца, две нижние пробирки;
#   • пентаграмма из пяти «огненных капсул» R_FIRE (вершина внизу);
#   • радиальные лучи: чётные внешние узлы (пластинки, диски) — к вершинам малой пентаграммы.
# ----------------------------------------------------------------------------
CONSTELLATION_R_OUT, CONSTELLATION_R_RING = 502.0, 380.0



CONSTELLATION_R_SMALL, CONSTELLATION_R_FIRE = 348.0, 255.0



CONSTELLATION_OUTER_SLOTS = {1: "dice", 2: "record", 3: "orb", 4: "disc", 5: "dice",
                             6: "disc", 7: "orb", 8: "record", 9: "dice"}   # слот 0 (верх) пуст



def _cpt(angle_deg: float, radius: float):
    a = math.radians(angle_deg)
    return (CONSTELLATION_CENTER[0] + radius * math.cos(a), CONSTELLATION_CENTER[1] + radius * math.sin(a))



def _constellation_geometry():
    """Возвращает (узлы [(тип, x, y, метка)], линии [(метка A, метка B)])."""
    pts = {}
    for k, t in CONSTELLATION_OUTER_SLOTS.items():
        pts[f"o{k}"] = (t,) + _cpt(-90 + 36 * k, CONSTELLATION_R_OUT)
    for k in range(5):                                       # огненные капсулы: 90°, 162°, 234°, 306°, 18°
        pts[f"f{k}"] = ("core",) + _cpt(90 + 72 * k, CONSTELLATION_R_FIRE)
    for tag, ang, t in (("sT", -90, "tube"), ("sR", -18, "egg"), ("sBR", 54, "tube"),
                        ("sBL", 126, "tube"), ("sL", 198, "egg")):
        pts[tag] = (t,) + _cpt(ang, CONSTELLATION_R_SMALL)
    inner = CONSTELLATION_R_OUT * math.cos(math.radians(72)) / math.cos(math.radians(36))
    pts["key"] = ("key",) + _cpt(-90, inner)
    # пробирки на пересечении рёбер большой пентаграммы с кольцом (ближе к вершине ребра)
    cx, cy = CONSTELLATION_CENTER
    for k in (1, 3, 5, 7, 9):
        for step in (4, -4):
            v, w = pts[f"o{k}"], pts[f"o{(k + step) % 10}"]
            dx, dy, fx, fy = w[1] - v[1], w[2] - v[2], v[1] - cx, v[2] - cy
            qa, qb = dx * dx + dy * dy, 2 * (fx * dx + fy * dy)
            qc = fx * fx + fy * fy - CONSTELLATION_R_RING ** 2
            t = (-qb - math.sqrt(qb * qb - 4 * qa * qc)) / (2 * qa)
            pts[f"t{k}_{step}"] = ("tube", v[1] + t * dx, v[2] + t * dy)
    order = ("dice", "record", "orb", "disc", "core", "egg", "key", "tube")
    nodes = sorted(((t, x, y, tag) for tag, (t, x, y) in pts.items()),
                   key=lambda n: (order.index(n[0]), n[3]))
    edges = []
    for k in (1, 3, 5, 7, 9):                                # большая пентаграмма (через одну вершину)
        edges.append((f"o{k}", f"o{(k + 4) % 10}"))
    edges += [("sT", "sBR"), ("sBR", "sL"), ("sL", "sR"), ("sR", "sBL"), ("sBL", "sT")]   # малая
    edges += [(f"f{k}", f"f{(k + 2) % 5}") for k in range(5)]                             # огненная
    edges += [("o2", "sR"), ("o8", "sL"), ("o4", "sBR"), ("o6", "sBL")]                   # лучи
    return tuple(nodes), tuple(edges)



CONSTELLATION_NODES, CONSTELLATION_EDGES = _constellation_geometry()
