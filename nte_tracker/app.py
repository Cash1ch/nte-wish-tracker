"""Точка входа: создание QApplication, базы данных и главного окна."""

import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication, QMessageBox

from .database import Database
from .errors import DatabaseError
from .mainwindow.window import MainWindow
from .paths import resolve_db_path, set_data_dir
from .ui.profile_dialog import ensure_profile
from .ui.theme import apply_app_style


# ----------------------------------------------------------------------------
# Точка входа
# ----------------------------------------------------------------------------
WEBENGINE_GPU_RASTER = True      # НОВОЕ: False — вернуть программную растеризацию встроенной карты



def main() -> int:
    # НОВОЕ: дробный масштаб экрана (125 %, 150 %) используется как есть, без округления
    # до целого — иначе Qt растягивает картинки и они теряют чёткость.
    # Вызывать нужно ДО создания QApplication.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    # ИЗМЕНЕНО: растеризация плиток карты на видеокарте. Программная (--disable-gpu-rasterization)
    # не успевает перерисовывать плитки при движении мыши и добавлении метки — вместо них на
    # мгновение видны тёмные квадраты. Если на вашей видеокарте появятся артефакты, поставьте
    # WEBENGINE_GPU_RASTER = False — вернётся прежний режим.
    _flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if WEBENGINE_GPU_RASTER:
        _extra = " --enable-gpu-rasterization --ignore-gpu-blocklist"
    else:
        _extra = " --disable-gpu-rasterization"
    if "gpu-rasterization" not in _flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (_flags + _extra).strip()
    app = QApplication(sys.argv)
    apply_app_style(app)     # ИЗМЕНЕНО: STYLE (+ плотные «стёкла», если есть фон)

    try:
        db = Database(resolve_db_path())
    except (DatabaseError, OSError) as e:
        QMessageBox.critical(None, "Ошибка", str(e))
        return 1

    set_data_dir(db.path.parent)  # нужно поиску иконок и музыки (assets рядом с базой)
    apply_app_style(app)        # фон мог лежать рядом с базой, а не со скриптом
    if not ensure_profile(db):  # НОВОЕ: первый запуск — окно «Введите ваш никнейм»
        db.close()
        return 0
    win = MainWindow(db)
    win.show()
    code = app.exec()
    db.close()
    return code
