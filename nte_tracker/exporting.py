"""Экспорт данных в JSON / CSV с сохранением порядка выпадения."""

from datetime import datetime

from .catalog import rank_letter, REWARD_COLS, WISH_COLS
from .config import DATE_FMT
from .stats import build_timeline


EXPORT_FORMAT_VERSION = 2



def build_export_payload(rows: list, rewards: list, profile_name: str = "") -> dict:
    """Данные для JSON-экспорта с сохранением порядка выпадения.

    Крутки и предметы лежат в разных таблицах, поэтому раньше при одинаковом времени (десятикратный
    бросок) их чередование терялось. Теперь все записи выстраиваются в единую хронологию
    (build_timeline — ровно тот порядок, что виден в истории), и каждой выдаётся сквозной номер
    seq = 1..N. Списки records/rewards тоже записаны в этом порядке, поэтому даже программа,
    не знающая про seq, получит верную последовательность внутри каждого списка."""
    events = build_timeline(rows, rewards)
    pos = {(e["src"], e["id"]): n for n, e in enumerate(events, 1)}
    recs = sorted(rows, key=lambda r: pos[("wish", r["id"])])
    rews = sorted(rewards, key=lambda r: pos[("reward", r["id"])])
    return {
        "format_version": EXPORT_FORMAT_VERSION,
        "app": "NTE Wish Tracker",
        "exported_at": datetime.now().strftime(DATE_FMT),
        "profile": profile_name,
        "order": "seq — сквозной номер в хронологии (1 = самая старая запись); "
                 "при одинаковом времени порядок определяет seq",
        "counts": {"records": len(recs), "rewards": len(rews)},
        "records": [dict(export_wish(r), seq=pos[("wish", r["id"])]) for r in recs],
        "rewards": [dict({k: r[k] for k in REWARD_COLS}, seq=pos[("reward", r["id"])])
                    for r in rews],
    }



def export_wish(r: dict) -> dict:
    """Запись крутки для экспорта: ранг выводится буквой S/A/B."""
    rec = {k: r[k] for k in WISH_COLS}
    rec["rarity"] = rank_letter(r["rarity"])
    return rec
