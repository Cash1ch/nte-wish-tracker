"""Работа с путями: папка программы, база данных, поиск ресурсов и музыки."""

import shutil
import sys
from pathlib import Path

from .catalog import ICON_DIR_NAMES, ICON_SUBDIRS
from .config import DB_NAME, MUSIC_EXTS, MUSIC_FILE


# ----------------------------------------------------------------------------
# Работа с путями
# ----------------------------------------------------------------------------
_DATA_DIR = None  # папка с базой данных (задаётся в main), тоже ищем в ней иконки


def set_data_dir(path) -> None:
    """Запоминает папку базы данных: иконки и музыку ищем и в ней тоже."""
    global _DATA_DIR
    _DATA_DIR = path


def search_roots() -> list:
    """Папки, где ищутся ресурсы: рядом с программой и рядом с базой данных."""
    return [app_dir()] + ([Path(_DATA_DIR)] if _DATA_DIR is not None else [])



def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent   # корень проекта (рядом с main.py)



def resolve_db_path() -> Path:
    base = app_dir()
    try:
        test = base / ".write_test"
        test.touch()
        test.unlink()
        return base / DB_NAME
    except OSError:
        fallback = Path.home() / "NTE Wish Tracker"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback / DB_NAME



def asset_dirs() -> list:
    """ИЗМЕНЕНО: помимо assets/ и icons/ просматриваются и подпапки из ICON_SUBDIRS
    (characters/, arcs/, items/)."""
    roots = search_roots()
    dirs = []
    for root in roots:
        for name in ICON_DIR_NAMES:
            for sub in ICON_SUBDIRS:
                d = root / name / sub if sub else root / name
                if d not in dirs:
                    dirs.append(d)
    return dirs



def find_music_file():
    """НОВОЕ: ищет файл фоновой музыки. Сначала берётся MUSIC_FILE как есть, затем
    файл с тем же именем и любым расширением из MUSIC_EXTS. Ищем рядом со скриптом и
    рядом с базой данных. Возвращает Path или None, если файла нет."""
    rel = Path(MUSIC_FILE)
    roots = search_roots()
    for root in roots:
        base = root / rel
        names = [base] + [base.with_suffix(ext) for ext in MUSIC_EXTS]
        for p in names:
            try:
                if p.is_file():
                    return p
            except OSError:
                continue
    return None


TESSERACT_DIR_NAMES = ("Tesseract-OCR", "tesseract", "Tesseract")
TESSERACT_SYSTEM_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def find_tesseract():
    """Ищет программу Tesseract OCR. Порядок поиска:
    1) папка Tesseract-OCR рядом с программой или рядом с базой данных (встроенная поставка);
    2) стандартные папки установки на Windows;
    3) переменная PATH.
    Возвращает Path или None, если Tesseract не найден."""
    exe_names = ("tesseract.exe", "tesseract")
    for root in search_roots():
        for folder in TESSERACT_DIR_NAMES:
            for exe in exe_names:
                p = root / folder / exe
                try:
                    if p.is_file():
                        return p
                except OSError:
                    continue
    for raw in TESSERACT_SYSTEM_PATHS:
        p = Path(raw)
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    found = shutil.which("tesseract")
    return Path(found) if found else None

