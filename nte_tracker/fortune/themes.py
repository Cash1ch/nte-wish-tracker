"""Темы и настройки Колеса Фортуны."""

# =====================================================================================
# НОВОЕ: «Колесо Фортуны» (кнопка «Испытай судьбу» на вкладке «Стафф»).
#   * FORTUNE_* / _fortune_sound_files — звуки синтезируются при первом открытии и
#     сохраняются во временную папку (WAV): внешние файлы не нужны;
#   * FortuneSounds — фоновая тема, «тики» на каждом штифте, шум вращения (его громкость
#     следует за скоростью колеса) и победный перезвон; QSoundEffect, при любом сбое —
#     тишина без падения приложения;
#   * FortuneWheel — рисованное колесо и физика с инерцией: случайная начальная скорость,
#     три профиля торможения (быстрая остановка / долгий накат / «интрига» с ползущим
#     замедлением) и штифты на границах секторов, о которые колесо теряет энергию, из-за
#     чего оно может «перевалить» через сектор или откатиться назад;
#   * FortuneDialog — окно с вступительным текстом, редактируемым списком вариантов,
#     колесом, кнопкой «Удачи!» и карточкой победы;
#   * PulsingGlow — плавное «дыхание» свечения кнопки (прозрачность тени 0.4 -> 1.0).
# =====================================================================================
FORTUNE_INTRO_TEXT = ("Сомневаешься? Боишься сделать шаг, который изменит всё? Не пытайся предугадать судьбу - "
                      "доверься ей. Передай бразды правления в надёжные руки Госпожи Фортуны. "
                      "Пусть её колесо решит за тебя. Крути и узнай, что уготовано.")



FORTUNE_INTRO_TEXT_SAKURA = ("Лепесток сакуры не выбирает, куда упасть, — его несёт ветер судьбы. "
                             "Так и ты: не спорь с небом, прими дары, что протягивает тебе Госпожа Фортуна.")



FORTUNE_INTRO_TEXT_NTE = ("Хватит строить из себя героя. В Этеро удача решает всё: от утреннего кофе до того, "
                          "доживёшь ли ты до следующего заказа. Боишься, что твой выбор всё сломает? Расслабься. "
                          "Отдайся в надёжные объятия Госпожи Фортуны - она хотя бы честно играет по своим правилам.")



FORTUNE_INTRO_TEXT_PAWS = ("«Кто сказал, что маленькие лапки не решают большие судьбы? Ещё как решают - просто делают это мило. "
                           "Белый котёнок уже тянет лапку к колесу: дом, вкусняшка или новое приключение? "
                           "Пусть Госпожа Фортуна улыбнётся - а ты просто наслаждайся подарком.»")



FORTUNE_STYLE_KEY = "fortune_style"               # ключ в таблице settings: выбранный стиль ("classic" / "nte" / "sakura" / "paws")



FORTUNE_NTE_KEY = "fortune_nte_style"            # ключ в таблице settings: включён ли «Стиль NTE» ("1" / "0")



FORTUNE_DEFAULT_OPTIONS = ("Да, действуй!", "Нет, не стоит", "Подожди до завтра", "Рискни!",
                           "Спроси совета у друга", "Сделай первый шаг", "Отложи на неделю",
                           "Доверься интуиции")



FORTUNE_MIN_OPTIONS, FORTUNE_MAX_OPTIONS = 1, 24   # крутить можно и с одним вариантом; список при каждом открытии пуст



FORTUNE_COLORS = ("#e94f64", "#f0a43c", "#f2d24b", "#5cc47a", "#3fb7c9", "#4a7be8", "#8a5ce0", "#d65bb8",
                  "#ff7a59", "#7bd0a0")



# ---------- темы оформления: классическая и «Стиль NTE» (киберпанк ночного города) ----------
_FORTUNE_BTN_GRAD = "qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {a}, stop:1 {b})"



FORTUNE_THEMES = {
    "classic": {
        "bg": ("#120c24", "#241540"),
        "card": ("#34204f", "#1b1233"), "card_border": "#d9b45a",
        "title": "#ffd98a", "intro": "#f6e7bd",
        "panel_bg": "rgba(255,255,255,18)", "panel_border": "rgba(217,180,90,120)",
        "head": "#ffd98a", "hint": "#b8a8d8",
        "list_bg": "rgba(10,6,25,170)", "list_fg": "#f3ecff", "field_border": "#5a4690", "select": "#6a4bb0",
        "btn_bg": "#3b2a66", "btn_fg": "#f3ecff", "btn_border": "#6a4bb0", "btn_hover": "#4b3680",
        "btn_dis": ("#8a80a8", "#2a2048", "#3e3463"),
        "spin": (_FORTUNE_BTN_GRAD.format(a="#ffe08a", b="#d9a52e"), "#3b2400", "#fff2b8",
                 _FORTUNE_BTN_GRAD.format(a="#fff0b0", b="#e8b542")),
        "spin_dis": ("#6b5a3a", "#2a1d08", "#8a7a52"),
        "check": "#d8c8f8", "spin_glow": None, "select_fg": "#ffffff", "edit_fg": "#ffffff",
        "title_text": "✦  КОЛЕСО ФОРТУНЫ  ✦", "win_top": "ВЫПАЛО", "win_sub": "Госпожа решила твою судьбу",
        "intro_text": FORTUNE_INTRO_TEXT,
        "win": {"bg": ("#3c2466", "#1a1030"), "border": "#ffe27a", "top": "#ffd98a", "text": "#ffffff",
                "sub": "#ffe27a", "btn_bg": "#d9a52e", "btn_fg": "#3b2400", "btn_border": "#fff2b8",
                "btn_hover": "#f0be48"},
        "wheel": {"colors": FORTUNE_COLORS, "edge": (30, 20, 50, 200), "aura": (255, 210, 110),
                  "rim": "#d9b45a", "rim2": None, "neon": False, "peg": ("#fff6cf", "#b8892a"),
                  "hub": ("#fff2b8", "#b8892a", "#6b4a14"), "star": "#6b4a14",
                  "ptr": ("#ffcf4a", "#4a2a00", "#fff2b8"), "win": (255, 240, 160), "win_edge": (255, 226, 122),
                  "text_dark": "#1b1230", "text_light": "#ffffff",
                  "rim_glow": None, "rim_w": 0.045, "hub_pen": 1.0, "ptr_glow": None, "ptr_sharp": False,
                  "blossom": False, "petals": False},
    },
    "nte": {                                              # глубокий ночной фиолет, неоновый циан и розовый
        "bg": ("#0d0c1d", "#1a1233"),
        "card": ("rgba(25, 20, 45, 217)", "rgba(35, 24, 64, 217)"), "card_border": "#00f0ff",
        "title": "#00f0ff", "intro": "#e6ecff",
        "panel_bg": "rgba(25, 20, 45, 217)", "panel_border": "#ff2a8d",
        "head": "#ff4fa3", "hint": "#8fa4d8",
        "list_bg": "rgba(13, 12, 29, 200)", "list_fg": "#e6f7ff", "field_border": "#00b8cc", "select": "#ff2a8d",
        "btn_bg": "#1c1740", "btn_fg": "#d9f7ff", "btn_border": "#00f0ff", "btn_hover": "#2a2262",
        "btn_dis": ("#6f7aa8", "#161230", "#2a3a6a"),
        "spin": ("qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #00f0ff, stop:1 #ff2a8d)", "#0d0c1d", "#ffffff",
                 "qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #6ff7ff, stop:1 #ff6fb2)"),
        "spin_dis": ("#2b2a4a", "#6f7aa8", "#3a3a6a"),
        "check": "#9fe9ff", "spin_glow": "#00f0ff", "select_fg": "#ffffff", "edit_fg": "#ffffff",
        "title_text": "✦ NTE FORTUNE WHEEL ✦", "win_top": "✦ ВЫПАЛО ✦", "win_sub": "✦ ГОСПОЖА РЕШИЛА ТВОЮ СУДЬБУ ✦",
        "intro_text": FORTUNE_INTRO_TEXT_NTE,
        "win": {"bg": ("rgba(25, 20, 45, 235)", "rgba(40, 20, 70, 235)"), "border": "#00f0ff", "top": "#ff4fa3",
                "text": "#ffffff", "sub": "#00f0ff", "btn_bg": "#ff2a8d", "btn_fg": "#ffffff",
                "btn_border": "#00f0ff", "btn_hover": "#ff5fa8"},
        "wheel": {"colors": ("#00e5ff", "#ff2a8d", "#9b5cff", "#ffc83d", "#2b3a6b"), "edge": (13, 12, 29, 230),
                  "aura": (0, 240, 255), "rim": "#00f0ff", "rim2": "#ff2a8d", "neon": True,
                  "peg": ("#eaffff", "#00a8c8"), "hub": ("#2a2062", "#0d0c1d", "#00f0ff"), "star": "#ff2a8d",
                  "ptr": ("#ff2a8d", "#00f0ff", "#ffffff"), "win": (0, 240, 255), "win_edge": (255, 42, 141),
                  "text_dark": "#0d0c1d", "text_light": "#ffffff",
                  "rim_glow": "#00f0ff", "rim_w": 0.032, "hub_pen": 1.6, "ptr_glow": "#00f0ff", "ptr_sharp": True,
                  "blossom": False, "petals": False},
    },
    "sakura": {                                           # японская эстетика: нежно-розовый, слоновая кость, багрянец и золото
        "bg": ("#fff0f5", "#fadadd"),
        "card": ("rgba(255, 255, 255, 215)", "rgba(255, 226, 234, 215)"), "card_border": "#e6ca65",
        "title": "#dc143c", "intro": "#6b2a3c",
        "panel_bg": "rgba(255, 255, 255, 175)", "panel_border": "#ffb7c5",
        "head": "#dc143c", "hint": "#9a6a78",
        "list_bg": "rgba(255, 255, 255, 225)", "list_fg": "#4a2630", "field_border": "#ffb7c5", "select": "#ffb7c5",
        "btn_bg": "#ffdbe4", "btn_fg": "#7a1230", "btn_border": "#ffb7c5", "btn_hover": "#ffc4d2",
        "btn_dis": ("#b79aa3", "#fbe9ee", "#f1cdd6"),
        "spin": ("qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ff8aa5, stop:1 #dc143c)", "#ffffff", "#e6ca65",
                 "qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffa3b8, stop:1 #e8405e)"),
        "spin_dis": ("#efc9d2", "#a47c86", "#e6ca65"),
        "check": "#7a1230", "spin_glow": "#ff8fa8", "select_fg": "#4a1020", "edit_fg": "#4a2630",
        "title_text": "✿  КОЛЕСО ФОРТУНЫ  ✿", "win_top": "✦ СУДЬБА ОПУСТИЛАСЬ КАК ЛЕПЕСТОК САКУРЫ ✦",
        "win_sub": "Госпожа решила твою судьбу",
        "intro_text": FORTUNE_INTRO_TEXT_SAKURA,
        "win": {"bg": ("#fff9fb", "#ffdce5"), "border": "#e6ca65", "top": "#dc143c", "text": "#4a1020",
                "sub": "#a8324d", "btn_bg": "#dc143c", "btn_fg": "#ffffff", "btn_border": "#e6ca65",
                "btn_hover": "#e8405e"},
        "wheel": {"colors": ("#ffb7c5", "#d63a5c", "#fff6ea", "#ffc9a8", "#e6ca65", "#b8735c"),
                  "edge": (255, 255, 255, 235), "aura": (255, 183, 197), "rim": "#e6ca65", "rim2": "#dc143c",
                  "neon": False, "peg": ("#fff6ea", "#e6ca65"), "hub": ("#fff6ea", "#ffb7c5", "#e6ca65"),
                  "star": "#dc143c", "ptr": ("#dc143c", "#e6ca65", "#fff6ea"), "win": (255, 255, 255),
                  "win_edge": (220, 20, 60), "text_dark": "#4a1020", "text_light": "#ffffff",
                  "rim_glow": "#ff8fa8", "rim_w": 0.04, "hub_pen": 1.3, "ptr_glow": "#ff8fa8", "ptr_sharp": True,
                  "blossom": True, "petals": True},
    },
    "paws": {                                             # «Белые лапки»: уютный дом, кремовое молоко, персик и тёплый шоколад
        "bg": ("#fdfbf7", "#f4ecd8"),
        "card": ("rgba(255, 252, 245, 220)", "rgba(244, 236, 216, 220)"), "card_border": "#d9c3a9",
        "title": "#8b5e3c", "intro": "#6b4a32",
        "panel_bg": "rgba(255, 251, 243, 185)", "panel_border": "#e6b89c",
        "head": "#9a6a44", "hint": "#a38a74",
        "list_bg": "rgba(255, 252, 246, 230)", "list_fg": "#4a3220", "field_border": "#d9c3a9", "select": "#e6b89c",
        "btn_bg": "#f4ecd8", "btn_fg": "#6b4528", "btn_border": "#d9c3a9", "btn_hover": "#f0dfc2",
        "btn_dis": ("#b5a28c", "#f6eee0", "#e8dcc6"),
        "spin": (_FORTUNE_BTN_GRAD.format(a="#f8d3b0", b="#e0a068"), "#4a2a12", "#fff3d6",
                 _FORTUNE_BTN_GRAD.format(a="#fbdfc3", b="#e8b07a")),
        "spin_dis": ("#ece0cb", "#a89580", "#d9c3a9"),
        "check": "#7a5334", "spin_glow": "#f0b98a", "select_fg": "#4a2a12", "edit_fg": "#4a3220",
        "title_text": "🐾  КОЛЕСО ФОРТУНЫ  🐾", "win_top": "✦ МИЛАЯ ЛАПКА РЕШИЛА ТВОЮ СУДЬБУ ✦",
        "win_sub": "Госпожа решила твою судьбу",
        "intro_text": FORTUNE_INTRO_TEXT_PAWS,
        "win": {"bg": ("#fffdf8", "#f6e6cf"), "border": "#d9a86a", "top": "#b9794a", "text": "#4a2e1a",
                "sub": "#9a6a44", "btn_bg": "#e6b89c", "btn_fg": "#4a2a12", "btn_border": "#fff3d6",
                "btn_hover": "#efc9ae"},
        "wheel": {"colors": ("#f7d9c4", "#e8b04f", "#fff6e6", "#8b5e3c", "#e6b89c", "#d9c3a9", "#f4ecd8", "#b9794a"),
                  "edge": (253, 251, 247, 240), "aura": (240, 200, 160), "rim": "#c9a27a", "rim2": "#e6b89c",
                  "neon": False, "peg": ("#fff6e6", "#d9c3a9"), "hub": ("#fff6e6", "#f4d9c2", "#c9a27a"),
                  "star": "#8b5e3c", "ptr": ("#e0a95a", "#6b4423", "#fff3d6"), "win": (255, 240, 200),
                  "win_edge": (184, 115, 70), "text_dark": "#4a2e1a", "text_light": "#fffaf0",
                  "rim_glow": "#f0c9a0", "rim_w": 0.042, "hub_pen": 1.3, "ptr_glow": "#f0c9a0", "ptr_sharp": False,
                  "blossom": False, "petals": False, "paws": True, "dim": (120, 84, 52, 105)},
    },
}
