"""Игровые справочники: баннеры, ранги, составы персонажей, дуги, наряды, виды предметов и лут."""

import re

from PyQt6.QtGui import QColor


EVENT_BANNER, STANDARD_BANNER, ARC_BANNER = "event_character", "standard_character", "arc"



BANNERS = {
    EVENT_BANNER: "Ивентовый персонаж",
    STANDARD_BANNER: "Стандартный персонаж",
    ARC_BANNER: "Дуга",
}



# Названия подвкладок раздела «Стафф»
POOL_TITLES = {
    EVENT_BANNER: "Ивентовые персонажи",
    STANDARD_BANNER: "Стандартные персонажи",
    ARC_BANNER: "Дуги",
}



RARITIES = (3, 4, 5)



# Ранги редкости. Внутри программы (счётчики, гарант, сравнения «>= A») используется
# число 5 / 4 / 3, а пользователю везде показывается буква:
#   S (бывш. 5★) — золотистый, A (бывш. 4★) — фиолетовый, B (бывш. 3★) — синий.
# В базе SQLite хранится буква (см. Database.add_many / fetch_all).
RANK_LETTERS = {5: "S", 4: "A", 3: "B"}



LETTER_RANKS = {v: k for k, v in RANK_LETTERS.items()}



# Цвета РАМОК В ИГРЕ, по которым OCR определяет ранг на скриншоте (не цвета интерфейса!).
# Рамка ранга B в игре серая, поэтому здесь «серый» оставлен намеренно.
RANK_COLOR_NAMES = {5: "золотистый", 4: "фиолетовый", 3: "серый"}



# Кириллические А и В визуально совпадают с латинскими — принимаем их как A и B
CYR_TO_LAT = str.maketrans({"А": "A", "В": "B"})



def rank_letter(rarity) -> str:
    """Число редкости (5/4/3) -> буква ранга (S/A/B)."""
    return RANK_LETTERS.get(rarity, "?")



def rank_from_db(value) -> int:
    """Значение из БД (буква S/A/B или старое число) -> числовой ранг 5/4/3."""
    text = str(value).strip().upper()
    if text in LETTER_RANKS:
        return LETTER_RANKS[text]
    return int(text) if text.isdigit() else 3



PITY_CHAR_SOFT, PITY_CHAR_HARD = 70, 90   # персонажи: мягкий / жёсткий гарант



PITY_ARC_STD, PITY_ARC_EVENT = 60, 80     # дуги: стандартная / ивентовая S



BONUS_EVERY = 10                          # бонусный A за каждые 10 круток



BONUS_LABEL = "Дополнительная добыча (бонус 10 круток)"



# Предметы (костюм, планер, скин, кубик) лежат на баннере и тратят крутку: True —
# они увеличивают счётчики круток, но никогда не сбрасывают гарант; False — вообще
# не затрагивают счётчики.
ITEMS_COUNT_AS_PULL = True



COUNTERS = ("counter", "counter_std", "counter_ev")



# ---- НОВОЕ: составы персонажей (вкладка «Стафф») ----
ROSTER_EVENT_S = ("Наналли", "Хотори", "Лакримоза", "Хаос", "Шинку", "Ирой", "Занку",
                  "Линко", "Блэкбёрд", "Аканэ Рин", "Элимс", "EXE")



ROSTER_STANDARD_S = ("Сакири", "Даффодил", "Фадия", "Цзююань", "Байканг", "Хатор")



ROSTER_A = ("Ханиэль", "Адлер", "Минт", "Ския", "Эдгар", "Аурелия")



# Какие составы показывает подвкладка пула: баннер -> ((заголовок, ранг 5/4, состав), ...).
# У дуг составов нет. Персонажи A ранга показываются в обоих персонажных пулах.
POOL_ROSTERS = {
    EVENT_BANNER: (("Ивентовые персонажи S ранга", 5, ROSTER_EVENT_S),
                   ("Персонажи A ранга", 4, ROSTER_A)),
    STANDARD_BANNER: (("Стандартные персонажи S ранга", 5, ROSTER_STANDARD_S),
                      ("Персонажи A ранга", 4, ROSTER_A)),
}



DROP_COLUMNS = 7                     # устарело: число плиток в строке теперь определяет FlowLayout по ширине окна



DROP_HISTORY_NEWEST_FIRST = False    # False — от старых к новым (хронология), True — наоборот



# Составы для подсказок/OCR/привязки: {имя в нижнем регистре: (имя, ранг, баннер)}.
# Баннер у A ранга не определён (None) — такие персонажи встречаются в обоих пулах.
ROSTER_KNOWN = {}



for _banner, _groups in POOL_ROSTERS.items():
    for _title, _rarity, _roster in _groups:
        for _name in _roster:
            ROSTER_KNOWN.setdefault(_name.lower(),
                                    (_name, _rarity, _banner if _rarity == 5 else None))



ARC_KINDS = {"standard": "Стандартная дуга", "event": "Ивентовая дуга"}



# НОВОЕ: единый префикс названия дуги. Названия дуг всегда хранятся как «Дуга - Название».
DUGA_PREFIX = "Дуга - "



# НОВОЕ: единый префикс названия планера: «Планер - Название» (как у дуг).
GLIDER_PREFIX = "Планер - "



# ---------------------------------------------------------------------------
# НОВОЕ: МАСТЕР-СПРАВОЧНИКИ для распознавания (OCR, нечёткое сопоставление, подсказки)
# ---------------------------------------------------------------------------
# Полный состав персонажей: ВСЕ ивентовые S, стандартные S и A ранга из кода программы
# (ROSTER_EVENT_S + ROSTER_STANDARD_S + ROSTER_A). Именно он питает match_roster_name /
# ROSTER_FOLDED и список известных имён. Новых персонажей добавляйте в кортежи ROSTER_* выше.
ALL_CHARACTERS = tuple(dict.fromkeys(ROSTER_EVENT_S + ROSTER_STANDARD_S + ROSTER_A))



# Планеры (ранг A — см. FIXED_RARITY["glider"]). Хранятся и показываются как «Планер - Название».
GLIDER_NAMES = (
    "Предвестник", "Суперпризрак", "Алая лента", "Овцелёт", "Пасмурный навес",
    "Небесный всадник", "Томатный дуэт", "Орхидеевый бриз", "Младший босс младшего босса",
)



# Дуги A ранга. Хранятся как «Дуга - Название»; ранг A подставляется по справочнику.
ARC_A_NAMES = (
    "Зонтик", "Космический восторг", "Блестящие дни", "Забытые", "Забытое", "Ора-Ора!",
    "Королевство разума!", "Великий вор", "Берегите головы!", "Чистое небо",
    "Я подожду тебя с жестокостью в сердце", "Обнаженный клинок", "Время придёт",
    "Бандит времени", "Зов искаженного города",
)



# НОВОЕ: дуги B ранга (серые). Хранятся как «Дуга - Название»; ранг B подставляется по справочнику,
# но цвет текста на скриншоте остаётся главным: фиолетовая/золотая дуга сохранит свой ранг.
# ИСПРАВЛЕНО: добавлены дуги «Будь счастлив» и «Мы.» — раньше их не было в справочнике, поэтому
# OCR не мог их исправить, а искажённое «Мы.» превращалось в персонажа «Минт».
ARC_B_NAMES = ("Опасная игра", "Настоящая музыка", "Будь счастлив", "Мы.", "Первый шаг к успеху")



# НОВОЕ: дуги S ранга и костюмы. В коде их пока нет — впишите названия сюда (или в файл
# master_names.json, см. «МАСТЕР-СПРАВОЧНИК» ниже): OCR будет находить их в строке и
# исправлять опечатки; ранг S у дуги подставится по справочнику.
# Стандартные дуги S ранга (стандартный пул дуг)
ARC_S_STANDARD_NAMES = (
    "Вечный вальс", "Сообщество Камелии", "Большой квест хорошего мальчика", "Слезы за маской",
    "Песнь кита", "Бушующее пламя", "Звёздная вуаль", "Ребяческая фантазия",
    "Убежище реальности", "Взорвать толпу",
)



# Ивентовые дуги S ранга (ивентовый пул дуг)
ARC_S_EVENT_NAMES = (
    "Заветное желание", "Алеющий мираж", "Ненасытный клинок", "Преступление и наказание",
    "Голос странника", "Полная готовность", "Неверные врата", "Последняя роза",
    "Обратная сторона Луны", "За пределы времени",
)



ARC_S_NAMES = ARC_S_STANDARD_NAMES + ARC_S_EVENT_NAMES



# {название дуги S: "standard" / "event"} — тип S дуги определяется по названию
ARC_S_KIND_BY_NAME = {**{n.lower(): "standard" for n in ARC_S_STANDARD_NAMES},
                      **{n.lower(): "event" for n in ARC_S_EVENT_NAMES}}



def arc_kind_by_name(name: str, default: str = "") -> str:
    """Тип S дуги («standard» / «event») по названию из справочника; иначе default."""
    key = re.sub(r"^\s*(?:дуга|arc|weapon)\s*[-:–—]\s*", "", str(name or ""), flags=re.I)
    return ARC_S_KIND_BY_NAME.get(key.strip().lower(), default)



def arc_short_name(name) -> str:
    return re.sub(r"^\s*(?:дуга|arc|weapon)\s*[-:–—]\s*", "", str(name or ""),
                  flags=re.I).strip()



def arc_full_name(name) -> str:
    short = arc_short_name(name)
    return f"{DUGA_PREFIX}{short}" if short else ""



BANNER_PANEL_KEYS = (EVENT_BANNER, ARC_BANNER)



ARC_POOL_ROSTERS = {
    ARC_BANNER: (
        ("Ивентовые дуги S ранга", 5, tuple(f"{DUGA_PREFIX}{n}" for n in ARC_S_EVENT_NAMES)),
        ("Стандартные дуги S ранга", 5, tuple(f"{DUGA_PREFIX}{n}" for n in ARC_S_STANDARD_NAMES)),
        ("Дуги A ранга", 4, tuple(f"{DUGA_PREFIX}{n}" for n in dict.fromkeys(ARC_A_NAMES)
                                  if n != "Забытые")),
    ),
}



# ИСПРАВЛЕНО (костюмы): единый префикс названия костюма: «Костюм - Название» (как у дуг и планеров).
# Тип записи у костюма ВСЕГДА «Костюм» (вид outfit, ранг S) — он никогда не становится персонажем.
OUTFIT_PREFIX = "Костюм - "



OUTFIT_RANK = 5          # костюмы — ранг S (золотой), см. FIXED_RARITY["outfit"]



# Все известные костюмы игры (без префикса). Новые костюмы добавляйте сюда или в
# master_names.json (ключ "outfits"): они сразу попадут в мастер-справочник с типом «Костюм».
OUTFIT_NAMES = (
    "Осенняя виньетка", "Сёрфинг среди звёзд", "Красное и чёрное", "Бесценная орхидея",
    "Архимаг", "Удар феникса", "Позолоченная рапсодия", "Чистое небо", "Ученица Терраси",
)



# Как ROSTER_KNOWN: {«дуга - название» в нижнем регистре: (название, ранг, баннер)}. Попадает в
# подсказки названий, автоопределение ранга и список «известных» имён OCR.
ARC_KNOWN = {f"{DUGA_PREFIX}{n}".lower(): (f"{DUGA_PREFIX}{n}", 5, ARC_BANNER)
             for n in ARC_S_NAMES}



ARC_KNOWN.update({f"{DUGA_PREFIX}{n}".lower(): (f"{DUGA_PREFIX}{n}", 3, ARC_BANNER)
                  for n in ARC_B_NAMES})



ARC_KNOWN.update({f"{DUGA_PREFIX}{n}".lower(): (f"{DUGA_PREFIX}{n}", 4, ARC_BANNER)
                  for n in ARC_A_NAMES})



# ИСПРАВЛЕНО (костюмы): {«костюм - название» в нижнем регистре: (название, ранг S, баннер None)}.
# Попадает в список «известных» имён OCR, поэтому костюм не считается «неизвестным именем».
OUTFIT_KNOWN = {f"{OUTFIT_PREFIX}{n}".lower(): (f"{OUTFIT_PREFIX}{n}", OUTFIT_RANK, None)
                for n in OUTFIT_NAMES}



# Баннеры из старых версий программы -> новые ключи
LEGACY_BANNERS = {"limited_character": EVENT_BANNER, "standard": STANDARD_BANNER,
                  "weapon": ARC_BANNER}



# Баннер «Новичковый» удалён: его записи остаются в базе, но скрыты.
REMOVED_BANNERS = {"beginner", "newbie", "novice", "newcomer", "новичковый"}



# Кешбэк — крутка со своей жёсткой редкостью (лежит в общей истории круток)
CASHBACK_TYPES = {"regular": "Обычный", "premium": "Премиальный"}



CASHBACK_RARITY = {"regular": 3, "premium": 4}



# Предметы (таблица rewards): тип -> название. «cube» (старый общий кубик), «arc»,
# «character» и «cashback» оставлены для чтения старых записей/экспортов.
REWARD_KINDS = {
    "solid_cube": "Твердый кубик", "trick_cube": "Шулерский кубик", "outfit": "Костюм",
    "glider": "Планер", "paint": "Окраска", "car_skin": "Скин на авто",
    "lost_fragment": "Потерянный фрагмент", "warp_fragment": "Фрагмент искривления",
    "cube": "Кубик", "arc": "Дуга", "character": "Персонаж", "cashback": "Кешбэк",
}



# Жёсткая редкость предметов.
# ИСПРАВЛЕНО: S (5, золотой) раньше стоял у кубиков, фрагментов и окраски — из-за этого обычные
# предметы показывались с золотым фоном. Теперь S остаётся только у настоящих «легендарных»
# предметов (костюм, скин на авто); персонажи и дуги получают ранг по своим правилам отдельно.
#   A (4, фиолетовый): кубики (твёрдый, шулерский, старый общий), планер, окраска;
#   B (3, синий):      фрагменты (потерянный, искривления).
# При необходимости поменяйте число (5 = S, 4 = A, 3 = B) — на старые записи в базе это
# подействует сразу: редкость предметов нигде не хранится, а считается по этой таблице.
FIXED_RARITY = {
    "solid_cube": 4, "trick_cube": 4, "cube": 4, "outfit": 5, "glider": 4, "paint": 4,
    "car_skin": 5, "lost_fragment": 3, "warp_fragment": 3,
}



LEGACY_REWARD_RARITY = {"character": 5, "arc": 4, "cashback": 3}



# Предметы с количеством: допустимые значения (хранятся в поле detail)
QTY_OPTIONS = {
    "solid_cube": ("1", "5"), "trick_cube": ("1", "5"), "cube": ("1", "5"),
    "lost_fragment": ("30", "50"), "warp_fragment": ("30", "16", "4"),
}



# Виды, у которых количество может быть любым числом (Фрагмент искривления в игре бывает
# 4, 16, 30 и др.): список QTY_OPTIONS — лишь подсказки для формы, OCR берёт значение с экрана.
QTY_FREE_KINDS = {"warp_fragment"}



def qty_is_valid(kind: str, value) -> bool:
    """Допустимо ли количество предмета: из списка QTY_OPTIONS либо (для свободных видов)
    любое число 1…999."""
    v = str(value or "").strip()
    if v in QTY_OPTIONS.get(kind, ()):
        return True
    return kind in QTY_FREE_KINDS and v.isdigit() and 0 < int(v) <= 999



def pick_item_qty(info: dict, qty) -> str:
    """Количество записи предмета по описанию вида (LOOT_TYPES) и значению с экрана."""
    opts = info.get("qty") or ()
    v = str(qty or "").strip()
    if v in opts:
        return v
    if info.get("qty_free") and v.isdigit() and 0 < int(v) <= 999:
        return v
    return opts[0] if opts else ""



# Предметы с привязкой к персонажу (имя персонажа хранится в поле detail)
BIND_KINDS = {"outfit", "glider", "paint"}



# Предметы вне гаранта: в базе помечаются флагом no_pity и не прибавляют счётчик круток
NO_PITY_KINDS = {"warp_fragment"}



def _loot(label, mode, default, **extra):
    """Тип добычи в форме. mode: wish — крутка; cashback — крутка с фикс. редкостью;
    reward — предмет с фикс. редкостью. Необязательные ключи:
    name_label — подпись поля названия; hide_name — поле названия не нужно;
    bind — есть привязка к персонажу; qty — варианты количества; no_pity — вне гаранта."""
    return {"label": label, "mode": mode, "default": default, **extra}



# Порядок = порядок в выпадающем списке «Что получено»
LOOT_TYPES = {
    "character": _loot("Персонаж", "wish", "Персонаж",
                       name_label="Имя персонажа (необязательно):"),
    "arc":       _loot("Дуга", "wish", "Дуга", name_label="Название дуги (необязательно):"),
    "solid1": _loot("Предмет - Твердый кубик 1 шт", "reward", "Твердый кубик (1 шт)",
                    kind="solid_cube", detail="1", hide_name=True),
    "solid5": _loot("Предмет - Твердый кубик 5 шт", "reward", "Твердый кубик (5 шт)",
                    kind="solid_cube", detail="5", hide_name=True),
    "trick1": _loot("Предмет - Шулерский кубик 1 шт", "reward", "Шулерский кубик (1 шт)",
                    kind="trick_cube", detail="1", hide_name=True),
    "trick5": _loot("Предмет - Шулерский кубик 5 шт", "reward", "Шулерский кубик (5 шт)",
                    kind="trick_cube", detail="5", hide_name=True),
    "outfit": _loot("Костюм", "reward", "Костюм", kind="outfit", bind=True,
                    name_label="Название костюма:"),
    "glider": _loot("Планер", "reward", "Планер", kind="glider", bind=True,
                    name_label="Название планера:"),
    "paint":  _loot("Детали модификации - Окраска", "reward", "Окраска", kind="paint",
                    bind=True, name_label="Название окраски:"),
    "lost_fragment": _loot("Предмет - Потерянный фрагмент", "reward", "Потерянный фрагмент",
                           kind="lost_fragment", qty=("30", "50"), hide_name=True),
    "warp_fragment": _loot("Предмет - Фрагмент искривления", "reward", "Фрагмент искривления",
                           kind="warp_fragment", qty=("30", "16", "4"), qty_free=True, hide_name=True,
                           no_pity=True),
    # Не вошли в новое ТЗ, но оставлены, чтобы не терять ввод скинов и кешбэка:
    "car_skin":   _loot("Скин на авто", "reward", "Скин на авто", kind="car_skin"),
    "cb_regular": _loot("Кешбэк (Обычный)", "cashback", "Обычный кешбэк", cashback="regular"),
    "cb_premium": _loot("Кешбэк (Премиальный)", "cashback", "Премиальный кешбэк",
                        cashback="premium"),
}



# Типы, которых нет в списке «Что получено» формы «Ручная» (остаются для OCR и уже записанной истории)
MANUAL_HIDDEN_LOOT = ("car_skin", "cb_regular", "cb_premium")



def loot_rarity(info: dict):
    """Жёсткая редкость типа добычи или None, если редкость выбирается вручную."""
    if info["mode"] == "reward":
        return FIXED_RARITY[info["kind"]]
    if info["mode"] == "cashback":
        return CASHBACK_RARITY[info["cashback"]]
    return None



def loot_aliases(key) -> tuple:
    """НОВОЕ: имена-синонимы для поиска иконки типа добычи: полное название записи,
    название типа, ключ вида (solid_cube) и ключ формы (solid5). Любой из этих файлов
    в assets/ (например, items/solid_cube.png) подойдёт."""
    info = LOOT_TYPES.get(key)
    if info is None:
        return ()
    names = [info["default"], info["label"], info.get("kind"), key]
    if info.get("cashback"):
        names.append(f"cashback_{info['cashback']}")
    return tuple(n for n in names if n)



WISH_COLS = ("banner", "rarity", "name", "pulled_at", "is_bonus", "arc_kind", "cashback")



# OCR-ФИКС: «rarity» — ранг предмета, выбранный по цвету текста на скриншоте (буква S/A/B);
# пусто — ранг берётся по виду предмета (FIXED_RARITY)
REWARD_COLS = ("kind", "name", "detail", "obtained_at", "banner", "no_pity", "rarity")



def reward_rarity_to_db(value) -> str:
    """OCR-ФИКС: ранг предмета для базы — буква S/A/B или пустая строка (число 5/4/3, буква
    и кириллические А/В принимаются; всё остальное — «не задан»)."""
    if value in (None, "") or isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return RANK_LETTERS.get(value, "")
    text = str(value).strip().upper().translate(CYR_TO_LAT)
    if text in LETTER_RANKS:
        return text
    return RANK_LETTERS.get(int(text), "") if text.isdigit() else ""



def _reward_row(r: dict) -> dict:
    """Запись предмета для INSERT: поле rarity всегда присутствует (по умолчанию пустое)."""
    return dict(r, rarity=reward_rarity_to_db(r.get("rarity")))



# Цвета рангов в интерфейсе — S золотистый, A фиолетовый, B синий. Эти же цвета
# используют иконки, плашки наград и выпадающие списки рангов.
RARITY_COLORS = {5: "#ffd740", 4: "#b66cff", 3: "#42a5f5"}



# Цвета строк таблицы (фон, текст)
ROW_COLORS = {
    5: (QColor(255, 193, 7, 70), QColor(255, 215, 64)),
    4: (QColor(156, 39, 176, 70), QColor(214, 160, 224)),
    3: (QColor(33, 150, 243, 45), QColor(144, 202, 249)),
}



ICON_EXTS = (".png", ".jpg", ".jpeg", ".webp")



ICON_DIR_NAMES = ("assets", "icons")



# НОВОЕ: подпапки внутри assets/ и icons/ (пустая строка — сама папка)
ICON_SUBDIRS = ("", "characters", "arcs", "items")



BONUS_TYPE_PREFIX = "Бонус (10 круток)"     # префикс колонки «Тип» у бонусной добычи
