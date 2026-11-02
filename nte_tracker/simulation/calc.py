"""Расчёты вкладки «Симуляция»: характеристики, возвышение, защита, сопротивление."""

import json

from ..catalog import ICON_DIR_NAMES, ICON_EXTS
from ..icons import _name_variants, find_icon_path
from ..paths import asset_dirs, search_roots


# ----------------------------------------------------------------------------
# НОВОЕ: вкладка «Симуляция» — рост характеристик, возвышение, защита и сопротивление врага
# ----------------------------------------------------------------------------
SIM_ELEMENTS = ("Космос", "Лакшана", "Анима", "Хаос", "Инкантация", "Психея")



SIM_JSON_NAME = "simulation_data.json"      # необязательный файл: свои базовые статы



SIM_PORTRAIT_DIRS = ("portraits", "full", "art")



SIM_PORTRAIT_SUFFIXES = ("", "_full", "_portrait", "_art", "_splash", "-full", "-portrait", "-art")



SIM_FLAT_STEP = 50.0                        # шаг для плоской АТК в таблице весов



SIM_SETTING_CHAR, SIM_SETTING_ARC = "sim_character", "sim_weapon"



SIM_NO_WEAPON = "Без дуги"



# --- модель прогрессии (nte_character_progression.md) ---
SIM_MAX_LEVEL = 80



SIM_ASC_LEVELS = (40, 50, 60, 70)           # пороги возвышения



SIM_BETAS = (0.12, 0.14, 0.16, 0.18)        # скачок характеристик на i-м возвышении



SIM_HIDDEN_BONUS = 12.0                     # скрытый бонус S-ранга, % за этап



SIM_HIDDEN_STAGES = (2, 4)                  # этапы возвышения, открывающие скрытый бонус



SIM_BASE_CRIT, SIM_BASE_CRIT_DMG = 5.0, 50.0



SIM_BASE_STAMINA, SIM_BASE_REGEN = 240, 100



# фазы возвышения (nte_complete_math_guide.md): (фаза, характеристика, бонус %), накопительно
SIM_PHASE_AFFIXES = ((2, "element_dmg", 8.0), (4, "crit_dmg", 12.0), (6, "dmg", 10.0))



SIM_PHASE_NAMES = {"element_dmg": "стихийный урон", "crit_dmg": "крит. урон", "dmg": "общий урон"}



SIM_HIDDEN_KINDS = (("Стихийный урон", "element_dmg"), ("Шанс крита", "crit"))



# роль: (название, K_hp, K_atk, K_def, приоритетный скрытый стат)
SIM_ROLES = {
    "dps": ("Основной урон", 1.0, 1.4, 0.8, "Крит. урон / Стихийный урон"),
    "sub": ("Саб-урон / энейблер", 1.1, 1.2, 0.9, "Скорость восполнения энергии"),
    "support": ("Поддержка / бафер", 1.2, 0.9, 1.1, "Общий процентный урон %"),
    "tank": ("Танк / щитовик", 1.5, 0.7, 1.4, "Эффективность щита / Защита %"),
}



SIM_ROLE_BY_NAME = {"Наналли": "dps", "Лакримоза": "dps", "Шинку": "sub", "Минт": "support",
                    "Адлер": "support", "Фадия": "tank", "Хатор": "tank"}



# Значения на 1-м уровне по рангу (если нет данных в simulation_data.json).
SIM_CHAR_DEFAULTS = {
    5: {"element": "Космос", "hidden": "element_dmg", "hp": 800.0, "atk": 120.0, "def": 70.0,
        "alpha": 0.05, "gamma": 0.97, "dmg": 0.0},
    4: {"element": "Космос", "hidden": "element_dmg", "hp": 700.0, "atk": 100.0, "def": 60.0,
        "alpha": 0.05, "gamma": 0.97, "dmg": 0.0},
}



SIM_WEAPON_DEFAULTS = {
    5: {"atk": 100.0, "alpha": 0.05, "gamma": 0.97, "atk_pct": 20.0, "crit": 0.0, "crit_dmg": 0.0,
        "dmg": 0.0, "element_dmg": 0.0},
    4: {"atk": 80.0, "alpha": 0.05, "gamma": 0.97, "atk_pct": 12.0, "crit": 0.0, "crit_dmg": 0.0,
        "dmg": 0.0, "element_dmg": 0.0},
    3: {"atk": 60.0, "alpha": 0.05, "gamma": 0.97, "atk_pct": 8.0, "crit": 0.0, "crit_dmg": 0.0,
        "dmg": 0.0, "element_dmg": 0.0},
}



# (ключ, подпись, минимум, максимум, знаков, шаг, значение по умолчанию, суффикс, группа)
SIM_FIELDS = (
    ("level", "Уровень персонажа (L)", 1, 80, 0, 1, 80, "", "char"),
    ("ascension", "Ранг возвышения (A)", 0, 4, 0, 1, 4, "", "char"),
    ("weapon_level", "Уровень дуги (L_орк)", 1, 80, 0, 1, 80, "", "char"),
    ("phase", "Фаза возвышения (аффиксы 2/4/6)", 0, 6, 0, 1, 0, "", "char"),
    ("skill", "% навыка (базовый)", 0, 20000, 1, 5, 100, " %", "char"),
    ("skill_level", "Уровень навыка (L_skill)", 1, 20, 0, 1, 1, "", "char"),
    ("skill_k", "Рост навыка K_skill", 0, 50, 1, 0.5, 6.5, " % за ур.", "char"),
    ("atk_pct", "АТК % (модули)", 0, 2000, 1, 1, 0, " %", "char"),
    ("atk_flat", "АТК плоская (модули)", 0, 99999, 0, 10, 0, "", "char"),
    ("dmg", "Общий урон % (модули)", 0, 2000, 1, 1, 0, " %", "char"),
    ("element_dmg", "Урон стихии % (модули)", 0, 2000, 1, 1, 0, " %", "char"),
    ("crit", "Шанс крита % (модули)", 0, 100, 1, 1, 0, " %", "char"),
    ("crit_dmg", "Крит. урон % (модули)", 0, 2000, 1, 1, 0, " %", "char"),
    ("enemy_level", "Уровень врага", 1, 200, 0, 1, 80, "", "enemy"),
    ("resist", "Базовый резист врага %", -100, 200, 1, 1, 10, " %", "enemy"),
    ("shred", "Срез резиста %", 0, 200, 1, 1, 0, " %", "enemy"),
    ("def_shred", "Срез защиты врага %", 0, 100, 1, 1, 0, " %", "enemy"),
    ("def_ignore", "Игнор защиты %", 0, 100, 1, 1, 0, " %", "enemy"),
    ("under_level", "Уровень отстающего персонажа", 1, 80, 0, 1, 60, "", "scenario"),
    ("boss_level", "Уровень эндгейм-босса", 1, 200, 0, 1, 90, "", "scenario"),
)



# ползунки рядом с полями: ключ -> (минимум, максимум, шаг)
SIM_SLIDERS = {"level": (1, 80, 1), "ascension": (0, 4, 1), "weapon_level": (1, 80, 1),
               "phase": (0, 6, 1), "skill_level": (1, 20, 1),
               "skill": (0, 2000, 5), "enemy_level": (1, 200, 1)}



SIM_STYLE = """
QDoubleSpinBox { background-color: rgba(8, 10, 24, 150); border: 1px solid rgba(255, 255, 255, 45);
                 border-radius: 8px; padding: 4px 8px; min-width: 96px; }
QDoubleSpinBox:focus { border-color: #ffd740; }
QFrame#simPortrait { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                     stop:0 rgba(255, 255, 255, 26), stop:1 rgba(255, 255, 255, 8));
                     border: 1px solid rgba(255, 255, 255, 50); border-radius: 16px; }
QLabel#simName { font-size: 22px; font-weight: bold; color: #ffd740; }
QLabel#simSub { color: #b4b9c9; font-size: 13px; }
QLabel#simHint { color: #b4b9c9; font-size: 12px; }
QLabel#simIdeal { font-size: 14px; font-weight: bold; }
QSlider::groove:horizontal { height: 6px; border-radius: 3px; background: rgba(255, 255, 255, 40); }
QSlider::sub-page:horizontal { border-radius: 3px; background: rgba(255, 215, 64, 200); }
QSlider::handle:horizontal { width: 16px; margin: -6px 0; border-radius: 8px; background: #ffd740; }
"""



def _sim_clamp(value, lo, hi):
    return max(lo, min(hi, value))



def sim_required_ascension(level: int) -> int:
    """Минимальный ранг возвышения, нужный для достижения уровня L."""
    return sum(1 for t in SIM_ASC_LEVELS if level > t)



def sim_level_cap(asc: int) -> int:
    """Максимальный уровень при ранге возвышения A (40 / 50 / 60 / 70 / 80)."""
    return SIM_ASC_LEVELS[asc] if asc < len(SIM_ASC_LEVELS) else SIM_MAX_LEVEL



def sim_stat_at_level(stat1: float, alpha: float, gamma: float, level: float, asc: int,
                      betas=SIM_BETAS) -> float:
    """Stat_база(L) = Stat_ур.1 × (1 + α × (L − 1)^γ) + ΔStat_возв,
    ΔStat_возв = Σ(Stat_ур.1 × β_i) для i = 1..A."""
    level = _sim_clamp(level, 1, SIM_MAX_LEVEL)
    asc = int(_sim_clamp(asc, 0, len(SIM_ASC_LEVELS)))
    growth = stat1 * (1 + alpha * (level - 1) ** gamma)
    return growth + sum(stat1 * b for b in betas[:asc])



def sim_hidden_bonus(asc: int, rank: int) -> float:
    """Скрытый бонус возвышения: только S-ранг, +12 % на 2-м и 4-м этапах (накопительно)."""
    if rank < 5:
        return 0.0
    return SIM_HIDDEN_BONUS * sum(1 for s in SIM_HIDDEN_STAGES if asc >= s)



def sim_character_stats(prof: dict, role: str, level: int, asc: int) -> dict:
    """HP / АТК / ЗАЩ персонажа на уровне L: Stat_итого = Stat_база(L) × K_роль."""
    _name, k_hp, k_atk, k_def, _hidden = SIM_ROLES.get(role, SIM_ROLES["dps"])
    betas = prof.get("betas")
    if not (isinstance(betas, (list, tuple)) and len(betas) >= len(SIM_BETAS)):
        betas = SIM_BETAS
    out = {}
    for key, k in (("hp", k_hp), ("atk", k_atk), ("def", k_def)):
        out[key] = sim_stat_at_level(prof[key], prof["alpha"], prof["gamma"], level, asc, betas) * k
    return out



def sim_weapon_atk(wp: dict, level: int) -> float:
    """АТК дуги на уровне L_орк (без возвышений)."""
    return sim_stat_at_level(wp["atk"], wp["alpha"], wp["gamma"], level, 0)



def sim_skill_ratio(base_ratio: float, k_skill: float, skill_level: float) -> float:
    """Skill_Ratio(L_skill) = Skill_Ratio_base × (1 + K_skill × (L_skill − 1)), K в процентах."""
    return base_ratio * (1 + k_skill / 100.0 * (max(1.0, skill_level) - 1))



def sim_phase_bonuses(phase: int) -> dict:
    """Аффиксы фаз возвышения 2 / 4 / 6: +8 % стихии, +12 % крит. урона, +10 % общего урона."""
    out = {"element_dmg": 0.0, "crit_dmg": 0.0, "dmg": 0.0}
    for need, key, value in SIM_PHASE_AFFIXES:
        if phase >= need:
            out[key] += value
    return out



def sim_defense_multiplier(char_level, enemy_level, def_shred=0.0, def_ignore=0.0) -> float:
    """(L + 100) / (L + 100 + (Lвр + 100) × (1 − срез/игнор))."""
    reduction = _sim_clamp((def_shred + def_ignore) / 100.0, 0.0, 1.0)
    numerator = char_level + 100.0
    return numerator / (numerator + (enemy_level + 100.0) * (1.0 - reduction))



def sim_resist_multiplier(resist, shred) -> float:
    """Сопротивление врага с порогами: ≥ 75 % — 1/(1 + 4x), < 0 — 1 − x/2, иначе 1 − x."""
    x = (resist - shred) / 100.0
    if x >= 0.75:
        return 1.0 / (1.0 + x * 4.0)
    if x < 0:
        return 1.0 - x / 2.0
    return 1.0 - x



def sim_calculate(p: dict) -> dict:
    """Мультипликативная модель урона NTE (формулы из документов)."""
    atk = p["atk_base"] * (1 + p["atk_pct"] / 100) + p["atk_flat"]
    base = atk * p["skill"] / 100
    with_bonus = base * (1 + (p["dmg"] + p["element_dmg"]) / 100)
    crit_rate = _sim_clamp(p["crit"], 0.0, 100.0)
    crit_mult = 1 + (crit_rate / 100) * (p["crit_dmg"] / 100)
    average = with_bonus * crit_mult
    resist_factor = sim_resist_multiplier(p["resist"], p["shred"])
    defense_factor = sim_defense_multiplier(p["level"], p["enemy_level"],
                                            p.get("def_shred", 0.0), p.get("def_ignore", 0.0))
    mitigation = resist_factor * defense_factor
    return {
        "atk": atk, "base": base, "with_bonus": with_bonus, "crit_mult": crit_mult,
        "average": average, "resist_factor": resist_factor, "defense_factor": defense_factor,
        "final": average * mitigation,
        "crit_hit": with_bonus * (1 + p["crit_dmg"] / 100) * mitigation,
        "crit_value": 2 * p["crit"] + p["crit_dmg"],
        "ideal_crit": min(100.0, p["crit_dmg"] / 2),
    }



def sim_marginal(p: dict, step: float) -> dict:
    """Прирост по формулам из документа: АТК % и стихия (в процентах)."""
    atk_gain = step / (100 + p["atk_pct"]) * 100
    elem_gain = step / (100 + p["dmg"] + p["element_dmg"]) * 100
    return {"atk": atk_gain, "element": elem_gain}



def sim_stat_weights(p: dict, step: float) -> list:
    """Реальный прирост итогового урона от добавки к каждой характеристике.
    Возвращает [(подпись, шаг, прирост %, вес относительно АТК %)]."""
    base_final = sim_calculate(p)["final"]
    stats = (("atk_pct", "АТК %", step), ("atk_flat", "АТК плоская", SIM_FLAT_STEP),
             ("element_dmg", "Урон стихии %", step), ("dmg", "Общий урон %", step),
             ("crit", "Шанс крита %", step), ("crit_dmg", "Крит. урон %", step),
             ("shred", "Срез резиста %", step), ("def_shred", "Срез защиты %", step))
    gains = []
    for key, label, delta in stats:
        q = dict(p)
        q[key] = q.get(key, 0.0) + delta
        gain = (sim_calculate(q)["final"] / base_final - 1) * 100 if base_final > 0 else 0.0
        gains.append((label, delta, gain))
    ref = gains[0][2]
    return [(label, delta, gain, (gain / ref if ref > 0 else 0.0)) for label, delta, gain in gains]



def sim_load_overrides() -> dict:
    """Читает simulation_data.json (рядом с main.py, в assets/ или рядом с базой).
    Любая ошибка файла игнорируется."""
    roots = search_roots()
    for root in roots:
        for path in (root / SIM_JSON_NAME, root / "assets" / SIM_JSON_NAME):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                return data
    return {}



def find_portrait_path(name: str):
    """Ищет арт персонажа в полный рост: portraits/, full/, art/ (и файлы с суффиксами
    _full, _portrait, _art), затем обычную иконку. Возвращает Path или None."""
    roots = search_roots()
    portrait_dirs = [root / base / sub for root in roots for base in ICON_DIR_NAMES
                     for sub in SIM_PORTRAIT_DIRS]
    variants = _name_variants(name)
    for dirs, suffixes in ((portrait_dirs, SIM_PORTRAIT_SUFFIXES),
                           (asset_dirs(), SIM_PORTRAIT_SUFFIXES[1:])):
        for d in dirs:
            if not d.is_dir():
                continue
            for v in variants:
                for s in suffixes:
                    for ext in ICON_EXTS:
                        f = d / (v + s + ext)
                        if f.is_file():
                            return f
    return find_icon_path(name)
