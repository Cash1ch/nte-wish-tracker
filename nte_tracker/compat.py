"""Необязательные зависимости (QtMultimedia, requests, Pillow, pytesseract, OpenCV, NumPy).
Модуль подключается «мягко»: если пакета нет, соответствующее имя равно None."""

import urllib.request  # noqa: F401  (нужен для urllib.request.urlopen в других модулях)

# НОВОЕ: музыка. QtMultimedia подключается «мягко»: если модуля нет (урезанная сборка
# PyQt6 или не хватает системных библиотек), приложение всё равно запустится —
# просто без фоновой музыки, а панель громкости будет неактивна.
try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
except ImportError:
    QAudioOutput = QMediaPlayer = None

try:
    from PyQt6.QtMultimedia import QAudio  # нужен для «естественной» шкалы громкости
except ImportError:
    QAudio = None

# НОВОЕ: звуки «Колеса Фортуны» (тики, шум вращения, фон, победа) — QSoundEffect, тоже «мягко»
try:
    from PyQt6.QtMultimedia import QSoundEffect
except ImportError:
    QSoundEffect = None

# НОВОЕ: requests — для запроса текущего баннера. Подключается «мягко»: если пакета нет,
# BannerFetchThread использует стандартный urllib, поэтому приложение запустится в любом случае.
try:
    import requests
except ImportError:
    requests = None

try:  # QtWebEngine нужно импортировать ДО создания QApplication (встроенная карта)
    from PyQt6.QtWebEngineWidgets import QWebEngineView as _QWebEngineViewProbe  # noqa: F401
except Exception:
    pass

# Pillow нужен для анализа цвета рамки/фона и подготовки скриншота к OCR,
# pytesseract — для распознавания текста. Оба необязательны: без них остальное
# приложение работает как обычно.
try:
    from PIL import Image, ImageChops, ImageOps, ImageStat
except ImportError:
    Image = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

# НОВОЕ: OpenCV + NumPy — для продвинутой предобработки скриншота перед OCR (увеличение,
# CLAHE, бинаризация, морфология). Необязательны: без них работает упрощённый вариант на Pillow.
try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

# Если пакет не установлен, соответствующее имя остаётся None (как в исходной программе).
for _name in ("Image", "ImageChops", "ImageOps", "ImageStat", "pytesseract", "cv2", "np", "requests",
              "QAudioOutput", "QMediaPlayer", "QAudio", "QSoundEffect"):
    globals().setdefault(_name, None)
del _name

