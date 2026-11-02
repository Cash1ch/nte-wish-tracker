"""Сбор данных для карточки «Поделиться»."""

import re
from datetime import datetime

from ..catalog import (
    ARC_BANNER, arc_full_name, arc_kind_by_name, arc_short_name, EVENT_BANNER, PITY_ARC_EVENT, PITY_ARC_STD,
    PITY_CHAR_HARD, PITY_CHAR_SOFT, POOL_ROSTERS, POOL_TITLES, STANDARD_BANNER,
)
from ..labels import arc_event_only_stats, fmt_avg
from ..ui.banners import (
    arc_period_stats, banner_countdown, banner_period_stats, banner_pull_window, load_banner_art,
)
from ..ui.pool_page import PoolPage
from ..ui.staff_widgets import roster_counts, roster_key
from .renderer import SHARE_POOL_ACCENTS, SHARE_POOL_SHORT, SHARE_WATERMARK


# ----------------------------------------------------------------------------
# НОВОЕ: сбор данных для ShareCardRenderer (виджеты не снимаются — берутся только данные)
# ----------------------------------------------------------------------------
def _share_date(text) -> str:
    m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", str(text or ""))
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else str(text or "")



def _share_banner_card(key: str, entry, is_current: bool, s: dict, history: list, now) -> dict:
    """Данные одной плитки баннера (логика совпадает с PoolPage._fill_card / _fill_arc_card)."""
    is_arc = key == ARC_BANNER
    if is_arc:
        caption = "Дуга текущего персонажа" if is_current else "Дуга реран персонажа"
        empty = "Не определена" if is_current else "Не объявлена"
        generic = (("arc_current", "arc", "current_arc") if is_current else ("arc_rerun", "rerun_arc"))
    else:
        caption = "Текущий ивентовый персонаж" if is_current else "Реран персонажа"
        empty = "Не определён" if is_current else "Не объявлен"
        generic = (("current", "event") if is_current else ("rerun",))
    name = empty
    art = None
    if entry and entry.get("name"):
        name = arc_short_name(entry["name"]) if is_arc else entry["name"]
        try:
            if is_arc:
                art = (load_banner_art(arc_short_name(entry["name"]))
                       or load_banner_art(arc_full_name(entry["name"]), generic))
            else:
                art = load_banner_art(entry["name"], generic)
        except Exception:
            art = None
    text, _tip, kind = banner_countdown(entry, now)
    if entry:
        lo, hi = banner_pull_window(entry)
        st = arc_period_stats(history, lo, hi) if is_arc \
            else banner_period_stats(history, EVENT_BANNER, lo, hi)
        line = f"Круток за период: {st['pulls']} · S: {st['s']}"
    elif is_current:
        line = f"Круток в пуле: {s['total']} · S: {s['r5']}"
    else:
        line = ("Реран дуги пока не объявлен в banners.json" if is_arc
                else "Реран пока не объявлен в banners.json")
    return {"caption": caption, "name": name, "period": text, "kind": kind, "line": line, "art": art}



def _share_pool_data(win, key: str, history: list, now) -> dict:
    s = win.stats[key]
    page = win.pools.get(key)
    values = (s["total"], s["r5"], fmt_avg(s["pities"]))
    if key == ARC_BANNER:
        try:
            if win.db.get_setting("arc_hide_standard", "0", scoped=True) == "1":
                n_ev, avg_ev = arc_event_only_stats(history)
                values = (s["total"], n_ev, avg_ev)
        except Exception:
            pass
    pool = {"key": key, "title": POOL_TITLES[key], "accent": SHARE_POOL_ACCENTS.get(key, "#8ab4ff"),
            "stats": [(title, str(v), color) for title, color, v
                      in zip(PoolPage.CARD_TITLES, PoolPage.CARD_ACCENTS, values)],
            "bars": [], "soft_active": False, "chips": [], "banners": [], "roster": None}
    entries = (getattr(page, "_entries", None) or (None, None)) if page is not None else (None, None)
    current, rerun = entries
    info_known = page is not None and getattr(page, "_banner_info", None) is not None

    # --- гарант ---
    if key == ARC_BANNER:
        std, ev = s["counter_std"], s["counter_ev"]
        if current:
            lo, hi = banner_pull_window(current)
            st = arc_period_stats(history, lo, hi)
            std, ev = st["std"], st["ev"]
        for title, cur, target in (("Стандартная S дуга", std, PITY_ARC_STD),
                                   ("Ивентовая S дуга", ev, PITY_ARC_EVENT)):
            pool["bars"].append({"label": f"{title}: {cur}/{target}", "cur": cur, "max": target,
                                 "soft": None, "right": f"До гаранта: {max(0, target - cur)}"})
    else:
        c = s["counter"]
        if key == EVENT_BANNER and current:
            lo, hi = banner_pull_window(current)
            c = banner_period_stats(history, EVENT_BANNER, lo, hi)["pity"]
        c = min(c, PITY_CHAR_HARD)
        label = f"До гаранта: {c}/{PITY_CHAR_HARD}" if key == EVENT_BANNER \
            else f"Текущий: {c}/{PITY_CHAR_HARD}"
        pool["bars"].append({"label": label, "cur": c, "max": PITY_CHAR_HARD, "soft": PITY_CHAR_SOFT,
                             "right": f"До жёсткого гаранта: {max(0, PITY_CHAR_HARD - c)}"})
        pool["soft_active"] = c + 1 >= PITY_CHAR_SOFT

    # --- составы (стандартный пул) ---
    if key == STANDARD_BANNER and key in POOL_ROSTERS:
        counts = roster_counts(history, key)
        parts = {}
        for title, rarity, roster in POOL_ROSTERS[key]:
            tiles = [(n, counts.get((rarity, roster_key(n)), (n, 0))[1]) for n in roster]
            owned = sum(1 for _n, cnt in tiles if cnt)
            parts[rarity] = (f"{title} — получено {owned} из {len(roster)}", tiles, tiles)
        pool["roster"] = {"s_title": parts[5][0], "s": parts[5][1], "a_text": parts[4][0],
                          "a": parts[4][2]}
    return pool



def collect_share_data(win, only_key=None) -> dict:
    """Собирает данные карточки «Поделиться» из состояния главного окна. only_key — ключ
    пула текущей открытой страницы «Стафф»: карточка строится только для неё."""
    now = datetime.now()
    history = list(win.history)
    profile = ""
    try:
        prof = win.db.active_profile() if win.db.profile_id else None
        profile = prof["name"] if prof else ""
    except Exception:
        profile = ""
    keys = [only_key] if only_key in POOL_TITLES else list(POOL_TITLES)
    pools = [_share_pool_data(win, key, history, now) for key in keys]
    recent = []
    hidden_s = 0
    try:
        hide_std_arcs = win.db.get_setting("arc_hide_standard", "0", scoped=True) == "1"
    except Exception:
        hide_std_arcs = False
    for e in history:                                   # history — «новые сверху»
        if e["kind"] != "main" or e["rarity"] != 5 or e["banner"] not in keys:
            continue
        is_arc = e["banner"] == ARC_BANNER
        name = e["name"] or ""
        ev = bool(is_arc and arc_kind_by_name(name, e.get("arc_kind") or "") == "event")
        if is_arc and hide_std_arcs and not ev:
            hidden_s += 1
            continue
        pity = int((e["ce"] if ev else e["cs"]) if is_arc else e["p5"] or 0)
        recent.append({"name": name, "label": arc_short_name(name) if is_arc else name,
                       "rarity": 5, "pity": pity,
                       "hard": (PITY_ARC_EVENT if ev else PITY_ARC_STD) if is_arc else PITY_CHAR_HARD,
                       "pool": SHARE_POOL_SHORT.get(e["banner"], e.get("banner_text", "")),
                       "date": _share_date(e["date"]), "aliases": tuple(e["aliases"]),
                       "event": bool(is_arc and arc_kind_by_name(name, e.get("arc_kind") or "") == "event")})
    recent.reverse()                                    # как в приложении: от старых к новым
    return {"profile": profile, "generated": now, "pools": pools, "recent": recent,
            "total_s": sum(win.stats[k]["r5"] for k in keys) - hidden_s, "watermark": SHARE_WATERMARK,
            "page_title": POOL_TITLES[keys[0]] if len(keys) == 1 else ""}
