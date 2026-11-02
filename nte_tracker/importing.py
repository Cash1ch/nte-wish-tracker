"""Нормализация записей и загрузка из JSON / CSV / логов."""

import csv
import json
import re
from pathlib import Path

from .catalog import (
    ARC_BANNER, ARC_KINDS, BANNERS, BIND_KINDS, CASHBACK_RARITY, CASHBACK_TYPES, CYR_TO_LAT, EVENT_BANNER,
    LEGACY_BANNERS, LETTER_RANKS, NO_PITY_KINDS, qty_is_valid, QTY_OPTIONS, RARITIES, REMOVED_BANNERS,
    REWARD_KINDS, reward_rarity_to_db, STANDARD_BANNER,
)
from .labels import default_reward_name
from .ocr.dates import _normalize_date


# ----------------------------------------------------------------------------
# Нормализация записей (импорт из CSV/JSON/логов)
# ----------------------------------------------------------------------------
def _alias_map(labels: dict, extra: dict = None) -> dict:
    """Словарь «любое написание (в нижнем регистре) -> ключ»."""
    m = {k: k for k in labels}
    m.update({v.lower(): k for k, v in labels.items()})
    for key, words in (extra or {}).items():
        m.update({w: key for w in words})
    return m



BANNER_MAP = _alias_map(BANNERS, {
    EVENT_BANNER: ("limited", "character", "char", "event", "event_char", "limited_char"),
    STANDARD_BANNER: ("permanent", "regular", "standard_char"),
    ARC_BANNER: ("weapons", "arcs", "дуги"),
})



BANNER_MAP.update(LEGACY_BANNERS)



ARC_MAP = _alias_map(ARC_KINDS, {
    "standard": ("стандартная", "std", "perm", "permanent", "regular"),
    "event": ("ивентовая", "limited", "evt"),
})



CASHBACK_MAP = _alias_map(CASHBACK_TYPES, {"regular": ("normal", "basic"), "premium": ("премиум",)})



REWARD_KIND_MAP = _alias_map(REWARD_KINDS)



TRUE_WORDS = {"1", "true", "yes", "y", "t", "да", "bonus", "бонус"}



FALSE_WORDS = {"", "0", "false", "no", "n", "f", "нет", "none"}



def _lookup(value, mapping: dict, what: str, allow_empty: bool = False) -> str:
    s = str(value or "").strip().lower()
    if not s and allow_empty:
        return ""
    if s in mapping:
        return mapping[s]
    raise ValueError(f"{what}: {value!r}")



def _normalize_banner(value) -> str:
    if str(value or "").strip().lower() in REMOVED_BANNERS:
        raise ValueError("баннер «Новичковый» больше не поддерживается")
    return _lookup(value, BANNER_MAP, "неизвестный баннер")



def _normalize_rarity(value) -> int:
    """Ранг из импорта: S / A / B (в том числе кириллические А, В) или старые 5 / 4 / 3,
    «5★». Возвращает числовой ранг 5/4/3."""
    text = str(value or "").strip().upper().translate(CYR_TO_LAT)
    m = re.match(r"([SAB])(?:\W|$)", text)
    if m:
        return LETTER_RANKS[m.group(1)]
    m = re.search(r"\d", text)
    if not m or int(m.group()) not in RARITIES:
        raise ValueError(f"неверная редкость (ожидается S, A или B): {value!r}")
    return int(m.group())



def _normalize_bool(value) -> int:
    s = str(value if value is not None else "").strip().lower()
    if s in TRUE_WORDS:
        return 1
    if s in FALSE_WORDS:
        return 0
    raise ValueError(f"неверное значение флага бонуса: {value!r}")



def _picker(raw: dict):
    """Возвращает pick(*ключи): первое непустое значение (ключи — без учёта регистра)."""
    if not isinstance(raw, dict):
        raise ValueError("запись не является объектом")
    low = {str(k).strip().lower(): v for k, v in raw.items()}

    def pick(*keys):
        return next((low[k] for k in keys if low.get(k) not in (None, "")), None)
    return pick



def _file_seq(pick):
    """Порядковый номер записи в файле экспорта (поле seq / order) или None, если его нет."""
    v = pick("seq", "order", "position")
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None



def normalize_record(raw: dict) -> dict:
    """Приводит произвольную запись к формату БД или бросает ValueError.
    Лишние поля (например, старое «featured») игнорируются."""
    pick = _picker(raw)
    name = str(pick("name", "item", "item_name", "title") or "").strip()
    if not name:
        raise ValueError("не указано название")
    banner = _normalize_banner(pick("banner", "gacha_type", "pool", "banner_type"))
    rarity = _normalize_rarity(pick("rarity", "stars", "rank", "star"))
    is_bonus = _normalize_bool(pick("is_bonus", "bonus", "extra"))
    cashback = _lookup(pick("cashback", "cashback_type"), CASHBACK_MAP,
                       "неизвестный тип кешбэка", allow_empty=True)
    if cashback:
        if is_bonus:
            raise ValueError("кешбэк не может быть бонусной добычей")
        rarity = CASHBACK_RARITY[cashback]
    elif is_bonus and rarity != 4:
        raise ValueError("дополнительная добыча должна быть A")
    arc_kind = _lookup(pick("arc_kind", "arc_type", "weapon_type"), ARC_MAP,
                       "неизвестный тип дуги", allow_empty=True)
    if not (banner == ARC_BANNER and rarity == 5 and not is_bonus and not cashback):
        arc_kind = ""
    return {
        "banner": banner, "rarity": rarity, "name": name,
        "pulled_at": _normalize_date(pick("pulled_at", "time", "date", "datetime", "timestamp")),
        "is_bonus": is_bonus, "arc_kind": arc_kind, "cashback": cashback,
        "file_seq": _file_seq(pick),
    }



def normalize_reward(raw: dict) -> dict:
    """Приводит запись предмета к формату БД или бросает ValueError.
    Пустое название заменяется названием типа; баннер необязателен (старые записи).
    detail: количество (кубики, фрагменты), имя персонажа (костюм, планер, окраска)
    или тип кешбэка."""
    pick = _picker(raw)
    kind = _lookup(pick("kind", "type"), REWARD_KIND_MAP, "неизвестный тип награды")
    name = str(pick("name", "title") or "").strip()
    detail = str(pick("detail", "details", "value") or "").strip()
    raw_banner = pick("banner", "gacha_type", "pool", "banner_type")
    if kind in QTY_OPTIONS:
        m = re.search(r"\d+", detail)
        if not m or not qty_is_valid(kind, m.group()):
            raise ValueError(f"{REWARD_KINDS[kind]}: количество должно быть "
                             f"{' или '.join(QTY_OPTIONS[kind])}, а не {detail!r}")
        detail = m.group()
    elif kind == "cashback":
        detail = _lookup(detail, CASHBACK_MAP, "неизвестный тип кешбэка")
    elif kind not in BIND_KINDS:
        detail = ""
    return {
        "kind": kind,
        "name": name or default_reward_name(kind, detail),
        "detail": detail,
        "obtained_at": _normalize_date(
            pick("obtained_at", "pulled_at", "time", "date", "datetime", "timestamp")),
        "banner": _normalize_banner(raw_banner) if raw_banner else "",
        "no_pity": int(kind in NO_PITY_KINDS or _normalize_bool(pick("no_pity"))),
        "rarity": reward_rarity_to_db(pick("rarity", "rank")),   # OCR-ФИКС
        "file_seq": _file_seq(pick),
    }



def normalize_all(raw: list, fn, label: str):
    """Применяет fn к каждой записи. Возвращает (корректные, тексты ошибок)."""
    valid, errors = [], []
    for i, rec in enumerate(raw, 1):
        try:
            valid.append(fn(rec))
        except ValueError as e:
            errors.append(f"{label} {i}: {e}")
    return valid, errors



def _read_json(path: Path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)



def load_json_records(path: Path) -> list:
    data = _read_json(path)
    if isinstance(data, dict):
        for key in ("records", "wishes", "pulls", "list", "data", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        if isinstance(data.get("rewards"), list):
            return []  # файл содержит только предметы
        raise ValueError("в JSON не найден список записей (ожидается ключ 'records')")
    if isinstance(data, list):
        return data
    raise ValueError("неподдерживаемая структура JSON")



def load_json_rewards(path: Path) -> list:
    data = _read_json(path)
    return data["rewards"] if isinstance(data, dict) and isinstance(data.get("rewards"), list) else []



def load_csv_records(path: Path) -> list:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return list(csv.DictReader(f, dialect=dialect))



# ----------------------------------------------------------------------------
# ЗАГЛУШКА: автоматический импорт из логов игры
# ----------------------------------------------------------------------------
def parse_game_logs(path: str) -> list:
    """
    ЗАГЛУШКА для автоматического импорта круток.

    Должна вернуть список словарей вида:
        {"banner": "event_character", "rarity": 5, "name": "Имя",
         "pulled_at": "2026-01-31 18:45:12", "is_bonus": 0, "arc_kind": "", "cashback": ""}
    (ключи и значения дополнительно нормализуются функцией normalize_record).

    Сейчас поддерживаются только JSON-файлы (см. load_json_records).
    Чтобы добавить чтение локальных логов игры:
      1. найдите файл лога (например, в папке игры или %LOCALAPPDATA%),
      2. найдите в нём строки/URL с историей круток,
      3. разберите их здесь и верните список записей.
    """
    p = Path(path)
    if p.suffix.lower() == ".json":
        return load_json_records(p)
    # TODO: реализовать разбор логов игры (.log / .txt)
    raise NotImplementedError(
        "Автоматический разбор логов игры пока не реализован.\n"
        "Реализуйте функцию parse_game_logs() в main.py "
        "или используйте импорт JSON/CSV."
    )
