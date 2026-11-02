"""Проверка окружения: версии Qt совпадают и QtWebEngine загружается. Запуск: python tools/check_webengine.py"""
import sys
from importlib import metadata

names = ["PyQt6", "PyQt6-Qt6", "PyQt6-WebEngine", "PyQt6-WebEngine-Qt6"]
vers = {}
for n in names:
    try:
        vers[n] = metadata.version(n)
    except metadata.PackageNotFoundError:
        vers[n] = None
for n, v in vers.items():
    print(f"{n:22} {v}")

missing = [n for n, v in vers.items() if v is None]
if missing:
    sys.exit(f"ОШИБКА: не установлены {missing}")
lines = {".".join(v.split(".")[:2]) for v in vers.values()}
if len(lines) != 1:
    sys.exit(f"ОШИБКА: версии Qt-пакетов из разных линеек: {sorted(lines)}. Используйте requirements.txt")

from PyQt6.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
print("Qt", QT_VERSION_STR, "| PyQt", PYQT_VERSION_STR)
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
from PyQt6.QtWebEngineCore import QWebEngineProfile  # noqa: F401
print("QtWebEngine: OK")
