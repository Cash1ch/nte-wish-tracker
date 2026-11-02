"""Система достижений: описание, метрики, менеджер (SQLite)."""

import sqlite3
import traceback
from datetime import datetime
from pathlib import Path

from .catalog import ARC_BANNER, EVENT_BANNER, STANDARD_BANNER
from .database import Database
from .labels import _safe_int
from .ui.profile_dialog import PROFILE_AVATAR_KEY


# ----------------------------------------------------------------------------
# НОВОЕ: система достижений — менеджер (SQLite), всплывающее уведомление, карточки
# ----------------------------------------------------------------------------
APP_SECONDS_KEY = "app_seconds"                # настройка профиля: секунды, проведённые в приложении



MINIGAME_PLAYS_KEY = "minigame_plays"         # настройка профиля: сколько раз запускались мини-игры



MINIGAME_IDS = ("invaders", "arkanoid", "platformer", "asteroids")   # настройка minigame_tried_<id> = "1"



FORTUNE_SPINS_KEY = "fortune_spins"           # настройка профиля: сколько раз прокручено колесо фортуны



ACH_SEEDED_KEY = "achievements_seeded"     # настройка профиля: достижения уже проверялись



ACH_GOLD = "#ffd740"



ACH_TOAST_HOLD_MS = 3600                   # сколько уведомление остаётся на экране



ACHIEVEMENTS = (
    {"id": "first_step", "title": "Первый шаг", "icon": "➤", "metric": "pulls", "target": 1,
     "description": "Импортируйте или добавьте первую крутку"},
    {"id": "hundred_pulls", "title": "Сотня", "icon": "✦", "metric": "pulls", "target": 100,
     "description": "Совершите 100 круток"},
    {"id": "five_hundred_pulls", "title": "Полтысячи", "icon": "◆", "metric": "pulls", "target": 500,
     "description": "Совершите 500 круток"},
    {"id": "thousand_pulls", "title": "Тысячник", "icon": "❂", "metric": "pulls", "target": 1000,
     "description": "Совершите 1000 круток"},
    {"id": "pulls_1500", "title": "Полторы тысячи", "icon": "✸", "metric": "pulls", "target": 1500,
     "description": "Совершите 1500 круток"},
    {"id": "pulls_2000", "title": "Двухтысячник", "icon": "✹", "metric": "pulls", "target": 2000,
     "description": "Совершите 2000 круток"},
    {"id": "s_collector", "title": "Коллекционер S", "icon": "★", "metric": "s_total", "target": 5,
     "description": "Получите 5 предметов S-ранга"},
    {"id": "s_rain", "title": "Звёздный дождь", "icon": "✪", "metric": "s_total", "target": 15,
     "description": "Получите 15 предметов S-ранга"},
    {"id": "lucky", "title": "Фортуна на моей стороне", "icon": "☘", "metric": "lucky", "target": 1,
     "description": "Получите S-ранг, потратив меньше 10 круток гаранта"},
    {"id": "true_pity", "title": "Настоящий гарант", "icon": "♛", "metric": "pity80", "target": 1,
     "description": "Получите S-ранг на гаранте 80 и выше"},
    {"id": "arc_hunter", "title": "Охотник за дугами", "icon": "❖", "metric": "arcs", "target": 10,
     "description": "Соберите 10 уникальных дуг"},
    {"id": "full_arsenal", "title": "Полный арсенал", "icon": "✚", "metric": "unique_s", "target": 10,
     "description": "Откройте 10 уникальных персонажей и дуг в «Стафф»"},
    {"id": "event_fan", "title": "Любимчик ивентов", "icon": "◈", "metric": "event_s", "target": 5,
     "description": "Получите 5 S-рангов с ивентового баннера персонажей"},
    {"id": "classic", "title": "Классика", "icon": "♦", "metric": "std_s", "target": 5,
     "description": "Получите 5 S-рангов со стандартного баннера персонажей"},
    {"id": "crazy", "title": "Чокнутый", "icon": "✺", "metric": "fortune_spins", "target": 100,
     "description": "Прокрутите колесо фортуны 100 раз",
     "reward_title": "Рецепт шаурмы", "reward_text": "RECIPE_SHAWARMA"},
    {"id": "time_1h", "title": "Заглянул на огонёк", "icon": "◔", "metric": "app_seconds", "target": 3600,
     "unit": "time", "description": "Проведите в приложении 1 час"},
    {"id": "time_10h", "title": "Завсегдатай", "icon": "◑", "metric": "app_seconds", "target": 36000,
     "unit": "time", "description": "Проведите в приложении 10 часов"},
    {"id": "time_50h", "title": "Живу здесь", "icon": "◕", "metric": "app_seconds", "target": 180000,
     "unit": "time", "description": "Проведите в приложении 50 часов"},
    {"id": "time_100h", "title": "Хранитель трекера", "icon": "●", "metric": "app_seconds", "target": 360000,
     "unit": "time", "description": "Проведите в приложении 100 часов"},
    {"id": "first_game", "title": "Давай поиграем", "icon": "▶", "metric": "game_plays", "target": 1,
     "description": "Запустите любую мини-игру"},
    {"id": "gamer_25", "title": "Заядлый геймер", "icon": "♜", "metric": "game_plays", "target": 25,
     "description": "Запустите мини-игры 25 раз"},
    {"id": "arcade_100", "title": "Аркадный маньяк", "icon": "♚", "metric": "game_plays", "target": 100,
     "description": "Запустите мини-игры 100 раз"},
    {"id": "all_games", "title": "Мастер на все руки", "icon": "✜", "metric": "games_tried", "target": 4,
     "description": "Попробуйте все 4 мини-игры"},
    {"id": "profile_face", "title": "Лицо профиля", "icon": "☻", "metric": "avatar", "target": 1,
     "description": "Установите аватарку профиля"},
)



def achievement_metrics(db: Database, stats: dict, history: list) -> dict:
    """Числа, по которым считается прогресс достижений активного профиля."""
    wishes = [e for e in history if e.get("src") == "wish"]
    s_rows = [e for e in wishes if e.get("rarity") == 5 and e.get("kind") in ("main", "cashback")]

    def named(e):
        return bool(e.get("name")) and e["name"] not in ("Персонаж", "Дуга")

    pities = [_safe_int(e.get("p5")) for e in s_rows if _safe_int(e.get("p5")) > 0]
    arcs = {e["name"].lower() for e in wishes if e.get("banner") == ARC_BANNER and named(e)
            and e.get("rarity") in (4, 5) and e.get("kind") in ("main", "cashback")}
    avatar_path = db.get_setting(PROFILE_AVATAR_KEY, "", scoped=True)
    return {
        "pulls": sum(s["total"] for s in stats.values()),
        "s_total": sum(s["r5"] for s in stats.values()),
        "lucky": int(any(p < 10 for p in pities)),
        "pity80": int(any(p >= 80 for p in pities)),
        "arcs": len(arcs),
        "unique_s": len({e["name"].lower() for e in s_rows if named(e)}),
        "event_s": sum(1 for e in s_rows if e.get("banner") == EVENT_BANNER),
        "std_s": sum(1 for e in s_rows if e.get("banner") == STANDARD_BANNER),
        "avatar": int(bool(avatar_path) and Path(avatar_path).is_file()),
        "fortune_spins": _safe_int(db.get_setting(FORTUNE_SPINS_KEY, "0", scoped=True)),
        "app_seconds": _safe_int(db.get_setting(APP_SECONDS_KEY, "0", scoped=True)),
        "game_plays": _safe_int(db.get_setting(MINIGAME_PLAYS_KEY, "0", scoped=True)),
        "games_tried": sum(1 for g in MINIGAME_IDS
                           if db.get_setting(f"minigame_tried_{g}", "0", scoped=True) == "1"),
    }



class AchievementManager:
    """Определения достижений + прогресс профиля в таблице achievements (SQLite)."""

    def __init__(self, db: Database):
        self.db = db
        try:
            with db.conn:
                db.conn.execute("""CREATE TABLE IF NOT EXISTS achievements (
                                       profile_id INTEGER NOT NULL,
                                       achievement_id TEXT NOT NULL,
                                       title TEXT NOT NULL DEFAULT '',
                                       description TEXT NOT NULL DEFAULT '',
                                       icon TEXT NOT NULL DEFAULT '',
                                       is_unlocked INTEGER NOT NULL DEFAULT 0,
                                       unlocked_at TEXT NOT NULL DEFAULT '',
                                       progress_current INTEGER NOT NULL DEFAULT 0,
                                       progress_target INTEGER NOT NULL DEFAULT 1,
                                       PRIMARY KEY (profile_id, achievement_id)
                                   )""")
        except sqlite3.Error:
            traceback.print_exc()

    def _stored(self, pid: int) -> dict:
        try:
            rows = self.db.conn.execute(
                "SELECT achievement_id, is_unlocked, unlocked_at, progress_current, progress_target "
                "FROM achievements WHERE profile_id = ?", (pid,)).fetchall()
        except sqlite3.Error:
            return {}
        return {r["achievement_id"]: r for r in rows}

    def evaluate(self, stats: dict, history: list) -> list:
        """Пересчитывает прогресс, сохраняет его и возвращает только что полученные достижения.
        Если у профиля уже были данные при первой проверке, старые достижения открываются тихо."""
        pid = self.db.profile_id
        if not pid:
            return []
        metrics = achievement_metrics(self.db, stats, history)
        stored = self._stored(pid)
        seeded = self.db.get_setting(ACH_SEEDED_KEY, "0", scoped=True) == "1"
        silent = not seeded and (metrics["pulls"] > 0 or metrics["avatar"] > 0)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        rows, fresh = [], []
        for d in ACHIEVEMENTS:
            old = stored.get(d["id"])
            was = bool(old and old["is_unlocked"])
            current = min(_safe_int(metrics.get(d["metric"], 0)), d["target"])
            done = was or current >= d["target"]
            at = old["unlocked_at"] if was else (now if done else "")
            rows.append((pid, d["id"], d["title"], d["description"], d["icon"], int(done), at,
                         d["target"] if done else current, d["target"]))
            if done and not was and not silent and not (old is None and seeded):
                fresh.append(d)
        try:
            with self.db.conn:
                self.db.conn.executemany(
                    "INSERT INTO achievements (profile_id, achievement_id, title, description, icon, "
                    "is_unlocked, unlocked_at, progress_current, progress_target) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(profile_id, achievement_id) DO UPDATE SET title = excluded.title, "
                    "description = excluded.description, icon = excluded.icon, "
                    "is_unlocked = excluded.is_unlocked, unlocked_at = excluded.unlocked_at, "
                    "progress_current = excluded.progress_current, "
                    "progress_target = excluded.progress_target", rows)
        except sqlite3.Error:
            traceback.print_exc()
            return []
        if not seeded:
            self.db.set_setting(ACH_SEEDED_KEY, "1", scoped=True)
        return fresh

    def all(self) -> list:
        """Все достижения активного профиля в порядке определения."""
        stored = self._stored(self.db.profile_id)
        out = []
        for d in ACHIEVEMENTS:
            r = stored.get(d["id"])
            out.append({"id": d["id"], "title": d["title"], "description": d["description"],
                        "icon": d["icon"], "is_unlocked": bool(r and r["is_unlocked"]),
                        "unlocked_at": r["unlocked_at"] if r else "",
                        "progress_current": _safe_int(r["progress_current"]) if r else 0,
                        "progress_target": d["target"], "unit": d.get("unit", ""),
                        "reward_title": d.get("reward_title", ""),
                        "reward_text": RECIPE_SHAWARMA if d.get("reward_text") == "RECIPE_SHAWARMA" else ""})
        return out



RECIPE_SHAWARMA = """Ингредиенты (на 2 штуки)

• Тонкий армянский лаваш — 2 шт.
• Куриное филе или бедро — 300 г
• Капуста (белокочанная или пекинская) — 100 г
• Огурец — 1 шт.
• Помидор — 1 шт.
• Соус: 3 ст. л. сметаны + 2 ст. л. майонеза + 1–2 зубчика чеснока (через пресс) + зелень, соль и перец по вкусу.

Приготовление

1. Подготовьте соус: смешайте сметану, майонез, измельченный чеснок, мелко нарезанную зелень и щепотку соли.
2. Пожарьте мясо: курицу нарежьте небольшими кусочками, посолите, добавьте специи (паприку, сушеный чеснок, перец) и обжарьте на сковороде до золотистой корочки (7–10 минут).
3. Нарежьте овощи: капусту мелко нашинкуйте (и немного помните руками), огурец и помидор нарежьте тонкой соломкой или ломтиками.
4. Соберите шаурму:
   • Разложите лаваш, смажьте центр соусом.
   • Выложите капусту, затем курицу, огурцы и помидоры.
   • Добавьте еще немного соуса сверху.
5. Заверните: подогните нижний и боковые края лаваша и скрутите в плотный рулет.
6. Обжарьте: подрумяньте шаурму на сухой сковороде (лучше гриль) по 1–2 минуты с каждой стороны до хрустящей корочки."""
