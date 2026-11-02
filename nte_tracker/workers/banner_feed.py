"""Фоновый запрос и разбор текущего ивентового баннера."""

import json
import re
import time
import urllib.request
from datetime import datetime

from PyQt6.QtCore import pyqtSignal, QThread

from ..compat import requests
from ..catalog import EVENT_BANNER
from ..config import (
    BANNER_ARC_DATE_PREFIXES, BANNER_ARC_KEYS, BANNER_ARC_RERUN_DATE_PREFIXES, BANNER_ARC_RERUN_KEYS,
    BANNER_CURRENT_DATE_PREFIXES, BANNER_CURRENT_KEYS, BANNER_END_KEYS, BANNER_MAX_BYTES, BANNER_NAME_MAX_LEN,
    BANNER_RERUN_DATE_PREFIXES, BANNER_RERUN_KEYS, BANNER_START_KEYS, BANNER_TIMEOUT, BANNER_USER_AGENT,
)


# ----------------------------------------------------------------------------
# Главное окно
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# НОВОЕ: фоновый запрос текущего ивентового баннера
# ----------------------------------------------------------------------------
_LIVE_OCR_THREADS = set()     # НОВОЕ: потоки OCR, пережившие закрытие окна



_LIVE_BANNER_THREADS = set()  # потоки, пережившие закрытие окна (чтобы Qt не уничтожил их «на ходу»)



def parse_banner_datetime(value, end_of_day: bool = False):
    """Превращает значение из JSON в НАИВНОЕ местное datetime (или None, если не распознано).

    Понимает: ISO-строки (дата или дата+время, «Z»/смещение пояса — переводится в местное
    время), «ДД.ММ.ГГГГ [ЧЧ:ММ[:СС]]», «ГГГГ/ММ/ДД [ЧЧ:ММ]», Unix-время (сек или мс).
    end_of_day=True: если указана только дата, берётся конец суток (23:59:59) — для end_date.
    Ошибка разбора — не повод падать: срок просто считается неизвестным.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        ts = value / 1000 if value > 1e11 else value  # миллисекунды -> секунды
        try:
            return datetime.fromtimestamp(ts)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    dt = None
    try:
        dt = datetime.fromisoformat(text)   # дата, дата+время, «T», «Z», смещение
    except ValueError:
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
                    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    date_only = not re.search(r"\d:\d", text)  # во входной строке нет времени
    if dt.tzinfo is not None:                   # переводим в местное время компьютера
        dt = dt.astimezone().replace(tzinfo=None)
    elif date_only and end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt



def format_remaining(seconds: float) -> str:
    """Оставшееся время по-русски: «5 дн. 12 ч.» (от суток), «03 ч. 45 мин.»
    (меньше суток), «12 мин.» (меньше часа), «меньше минуты»."""
    total = int(seconds)
    if total < 60:
        return "меньше минуты"
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} дн. {hours} ч."   # формат «X дн. Y ч.» (минуты от суток не нужны)
    if hours:
        return f"{hours:02d} ч. {minutes:02d} мин."
    return f"{minutes} мин."



def pick_banner_dates(sources):
    """Достаёт (начало, конец) из JSON. sources — список пар (словарь, префикс ключей);
    берётся первое найденное значение. Нераспознанная дата -> None; если конец не позже
    начала, начало игнорируется."""
    found = {}
    for field, keys, end_of_day in (("start", BANNER_START_KEYS, False),
                                    ("end", BANNER_END_KEYS, True)):
        found[field] = None
        for src, prefix in sources:
            raw = next((src[prefix + k] for k in keys if src.get(prefix + k) not in (None, "")), None)
            if raw is not None:
                found[field] = parse_banner_datetime(raw, end_of_day)
                break
    start, end = found["start"], found["end"]
    if start and end and end <= start:
        start = None
    return start, end



def _lower_keys(d: dict) -> dict:
    """Копия словаря с ключами в нижнем регистре и без пробелов по краям: «Rerun_End_Time »
    и «rerun_end_time» читаются одинаково."""
    return {str(k).strip().lower(): v for k, v in d.items()}



def parse_rerun_entry(data):
    """Реран из JSON: {"name", "start", "end"} или None, если рерана нет / имя некорректно.

    Схема та же, что у основного баннера:
      * имя — строка («rerun_banner»: «Лакримоза») или объект {"name": ..., "end_time": ...};
      * дата окончания: внутри объекта (end_time / end_date / end …) ИЛИ на верхнем уровне
        с префиксом rerun_ (rerun_end_time, rerun_end_date, rerun_event_end_time …);
      * дата начала — аналогично (rerun_start_time …).
    Ошибка здесь не критична: без рерана правая половина панели просто пуста."""
    entry = next((data[k] for k in BANNER_RERUN_KEYS
                  if data.get(k) not in (None, "", {}, [])), None)
    sources = [(data, pre) for pre in BANNER_RERUN_DATE_PREFIXES]
    if isinstance(entry, dict):
        entry = _lower_keys(entry)
        name = entry.get("name") or entry.get("character") or entry.get("banner") or ""
        sources.insert(0, (entry, ""))     # даты внутри объекта рерана — в приоритете
    elif isinstance(entry, str):
        name = entry
    else:
        return None
    name = str(name).strip()
    if not name or len(name) > BANNER_NAME_MAX_LEN or "\n" in name:
        return None
    start, end = pick_banner_dates(sources)
    return {"name": name, "start": start, "end": end}



def parse_arc_entry(data, keys, prefixes):
    entry = next((data[k] for k in keys if data.get(k) not in (None, "", {}, [])), None)
    sources = [(data, prefix) for prefix in prefixes]
    if isinstance(entry, dict):
        entry = _lower_keys(entry)
        name = (entry.get("name") or entry.get("arc") or entry.get("weapon")
                or entry.get("banner") or "")
        sources.insert(0, (entry, ""))
    elif isinstance(entry, str):
        name = entry
    else:
        return None
    name = str(name).strip()
    if not name or len(name) > BANNER_NAME_MAX_LEN or "\n" in name:
        return None
    start, end = pick_banner_dates(sources)
    return {"name": name, "start": start, "end": end}



def parse_banner_payload(data) -> dict:
    """Достаёт из JSON текущий ивентовый баннер и (необязательно) реран.

    Основной формат: {"current_event_banner": "Имя"}. Допустимы также запасные формы
    (см. docstring в начале файла): значение-объект {"name": "Имя", "start": ..., "end": ...}
    и старый ключ "event_character". Реран: «rerun_banner» + «rerun_end_time» (см. parse_rerun_entry).
    Возвращает {"name": str, "start": datetime | None, "end": datetime | None,
                "rerun": {"name", "start", "end"} | None}.
    ИСПРАВЛЕНО: реран не зависит от основного баннера. Раньше при отсутствии
    current_event_banner выбрасывалась ошибка и реран пропадал вместе с ним; теперь ошибка
    только если нет НИ основного баннера, НИ рерана. Без основного баннера name == "".
    Даты (start_date / end_date или start_time / end_time) необязательны: если их нет или
    они не распознаны — соответствующее значение None.
    """
    if not isinstance(data, dict):
        raise ValueError("ожидался JSON-объект")
    data = _lower_keys(data)               # ключи верхнего уровня — без учёта регистра
    entry = next((data[k] for k in BANNER_CURRENT_KEYS
                  if data.get(k) not in (None, "", {}, [])), None)
    if entry is None:                      # запасные ключи — на случай другого названия поля
        entry = data.get(EVENT_BANNER) or data.get("character") or data.get("name")
    info = {"name": "", "start": None, "end": None}
    sources = [data]                       # где искать даты: сначала внутри объекта баннера,
    if isinstance(entry, dict):            # затем на верхнем уровне JSON
        entry = _lower_keys(entry)
        info["name"] = entry.get("name") or entry.get("character") or ""
        sources.insert(0, entry)
    elif isinstance(entry, str):
        info["name"] = entry
    info["start"], info["end"] = pick_banner_dates(
        [(src, "") for src in sources] + [(data, pre) for pre in BANNER_CURRENT_DATE_PREFIXES])
    info["rerun"] = parse_rerun_entry(data)   # реран персонажа (или None)
    info["arc"] = parse_arc_entry(data, BANNER_ARC_KEYS, BANNER_ARC_DATE_PREFIXES)
    info["arc_rerun"] = parse_arc_entry(data, BANNER_ARC_RERUN_KEYS,
                                        BANNER_ARC_RERUN_DATE_PREFIXES)
    name = str(info["name"]).strip()
    if not name or len(name) > BANNER_NAME_MAX_LEN or "\n" in name:
        if info["rerun"] is None and info["arc"] is None and info["arc_rerun"] is None:
            raise ValueError("в ответе нет корректного названия баннера")
        name, info["start"], info["end"] = "", None, None   # есть только реран
    info["name"] = name
    return info



class BannerFetchThread(QThread):
    """Скачивает JSON с баннерами в ФОНОВОМ потоке, чтобы интерфейс не зависал.

    Сигналы:
      fetched(object) — успех, словарь из parse_banner_payload() (имя, сроки, реран);
      failed(str)     — любая ошибка (нет сети, таймаут, плохой ответ). Причина нужна только
                        для отладки: пользователю никаких окон с ошибкой не показывается.
    ИЗМЕНЕНО: сигнал fetched теперь pyqtSignal(object) вместо pyqtSignal(dict): Qt не
    пытается преобразовать словарь в QVariantMap, и datetime / вложенный словарь рерана
    доходят до окна в точности такими, какими их собрал парсер.
    Адреса перебираются по очереди (BANNER_URLS); берётся первый, который скачался и
    разобрался. Сам поток НИКОГДА не бросает исключений наружу: всё перехватывается в run().
    """
    fetched = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, urls, parent=None):
        super().__init__(parent)
        self.urls = (urls,) if isinstance(urls, str) else tuple(urls)

    @staticmethod
    def _download(url: str) -> bytes:
        """Один запрос с таймаутом. requests — если установлен, иначе urllib.
        К адресу добавляется метка времени, а в заголовках — Cache-Control: no-cache, чтобы
        raw.githubusercontent.com не отдавал устаревшую копию файла из своего кэша."""
        headers = {"User-Agent": BANNER_USER_AGENT, "Accept": "application/json",
                   "Cache-Control": "no-cache"}
        url = f"{url}{'&' if '?' in url else '?'}t={int(time.time())}"
        if requests is not None:
            resp = requests.get(url, headers=headers, timeout=BANNER_TIMEOUT)
            resp.raise_for_status()
            return resp.content[:BANNER_MAX_BYTES + 1]
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=BANNER_TIMEOUT) as resp:
            return resp.read(BANNER_MAX_BYTES + 1)

    def run(self):
        errors = []
        for url in self.urls:
            try:
                raw = self._download(url)
                if len(raw) > BANNER_MAX_BYTES:
                    raise ValueError("ответ слишком большой")
                info = parse_banner_payload(json.loads(raw.decode("utf-8-sig")))
            except Exception as e:  # noqa: BLE001 — сеть может сломаться десятком способов
                errors.append(f"{url.split('/')[-2]}: {type(e).__name__}: {e}")
                continue                # пробуем следующий адрес
            self.fetched.emit(info)
            return
        self.failed.emit("; ".join(errors) or "нет адресов для запроса")
