"""Статистика, хронология и история."""

from collections import Counter

from .catalog import (
    ARC_BANNER, arc_kind_by_name, BANNERS, COUNTERS, ITEMS_COUNT_AS_PULL, NO_PITY_KINDS, PITY_CHAR_HARD,
    QTY_OPTIONS, REWARD_KINDS,
)
from .labels import _safe_int, reward_detail_text, reward_display_name, reward_rarity, wish_type_text
from .ocr.names import NON_PITY_RE


# ----------------------------------------------------------------------------
# Статистика и история
# ----------------------------------------------------------------------------
def build_timeline(rows: list, rewards: list) -> list:
    """Единая хронология круток и предметов (старые первыми). Предметы приводятся
    к тому же виду, что и крутки; src отличает источник ("wish" / "reward").
    ИЗМЕНЕНО: у предметов добавлено поле aliases — синонимы для поиска иконки
    (тип предмета и его название)."""
    events = [dict(r, src="wish") for r in rows]
    events += [dict(r, src="reward", rarity=reward_rarity(r), name=reward_display_name(r),
                    pulled_at=r["obtained_at"], is_bonus=0, arc_kind="", cashback="",
                    aliases=(r["kind"], REWARD_KINDS.get(r["kind"], "")))
               for r in rewards]
    # ИСПРАВЛЕНО: при одинаковом времени порядок задаёт seq (номер в пакетном импорте), и
    # только потом — старое правило (предметы раньше круток, затем id)
    events.sort(key=lambda e: (e["pulled_at"], e.get("seq", 0), e["src"] == "wish", e["id"]))
    return events



def _blank_stats() -> dict:
    return {"total": 0, "r3": 0, "r4": 0, "r5": 0, "bonus": 0,
            "counter": 0, "counter_std": 0, "counter_ev": 0,
            "pities": [], "last5": None, "last4": None,
            "items": Counter(), "qty": Counter(), "cash": Counter()}



def _count_item(s: dict, e: dict):
    """Учёт предмета в сводке пула. items — число записей по типам, qty — суммарное
    количество (кубики, фрагменты), cash — кешбэк. Считается всегда, в том числе для
    предметов вне гаранта."""
    if e["src"] == "reward":
        if e["kind"] == "cashback":
            s["cash"][e["detail"]] += 1
        else:
            s["items"][e["kind"]] += 1
            if e["kind"] in QTY_OPTIONS:
                s["qty"][e["kind"]] += _safe_int(e["detail"])
    elif e["cashback"]:
        s["cash"][e["cashback"]] += 1



def is_non_pity_event(e: dict) -> bool:
    """OCR-ФИКС 7: запись вне гаранта: бонус («Подарок за очки»), предмет с флагом no_pity
    («Страна сна» — фрагмент искривления) либо старая запись, в названии которой есть точный
    текст «Страна сна» / «Подарок за очки». Все остальные записи считаются как обычно."""
    if e.get("is_bonus"):
        return True
    if e.get("src") == "reward" and (e.get("no_pity") or e.get("kind") in NO_PITY_KINDS):
        return True
    return bool(NON_PITY_RE.search(f"{e.get('name') or ''} {e.get('detail') or ''}"))



def compute_stats(events: list):
    """
    events — хронология (build_timeline). Возвращает (stats по баннерам,
    {(src, id): данные счётчиков на момент записи}).

    Для каждого баннера отдельно ведутся счётчики ОСНОВНЫХ круток (кешбэк и, при
    ITEMS_COUNT_AS_PULL, предметы — тоже крутки):
      counter     — круток с прошлой S (любой) — гарант персонажей;
      counter_std — круток с прошлой S дуги ЛЮБОГО вида (стандартной или ивентовой), цель: 60;
      counter_ev  — круток с прошлой ИВЕНТОВОЙ S дуги, цель: 80 (стандартная S дуга его не сбрасывает).
    Предметы увеличивают счётчики, но НИКОГДА их не сбрасывают и не входят в
    статистику S/A; предметы с флагом no_pity (фрагмент искривления) не меняют
    счётчики вообще. Бонусные записи (is_bonus) НЕ увеличивают счётчики и общее
    число круток — они учитываются отдельно в s["bonus"].
    """
    stats = {key: _blank_stats() for key in BANNERS}
    pity_at = {}

    def snapshot(s):
        return {"bonus": False, "n": s["total"], "p5": s["counter"],
                "cs": s["counter_std"], "ce": s["counter_ev"]}

    for e in events:
        s = stats.get(e["banner"])
        if s is None:  # старые предметы без баннера и скрытые баннеры
            continue
        ref = (e["src"], e["id"])
        _count_item(s, e)
        if e["is_bonus"] or (e["src"] == "wish" and is_non_pity_event(e)):
            s["bonus"] += 1
            pity_at[ref] = {"bonus": True}
            continue
        # OCR-ФИКС 7: «Страна сна» / «Подарок за очки» остаются в истории, но НЕ прибавляют
        # крутку и не двигают гарант; все остальные предметы — по ITEMS_COUNT_AS_PULL.
        if e["src"] == "reward" and (is_non_pity_event(e) or not ITEMS_COUNT_AS_PULL):
            continue

        s["total"] += 1
        for k in COUNTERS:
            s[k] += 1
        if e["banner"] != ARC_BANNER:             # гарант персонажей: строго не больше 90
            s["counter"] = min(s["counter"], PITY_CHAR_HARD)
        pity_at[ref] = snapshot(s)
        if e["src"] == "reward":  # предмет: гарант не сбрасывается, статистика ранга не меняется
            continue

        s[f"r{e['rarity']}"] += 1
        if e["rarity"] == 5:
            s["pities"].append(s["counter"])
            s["counter"] = 0
            if e["banner"] == ARC_BANNER:
                s["counter_std"] = 0
                if arc_kind_by_name(e.get("name"), e.get("arc_kind") or "") == "event":
                    s["counter_ev"] = 0
            s["last5"] = e
        elif e["rarity"] == 4:
            s["last4"] = e
    return stats, pity_at



def history_entries(events: list, pity_at: dict) -> list:
    """Единая история: крутки (в т.ч. кешбэк и бонусы) + предметы, новые сверху.
    kind: main / cashback / bonus / item. ИЗМЕНЕНО: в записи добавлено поле aliases
    (синонимы для иконки; у обычных круток пустое)."""
    out = []
    for e in events:
        info, is_item = pity_at.get((e["src"], e["id"]), {}), e["src"] == "reward"
        if info.get("bonus"):
            kind, n, pity = "bonus", "+", "—"
        elif info:
            kind = "item" if is_item else ("cashback" if e["cashback"] else "main")
            n = str(info["n"])
            pity = (f"С:{info['cs']} · И:{info['ce']}" if e["banner"] == ARC_BANNER
                    else str(info["p5"]))
        else:  # предмет без баннера (старая запись) или счётчики для предметов отключены
            kind, n, pity = "item", "•", "—"
        if is_item:
            type_text = " ".join(t for t in (REWARD_KINDS.get(e["kind"], e["kind"]),
                                             reward_detail_text(e)) if t)
            if e.get("no_pity"):
                type_text += " · вне гаранта"
        else:
            type_text = wish_type_text(e)
        out.append({"src": e["src"], "id": e["id"], "banner": e["banner"] or None,
                    "banner_text": BANNERS.get(e["banner"], "—"), "rarity": e["rarity"],
                    "name": e["name"], "type": type_text, "date": e["pulled_at"],
                    "n": n, "pity": pity, "kind": kind, "p5": info.get("p5", 0),
                    "cs": info.get("cs", 0), "ce": info.get("ce", 0),
                    "arc_kind": e.get("arc_kind") or "",
                    "aliases": tuple(e.get("aliases", ()))})
    out.reverse()
    return out
