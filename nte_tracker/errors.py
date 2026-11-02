"""Исключения приложения."""

from contextlib import contextmanager


class DatabaseError(Exception):
    """Ошибка работы с базой данных (с понятным текстом для пользователя)."""



class OcrError(Exception):
    """Ошибка распознавания скриншота (с понятным текстом для пользователя)."""



@contextmanager
def blocked(*widgets):
    """Временно отключает сигналы виджетов. Используется при программном
    изменении полей формы, чтобы не запускать лишние пересчёты предпросмотра."""
    for w in widgets:
        w.blockSignals(True)
    try:
        yield
    finally:
        for w in widgets:
            w.blockSignals(False)
