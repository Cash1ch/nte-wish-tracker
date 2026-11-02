"""Названия и текстовые описания предметов, круток и статистики."""

from .catalog import (
    ARC_BANNER, arc_kind_by_name, ARC_KINDS, BIND_KINDS, BONUS_TYPE_PREFIX, CASHBACK_RARITY, CASHBACK_TYPES,
    DUGA_PREFIX, FIXED_RARITY, LEGACY_REWARD_RARITY, LETTER_RANKS, QTY_OPTIONS, REWARD_KINDS,
    reward_rarity_to_db,
)


# ----------------------------------------------------------------------------
# Названия и описания предметов
# ----------------------------------------------------------------------------
def default_reward_name(kind: str, detail: str = "") -> str:
    """Название предмета, подставляемое, если пользователь не ввёл своё."""
    if kind in QTY_OPTIONS:
        return f"{REWARD_KINDS[kind]} ({detail or '?'} шт)"
    if kind == "cashback":
        return {"regular": "Обычный кешбэк", "premium": "Премиальный кешбэк"}.get(detail, "Кешбэк")
    return REWARD_KINDS.get(kind, kind)



def reward_display_name(r: dict) -> str:
    return (r.get("name") or "").strip() or default_reward_name(r["kind"], r.get("detail", ""))



def reward_detail_text(r: dict) -> str:
    """Короткое пояснение к предмету: количество, привязка к персонажу или тип кешбэка."""
    kind, detail = r["kind"], r.get("detail", "")
    if kind in QTY_OPTIONS:
        return f"×{detail}"
    if kind in BIND_KINDS:
        return f"→ {detail}" if detail else ""
    if kind == "cashback":
        return CASHBACK_TYPES.get(detail, detail)
    return ""



def reward_rarity(r: dict) -> int:
    # OCR-ФИКС: ранг, выбранный по цвету текста на скриншоте, важнее ранга вида предмета
    override = reward_rarity_to_db(r.get("rarity"))
    if override:
        return LETTER_RANKS[override]
    kind = r["kind"]
    if kind in FIXED_RARITY:
        return FIXED_RARITY[kind]
    if kind == "cashback":
        return CASHBACK_RARITY.get(r.get("detail"), 3)
    return LEGACY_REWARD_RARITY.get(kind, 3)



def wish_kind_label(r: dict) -> str:
    """НОВОЕ: вид крутки для колонки «Тип» — «Дуга» или «Персонаж».
    Сначала смотрим на название (префикс «Дуга - » или заглушка «Дуга»), затем на баннер:
    на баннере «Дуга» выпадают дуги, на остальных — персонажи."""
    name = (r.get("name") or "").strip()
    if name == "Дуга" or name.startswith(DUGA_PREFIX) or r.get("banner") == ARC_BANNER:
        return "Дуга"
    return "Персонаж"



def wish_type_text(r: dict) -> str:
    """Текст колонки «Тип» в истории. ИСПРАВЛЕНО: раньше у обычных круток колонка была
    пустой — теперь везде указан вид («Персонаж» / «Дуга»); у бонусной добычи — «Бонус
    (10 круток) · Дуга», у S дуг — «Стандартная дуга» / «Ивентовая дуга»."""
    if r.get("is_bonus"):
        return f"{BONUS_TYPE_PREFIX} - {wish_kind_label(r)}"   # OCR-ФИКС 3: «Бонус (10 круток) - Дуга»
    if r.get("cashback"):
        return f"Кешбэк: {CASHBACK_TYPES.get(r['cashback'], r['cashback'])}"
    if r["banner"] == ARC_BANNER and r["rarity"] == 5:
        return ARC_KINDS.get(r.get("arc_kind") or "", "Дуга S")
    return wish_kind_label(r)



def _safe_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default



def fmt_avg(values: list) -> str:
    return f"{sum(values) / len(values):.1f}" if values else "—"



def arc_event_only_stats(history: list) -> tuple:
    """(число ивентовых S-дуг, средний гарант по ним) — для режима «скрыть стандартные дуги».
    Гарант ивентовой дуги — крутки от прошлой ивентовой (стандартная S не сбрасывает)."""
    pulls = [int(e.get("ce") or 0) for e in history
             if e["banner"] == ARC_BANNER and e["kind"] == "main" and e["rarity"] == 5
             and arc_kind_by_name(e.get("name"), e.get("arc_kind") or "") == "event"]
    return len(pulls), fmt_avg(pulls)
