"""Простые настройки и константы приложения (заголовок, формат дат, баннеры, музыка, профили, анимации)."""

# ----------------------------------------------------------------------------
# Константы
# ----------------------------------------------------------------------------
APP_TITLE = "NTE Wish Tracker — Neverness to Everness"



DB_NAME = "nte_wishes.db"



DATE_FMT = "%Y-%m-%d %H:%M:%S"



QT_DATE_FMT = "yyyy-MM-dd HH:mm:ss"



TIME_SETTING_KEY = "last_pulled_at"  # последнее введённое время формы



TIME_SAVE_DELAY_MS = 600             # задержка записи времени формы в БД



SEARCH_DELAY_MS = 200                # задержка поиска в истории



# ---- НОВОЕ: автоопределение текущего ивентового баннера ----
BANNER_AUTODETECT = True             # False — вообще не ходить в интернет



# Адрес JSON с баннерами. Ожидаемый ответ:
#   {"current_event_banner": "Имя", "event_end_time": "...",
#    "rerun_banner": "Имя", "rerun_end_time": "..."}
# ИСПРАВЛЕНО: раньше в адресе стоял хэш коммита, из-за чего приложение вечно читало СТАРУЮ
# версию файла (без rerun_banner / rerun_end_time). Теперь адрес ведёт на актуальную ветку:
# HEAD — это ветка репозитория по умолчанию; main и master — запасные варианты.
BANNER_REPO_RAW = "https://raw.githubusercontent.com/Cash1ch/nte-banners/"



BANNER_BRANCHES = ("HEAD", "main", "master")



BANNER_FILE = "banners.json"



BANNER_URLS = tuple(f"{BANNER_REPO_RAW}{b}/{BANNER_FILE}" for b in BANNER_BRANCHES)



BANNER_URL = BANNER_URLS[0]          # оставлено для совместимости со старым кодом



BANNER_JSON_KEY = "current_event_banner"  # ключ с названием текущего баннера



BANNER_TIMEOUT = 3                   # секунд на запрос (соединение и чтение)



BANNER_MAX_BYTES = 64 * 1024         # ответ больше этого размера считаем мусором



BANNER_NAME_MAX_LEN = 60             # слишком длинное «имя» — признак мусора



BANNER_USER_AGENT = "NTE-Wish-Tracker/1.0"



# НОВОЕ: сроки баннера. Ключи JSON перебираются по порядку — берётся первый найденный.
BANNER_START_KEYS = ("event_start_time", "start_date", "start_time", "start")



BANNER_END_KEYS = ("event_end_time", "end_date", "end_time", "end")



# Для рерана к этим ключам добавляется префикс «rerun_»: rerun_end_time, rerun_start_time…
BANNER_TICK_MS = 1_000               # как часто обновлять подписи отсчёта (раз в секунду)



# ОБНОВЛЕНО: banners.json перечитывается с GitHub не только при запуске, но и периодически,
# поэтому новые персонажи и новые сроки подхватываются без перезапуска программы.
BANNER_REFRESH_MS = 15 * 60 * 1000   # раз в 15 минут (0 — только при запуске)



BANNER_NO_TIME_TEXT = "Время не указано"



BANNER_ENDED_TEXT = "Баннер завершён"



# НОВОЕ: реран и арт баннеров (вкладка «Стафф»)
# НОВОЕ: в таблице settings хранится момент, когда приложение впервые увидело баннер
# (ключ: banner_activated:<current|rerun>:<имя>). Если в JSON нет даты старта, крутки
# баннера считаются только начиная с этого момента — «задним числом» добавленные
# старые крутки в счётчик периода не попадают.
BANNER_ACTIVATED_PREFIX = "banner_activated:"



BANNER_RERUN_KEYS = ("rerun_banner", "current_rerun_banner", "rerun", "rerun_character",
                     "rerun_name", "rerun_character_banner")



BANNER_CURRENT_KEYS = (BANNER_JSON_KEY, "current_character_banner", "character_banner")



BANNER_CURRENT_DATE_PREFIXES = ("character_", "current_character_")



BANNER_RERUN_DATE_PREFIXES = ("rerun_", "rerun_character_")



BANNER_ARC_KEYS = ("current_arc_banner", "arc_banner", "current_arc", "event_arc_banner",
                   "event_arc", "arc")



BANNER_ARC_RERUN_KEYS = ("rerun_arc_banner", "arc_rerun_banner", "current_rerun_arc_banner",
                         "rerun_arc", "arc_rerun", "rerun_arc_name")



BANNER_ARC_DATE_PREFIXES = ("arc_", "current_arc_", "event_arc_")



BANNER_ARC_RERUN_DATE_PREFIXES = ("rerun_arc_", "arc_rerun_")



BANNER_ART_DIRS = ("banners", "characters")   # где искать арт: сначала banners/, затем characters/



BANNER_CARD_RADIUS = 16                       # скругление плитки баннера, px



BANNER_CARD_MIN_HEIGHT = 220                  # минимальная высота плитки баннера, px



# ---- НОВОЕ: фоновая музыка ----
# Путь к треку относительно папки программы (или папки с базой данных). Можно заменить
# на любой другой файл; если указанного расширения нет — пробуются MUSIC_EXTS.
MUSIC_FILE = "assets/audio/bgm.mp3"



MUSIC_EXTS = (".mp3", ".ogg", ".wav", ".flac", ".m4a", ".aac")



MUSIC_DEFAULT_VOLUME = 30            # громкость по умолчанию, % (фон не должен «орать»)



# НОВОЕ: фоновая анимация вкладки «Стафф» (настройки хранятся в таблице settings)
# НОВОЕ: профили игроков
ACTIVE_PROFILE_KEY = "active_profile_id"   # ключ в settings: id активного профиля



PROFILE_NAME_MAX = 32                      # максимальная длина никнейма



ANIM_ENABLED_KEY = "bg_anim_enabled"   # "1" — анимация включена, "0" — выключена



ANIM_EFFECT_KEY = "bg_anim_effect"     # snow | leaves | stars



ANIM_EFFECTS = (("snow", "Снежинки"), ("leaves", "Листочки"), ("stars", "Звёздочки"))



ANIM_DEFAULT_EFFECT = "snow"



ANIM_FRAME_MS = 33                     # ~30 кадров в секунду



MUSIC_VOLUME_KEY = "music_volume"    # ключ в таблице settings: громкость 0..100



MUSIC_MUTED_KEY = "music_muted"      # ключ в таблице settings: "1" — звук выключен



MUSIC_SAVE_DELAY_MS = 400            # задержка записи громкости в БД (debounce ползунка)
