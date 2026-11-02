"""База данных SQLite (Database) и ключи дубликатов."""

import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from .catalog import _reward_row, BANNERS, LEGACY_BANNERS, rank_from_db, RANK_LETTERS, REWARD_COLS, WISH_COLS
from .config import ACTIVE_PROFILE_KEY, BANNER_ACTIVATED_PREFIX, DATE_FMT, PROFILE_NAME_MAX, TIME_SETTING_KEY
from .errors import DatabaseError
from .labels import reward_display_name


# ----------------------------------------------------------------------------
# База данных
# ----------------------------------------------------------------------------
def _wish_key(r: dict) -> tuple:
    return (r["banner"], r["rarity"], r["name"], r["pulled_at"], int(r.get("is_bonus", 0)),
            r.get("arc_kind", "") or "", r.get("cashback", "") or "")



def _reward_key(r: dict) -> tuple:
    # имя берём через reward_display_name, чтобы старые записи с пустым именем
    # корректно сравнивались с новыми (у которых имя по умолчанию заполнено)
    return (r["kind"], reward_display_name(r), r["detail"], r["obtained_at"],
            r.get("banner", "") or "")



def enforce_bonus_rules(rec: dict) -> dict:
    """НОВОЕ: правила бонусной добычи на уровне базы. Запись с is_bonus=1 всегда ранга A,
    без типа S дуги и без кешбэка — иначе она могла бы попасть в статистику S или
    сломать гарант. Обычные записи возвращаются без изменений."""
    if not rec.get("is_bonus"):
        return rec
    return dict(rec, rarity=4, arc_kind="", cashback="")



def _insert_sql(table: str, cols: tuple) -> str:
    return (f"INSERT INTO {table} ({', '.join(cols)}) "
            f"VALUES ({', '.join(':' + c for c in cols)})")



class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.conn = None
        self.profile_id = 0   # НОВОЕ: id активного профиля (0 — профилей ещё нет)
        try:
            self.conn = sqlite3.connect(str(self.path))
            self.conn.row_factory = sqlite3.Row
            self._init_schema()
            self.load_active()
        except sqlite3.Error as e:
            if self.conn:
                self.conn.close()
                self.conn = None
            raise DatabaseError(f"Не удалось открыть базу данных:\n{self.path}\n\n{e}") from e

    def _ensure_columns(self, table: str, columns: dict):
        have = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
        for col, ddl in columns.items():
            if col not in have:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

    def _init_schema(self):
        """Создаёт таблицы и мигрирует старые базы.
        Старые столбцы (например, «featured») остаются нетронутыми."""
        with self.conn:
            run = self.conn.execute
            run("""CREATE TABLE IF NOT EXISTS wishes (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       banner TEXT NOT NULL,
                       rarity TEXT NOT NULL,
                       name TEXT NOT NULL,
                       pulled_at TEXT NOT NULL,
                       is_bonus INTEGER NOT NULL DEFAULT 0,
                       arc_kind TEXT NOT NULL DEFAULT '',
                       cashback TEXT NOT NULL DEFAULT ''
                   )""")
            run("""CREATE TABLE IF NOT EXISTS rewards (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       kind TEXT NOT NULL,
                       name TEXT NOT NULL DEFAULT '',
                       detail TEXT NOT NULL DEFAULT '',
                       obtained_at TEXT NOT NULL,
                       banner TEXT NOT NULL DEFAULT '',
                       no_pity INTEGER NOT NULL DEFAULT 0
                   )""")
            run("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            run("""CREATE TABLE IF NOT EXISTS profiles (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       name TEXT NOT NULL,
                       created_at TEXT NOT NULL DEFAULT ''
                   )""")
            self._ensure_columns("wishes", {"is_bonus": "INTEGER NOT NULL DEFAULT 0",
                                            "arc_kind": "TEXT NOT NULL DEFAULT ''",
                                            "cashback": "TEXT NOT NULL DEFAULT ''"})
            self._ensure_columns("rewards", {"banner": "TEXT NOT NULL DEFAULT ''",
                                             "no_pity": "INTEGER NOT NULL DEFAULT 0",
                                             "rarity": "TEXT NOT NULL DEFAULT ''"})  # OCR-ФИКС
            # НОВОЕ: seq — порядковый номер записи внутри пакетного импорта. Нужен, чтобы
            # крутки и предметы с ОДНИМ временем (десятикратный бросок) сохраняли порядок
            # скриншота: они лежат в разных таблицах, и по id их не сравнить. У старых и
            # вручную добавленных записей seq = 0 — их порядок не меняется.
            self._ensure_columns("wishes", {"seq": "INTEGER NOT NULL DEFAULT 0"})
            self._ensure_columns("rewards", {"seq": "INTEGER NOT NULL DEFAULT 0"})
            # НОВОЕ: batch_id — номер пакетного импорта (0 — запись не из пакета). Нужен для
            # кнопки «Отменить последний импорт».
            self._ensure_columns("wishes", {"batch_id": "INTEGER NOT NULL DEFAULT 0"})
            self._ensure_columns("rewards", {"batch_id": "INTEGER NOT NULL DEFAULT 0"})
            # НОВОЕ: profile_id — владелец записи. 0 — запись из старой базы без профилей:
            # её получает первый созданный профиль (см. create_profile).
            self._ensure_columns("wishes", {"profile_id": "INTEGER NOT NULL DEFAULT 0"})
            self._ensure_columns("rewards", {"profile_id": "INTEGER NOT NULL DEFAULT 0"})
            # Миграция рангов: старые числа 5/4/3 -> буквы S/A/B (выполняется один раз,
            # затрагивает только строки, где ранг ещё хранится числом)
            run("""UPDATE wishes SET rarity = CASE rarity WHEN 5 THEN 'S' WHEN 4 THEN 'A'
                                                       WHEN 3 THEN 'B' END
                   WHERE typeof(rarity) = 'integer' AND rarity IN (3, 4, 5)""")
            for table in ("wishes", "rewards"):  # перенос старых ключей баннеров
                for old, new in LEGACY_BANNERS.items():
                    run(f"UPDATE {table} SET banner = ? WHERE banner = ?", (new, old))
            # переименование персонажей: «Акане» -> «Аканэ Рин» (записи, привязки предметов)
            run("UPDATE wishes SET name = ? WHERE name = ?", ("Аканэ Рин", "Акане"))
            run("UPDATE rewards SET detail = ? WHERE detail = ? AND kind IN ('outfit', 'glider', 'paint')",
                ("Аканэ Рин", "Акане"))
            run("CREATE INDEX IF NOT EXISTS idx_wishes_time ON wishes(pulled_at, id)")
            run("CREATE INDEX IF NOT EXISTS idx_rewards_time ON rewards(obtained_at, id)")
            run("CREATE INDEX IF NOT EXISTS idx_wishes_profile ON wishes(profile_id, pulled_at, id)")
            run("CREATE INDEX IF NOT EXISTS idx_rewards_profile ON rewards(profile_id, obtained_at, id)")

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    # ---------- общие операции ----------
    def _select(self, sql: str, params=(), err: str = "Ошибка чтения базы данных") -> list:
        try:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"{err}:\n{e}") from e

    def _write(self, sql: str, seq=None, err: str = "Ошибка записи в базу данных") -> None:
        try:
            with self.conn:
                if seq is None:
                    self.conn.execute(sql)
                else:
                    self.conn.executemany(sql, seq)
        except sqlite3.Error as e:
            raise DatabaseError(f"{err}:\n{e}") from e

    @staticmethod
    def _new_only(records: list, existing: list, key) -> list:
        """Записи, которых ещё нет в базе (с учётом количества одинаковых копий)."""
        have, seen, out = Counter(map(key, existing)), Counter(), []
        for r in records:
            k = key(r)
            seen[k] += 1
            if seen[k] > have[k]:
                out.append(r)
        return out

    # ---------- настройки (запоминание введённого времени и т.п.) ----------
    def _scoped_key(self, key: str) -> str:
        """Ключ настройки, привязанный к активному профилю."""
        return f"p{self.profile_id}:{key}"

    def get_setting(self, key: str, default=None, scoped: bool = False):
        """scoped=True — настройка принадлежит активному профилю (время формы, отметки баннеров)."""
        if scoped:
            key = self._scoped_key(key)
        try:
            row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default
        except sqlite3.Error:
            return default

    def set_setting(self, key: str, value: str, scoped: bool = False) -> bool:
        if scoped:
            key = self._scoped_key(key)
        try:
            self._write("INSERT INTO settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", [(key, value)])
            return True
        except DatabaseError:
            return False

    # ---------- НОВОЕ: профили ----------
    def list_profiles(self) -> list:
        """Все профили (по порядку создания) с числом круток и предметов в каждом."""
        return self._select(
            "SELECT p.id, p.name, "
            "(SELECT COUNT(*) FROM wishes w WHERE w.profile_id = p.id) AS wishes_n, "
            "(SELECT COUNT(*) FROM rewards r WHERE r.profile_id = p.id) AS rewards_n "
            "FROM profiles p ORDER BY p.id ASC", err="Ошибка чтения профилей")

    def profile_count(self) -> int:
        try:
            return int(self.conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0])
        except sqlite3.Error:
            return 0

    def active_profile(self):
        for prof in self.list_profiles():
            if prof["id"] == self.profile_id:
                return prof
        return None

    def check_profile_name(self, name: str, exclude_id=None) -> str:
        """Проверяет никнейм и возвращает его в чистом виде; иначе DatabaseError."""
        clean = " ".join(str(name or "").split())
        if not clean:
            raise DatabaseError("Никнейм не может быть пустым.")
        if len(clean) > PROFILE_NAME_MAX:
            raise DatabaseError(f"Никнейм слишком длинный (не более {PROFILE_NAME_MAX} символов).")
        for prof in self.list_profiles():
            if prof["id"] != exclude_id and prof["name"].casefold() == clean.casefold():
                raise DatabaseError("Профиль с таким никнеймом уже существует.")
        return clean

    def create_profile(self, name: str) -> int:
        """Создаёт профиль. Если это первый профиль — он забирает все старые записи
        (profile_id = 0) и сохранённые настройки времени формы / отметки баннеров.
        Если активного профиля ещё нет, новый становится активным."""
        clean = self.check_profile_name(name)
        first = self.profile_count() == 0
        try:
            with self.conn:
                cur = self.conn.execute("INSERT INTO profiles (name, created_at) VALUES (?, ?)",
                                        (clean, datetime.now().strftime(DATE_FMT)))
                pid = int(cur.lastrowid)
                if first:
                    self.conn.execute("UPDATE wishes SET profile_id = ? WHERE profile_id = 0", (pid,))
                    self.conn.execute("UPDATE rewards SET profile_id = ? WHERE profile_id = 0", (pid,))
                    prefix = f"p{pid}:"
                    self.conn.execute(
                        "INSERT OR IGNORE INTO settings (key, value) "
                        "SELECT ? || key, value FROM settings WHERE key = ? "
                        "OR substr(key, 1, ?) = ?",
                        (prefix, TIME_SETTING_KEY, len(BANNER_ACTIVATED_PREFIX),
                         BANNER_ACTIVATED_PREFIX))
        except sqlite3.Error as e:
            raise DatabaseError(f"Не удалось создать профиль:\n{e}") from e
        if self.profile_id == 0:
            self.set_active_profile(pid)
        return pid

    def rename_profile(self, pid: int, name: str) -> str:
        clean = self.check_profile_name(name, exclude_id=pid)
        self._write("UPDATE profiles SET name = ? WHERE id = ?", [(clean, pid)],
                    "Не удалось переименовать профиль")
        return clean

    def delete_profile(self, pid: int) -> None:
        """Удаляет профиль вместе с его крутками, предметами и настройками. Последний
        оставшийся профиль удалить нельзя. Если удалён активный — активным становится первый."""
        ids = [p["id"] for p in self.list_profiles()]
        if pid not in ids:
            raise DatabaseError("Профиль не найден.")
        if len(ids) <= 1:
            raise DatabaseError("Нельзя удалить единственный профиль.")
        try:
            with self.conn:
                self.conn.execute("DELETE FROM wishes WHERE profile_id = ?", (pid,))
                self.conn.execute("DELETE FROM rewards WHERE profile_id = ?", (pid,))
                prefix = f"p{pid}:"
                self.conn.execute("DELETE FROM settings WHERE substr(key, 1, ?) = ?",
                                  (len(prefix), prefix))
                self.conn.execute("DELETE FROM profiles WHERE id = ?", (pid,))
        except sqlite3.Error as e:
            raise DatabaseError(f"Не удалось удалить профиль:\n{e}") from e
        if self.profile_id == pid:
            self.set_active_profile(next(i for i in ids if i != pid))

    def set_active_profile(self, pid: int) -> None:
        if pid not in [p["id"] for p in self.list_profiles()]:
            raise DatabaseError("Профиль не найден.")
        self.profile_id = pid
        self.set_setting(ACTIVE_PROFILE_KEY, str(pid))

    def load_active(self) -> None:
        """Определяет активный профиль по сохранённой настройке (иначе — первый профиль)."""
        try:
            ids = [r[0] for r in self.conn.execute("SELECT id FROM profiles ORDER BY id ASC")]
        except sqlite3.Error:
            ids = []
        try:
            pid = int(self.get_setting(ACTIVE_PROFILE_KEY))
        except (TypeError, ValueError):
            pid = 0
        if pid not in ids:
            pid = ids[0] if ids else 0
        self.profile_id = pid
        if pid and self.get_setting(ACTIVE_PROFILE_KEY) != str(pid):
            self.set_setting(ACTIVE_PROFILE_KEY, str(pid))

    # ---------- крутки (включая кешбэк и бонусы) ----------
    def fetch_all(self) -> list:
        """Все крутки в хронологическом порядке (старые первыми).
        Записи удалённого баннера «Новичковый» не возвращаются."""
        marks = ",".join("?" for _ in BANNERS)
        rows = self._select(
            f"SELECT id, seq, {', '.join(WISH_COLS)} FROM wishes "
            f"WHERE profile_id = ? AND banner IN ({marks}) "
            "ORDER BY pulled_at ASC, seq ASC, id ASC", (self.profile_id,) + tuple(BANNERS))
        for r in rows:  # в базе буква S/A/B, в программе — числовой ранг 5/4/3
            r["rarity"] = rank_from_db(r["rarity"])
        return rows

    def add_many(self, records: list) -> int:
        # числовой ранг -> буква S/A/B перед записью в базу
        rows = [dict(enforce_bonus_rules(r), rarity=RANK_LETTERS[enforce_bonus_rules(r)["rarity"]],
                     profile_id=self.profile_id) for r in records]
        self._write(_insert_sql("wishes", WISH_COLS + ("profile_id",)), rows)
        return len(records)

    def import_records(self, records: list):
        """Добавляет записи, пропуская существующие. Возвращает (добавлено, пропущено)."""
        to_add = self._new_only(records, self.fetch_all(), _wish_key)
        added = self.add_many(to_add) if to_add else 0
        return added, len(records) - added

    def delete_ids(self, ids: list) -> None:
        self._write("DELETE FROM wishes WHERE id = ? AND profile_id = ?",
                    [(i, self.profile_id) for i in ids], "Ошибка удаления")

    def clear_all(self) -> None:
        self._write("DELETE FROM wishes WHERE profile_id = ?", [(self.profile_id,)],
                    err="Ошибка очистки базы данных")

    # ---------- предметы (кубики, костюмы, планеры, скины) ----------
    def fetch_rewards(self) -> list:
        return self._select(
            f"SELECT id, seq, {', '.join(REWARD_COLS)} FROM rewards WHERE profile_id = ? "
            "ORDER BY obtained_at ASC, seq ASC, id ASC", (self.profile_id,),
            err="Ошибка чтения наград")

    def add_rewards(self, records: list) -> int:
        self._write(_insert_sql("rewards", REWARD_COLS + ("profile_id",)),
                    [dict(_reward_row(r), profile_id=self.profile_id) for r in records],
                    "Ошибка записи награды")
        return len(records)

    def import_rewards(self, records: list):
        to_add = self._new_only(records, self.fetch_rewards(), _reward_key)
        added = self.add_rewards(to_add) if to_add else 0
        return added, len(records) - added

    def import_batch(self, wishes: list, rewards: list):
        """Пакетное добавление круток и предметов ОДНОЙ транзакцией — либо записывается
        всё, либо (при ошибке) ничего.

        ИСПРАВЛЕНО: фильтр дубликатов убран. В игре несколько круток и наград могут выпасть в
        одну и ту же секунду, поэтому записи с одинаковым названием, типом и временем — разные
        записи, и в базу попадают ВСЕ переданные строки (раньше совпадающие с уже имеющимися
        молча отбрасывались через _new_only).

        Порядок: wishes и rewards приходят в порядке записи (bottom_to_top_order — старые
        первыми); относительный номер rec["seq"] сохраняет это чередование. Возвращает
        (круток добавлено, предметов добавлено)."""
        try:
            with self.conn:
                # Номера seq выдаются ПОСЛЕ всех существующих: при одинаковом времени
                # записи пакета идут после прежних, а между собой — в порядке пакета.
                base = 1 + max(
                    self.conn.execute("SELECT COALESCE(MAX(seq), 0) FROM wishes").fetchone()[0],
                    self.conn.execute("SELECT COALESCE(MAX(seq), 0) FROM rewards").fetchone()[0])
                batch = 1 + max(
                    self.conn.execute("SELECT COALESCE(MAX(batch_id), 0) FROM wishes").fetchone()[0],
                    self.conn.execute("SELECT COALESCE(MAX(batch_id), 0) FROM rewards").fetchone()[0])
                if wishes:
                    self.conn.executemany(
                        _insert_sql("wishes", WISH_COLS + ("seq", "batch_id", "profile_id")),
                        [dict(enforce_bonus_rules(r),
                              rarity=RANK_LETTERS[enforce_bonus_rules(r)["rarity"]],
                              seq=base + int(r.get("seq", 0)), batch_id=batch,
                              profile_id=self.profile_id)
                         for r in wishes])
                if rewards:
                    self.conn.executemany(
                        _insert_sql("rewards", REWARD_COLS + ("seq", "batch_id", "profile_id")),
                        [dict(_reward_row(r), seq=base + int(r.get("seq", 0)), batch_id=batch,
                              profile_id=self.profile_id)
                         for r in rewards])
        except sqlite3.Error as e:
            raise DatabaseError(f"Ошибка пакетной записи:\n{e}") from e
        return len(wishes), len(rewards)

    def import_file_ordered(self, wishes: list, rewards: list):
        """Импорт из файла JSON/CSV с сохранением порядка выпадения.

        Дубликаты пропускаются как раньше (с учётом количества одинаковых копий), но каждой
        добавленной записи выдаётся seq: если в файле есть номера (экспорт версии 2), записи
        получают seq в порядке этих номеров — единая цепочка круток И предметов; если номеров
        нет — в порядке следования в файле (крутки, затем предметы). Всё одной транзакцией.
        Возвращает (круток добавлено, круток пропущено, предметов добавлено, предметов пропущено)."""
        w_new = self._new_only(wishes, self.fetch_all(), _wish_key)
        r_new = self._new_only(rewards, self.fetch_rewards(), _reward_key)
        items = [("w", i, r) for i, r in enumerate(w_new)] + [("r", i, r) for i, r in enumerate(r_new)]
        has_seq = any(r.get("file_seq") is not None for _, _, r in items)
        if has_seq:   # записи без номера уходят в конец, между собой — в порядке файла
            items.sort(key=lambda t: (t[2].get("file_seq") is None,
                                      t[2].get("file_seq") or 0, t[0] == "w", t[1]))
        try:
            with self.conn:
                base = 1 + max(
                    self.conn.execute("SELECT COALESCE(MAX(seq), 0) FROM wishes").fetchone()[0],
                    self.conn.execute("SELECT COALESCE(MAX(seq), 0) FROM rewards").fetchone()[0])
                w_rows, r_rows = [], []
                for n, (kind, _, r) in enumerate(items):
                    if kind == "w":
                        rec = enforce_bonus_rules(r)
                        w_rows.append(dict(rec, rarity=RANK_LETTERS[rec["rarity"]], seq=base + n,
                                           batch_id=0, profile_id=self.profile_id))
                    else:
                        r_rows.append(dict(_reward_row(r), seq=base + n, batch_id=0,
                                           profile_id=self.profile_id))
                if w_rows:
                    self.conn.executemany(
                        _insert_sql("wishes", WISH_COLS + ("seq", "batch_id", "profile_id")), w_rows)
                if r_rows:
                    self.conn.executemany(
                        _insert_sql("rewards", REWARD_COLS + ("seq", "batch_id", "profile_id")), r_rows)
        except sqlite3.Error as e:
            raise DatabaseError(f"Ошибка импорта:\n{e}") from e
        return (len(w_new), len(wishes) - len(w_new), len(r_new), len(rewards) - len(r_new))

    def last_batch_id(self) -> int:
        """Номер последнего пакетного импорта, записи которого ещё есть в базе (0 — нет)."""
        try:
            pid = (self.profile_id,)
            return int(max(
                self.conn.execute("SELECT COALESCE(MAX(batch_id), 0) FROM wishes "
                                  "WHERE profile_id = ?", pid).fetchone()[0],
                self.conn.execute("SELECT COALESCE(MAX(batch_id), 0) FROM rewards "
                                  "WHERE profile_id = ?", pid).fetchone()[0]))
        except sqlite3.Error:
            return 0

    def batch_counts(self, batch_id: int) -> tuple:
        """(круток, предметов) в пакетном импорте batch_id."""
        try:
            return (self.conn.execute("SELECT COUNT(*) FROM wishes "
                                      "WHERE batch_id = ? AND profile_id = ?",
                                      (batch_id, self.profile_id)).fetchone()[0],
                    self.conn.execute("SELECT COUNT(*) FROM rewards "
                                      "WHERE batch_id = ? AND profile_id = ?",
                                      (batch_id, self.profile_id)).fetchone()[0])
        except sqlite3.Error:
            return (0, 0)

    def delete_batch(self, batch_id: int) -> tuple:
        """Удаляет все записи пакетного импорта одной транзакцией. Возвращает (круток, предметов)."""
        counts = self.batch_counts(batch_id)
        try:
            with self.conn:
                self.conn.execute("DELETE FROM wishes WHERE batch_id = ? AND profile_id = ?",
                                  (batch_id, self.profile_id))
                self.conn.execute("DELETE FROM rewards WHERE batch_id = ? AND profile_id = ?",
                                  (batch_id, self.profile_id))
        except sqlite3.Error as e:
            raise DatabaseError(f"Ошибка отмены импорта:\n{e}") from e
        return counts

    def delete_reward_ids(self, ids: list) -> None:
        self._write("DELETE FROM rewards WHERE id = ? AND profile_id = ?",
                    [(i, self.profile_id) for i in ids], "Ошибка удаления")

    def clear_rewards(self) -> None:
        self._write("DELETE FROM rewards WHERE profile_id = ?", [(self.profile_id,)],
                    err="Ошибка очистки наград")

    # ---------- резервные копии ----------
    def backup_to(self, dst_path: str) -> None:
        if Path(dst_path).resolve() == self.path.resolve():
            raise DatabaseError("Нельзя сохранить копию поверх рабочей базы.")
        dst = None
        try:
            dst = sqlite3.connect(dst_path)
            self.conn.backup(dst)
        except sqlite3.Error as e:
            raise DatabaseError(f"Не удалось создать резервную копию:\n{e}") from e
        finally:
            if dst:
                dst.close()

    def restore_from(self, src_path: str) -> None:
        if Path(src_path).resolve() == self.path.resolve():
            raise DatabaseError("Выбран файл текущей базы данных.")
        src = None
        try:
            src = sqlite3.connect(src_path)
            cols = {r[1] for r in src.execute("PRAGMA table_info(wishes)")}
            if not {"banner", "rarity", "name", "pulled_at"} <= cols:
                raise DatabaseError("Выбранный файл не является базой NTE Wish Tracker.")
            src.backup(self.conn)
            self.conn.row_factory = sqlite3.Row
            self._init_schema()  # миграция копий из старых версий
            self.load_active()   # НОВОЕ: активный профиль берётся из восстановленной базы
        except sqlite3.Error as e:
            raise DatabaseError(f"Не удалось восстановить базу данных:\n{e}") from e
        finally:
            if src:
                src.close()
