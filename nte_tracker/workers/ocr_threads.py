"""Потоки OCR: одиночный, пакетный и массовый."""

import gc
import re
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, QThread

from ..errors import OcrError
from ..ocr.pipeline import run_ocr_pipeline


class OcrThread(QThread):
    """НОВОЕ: распознаёт скриншот в ФОНОВОМ потоке, чтобы окно не зависало.

    Сигналы:
      done(object, object, object) — успех: строки OCR (после фильтра служебных строк),
                                     ранги по цвету значка для каждой строки, общий ранг (None);
      failed(str)                  — понятный текст ошибки для пользователя.
    Поток сам не трогает интерфейс: только считает и отправляет результат сигналом."""
    done = pyqtSignal(object, object, object)
    failed = pyqtSignal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        try:
            res = run_ocr_pipeline(self.path)     # единый конвейер (как и в пакетной вкладке)
        except OcrError as e:
            self.failed.emit(str(e))
            return
        except Exception as e:  # любая неожиданная ошибка — сообщением, а не падением потока
            self.failed.emit(f"Ошибка распознавания:\n{e}")
            return
        self.done.emit(res["lines"], res["ranks"], res["glob"])



# ---- НОВОЕ: пакетное распознавание («Скриншот оптом») ----
BATCH_MAX_FILES = 10                              # не больше стольких скриншотов за раз



BATCH_EXTS = (".jpg", ".jpeg", ".png", ".bmp")    # допустимые форматы



_LIVE_BATCH_THREADS = set()                       # потоки, пережившие закрытие окна



class BatchOcrThread(QThread):
    """НОВОЕ: распознаёт несколько скриншотов ПОДРЯД в одном фоновом потоке (окно не
    зависает; Tesseract не запускается параллельно). Для каждого файла выполняются те же
    шаги, что и в одиночной вкладке «Скриншот» (OcrThread): ocr_image -> filter_ocr_lines ->
    detect_rarity_colors. Разбор текста в записи делает окно (ocr_extract_pulls) — так тип
    безымянных строк можно пересчитать при смене баннера без повторного OCR.

    Сигналы:
      progress(int, int)               — начинается файл номер i (с нуля) из total;
      file_done(int, str, object, object) — файл i готов: текст, ранги по цвету, общий ранг;
      file_failed(int, str)            — файл i не распознан (понятный текст ошибки).
    Отмена: requestInterruption() — поток остановится после текущего файла."""
    progress = pyqtSignal(int, int)
    file_done = pyqtSignal(int, str, object, object, object)   # + уверенность по строкам
    file_failed = pyqtSignal(int, str)

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.paths = list(paths)

    def run(self):
        total = len(self.paths)
        for i, path in enumerate(self.paths):
            if self.isInterruptionRequested():
                break
            self.progress.emit(i, total)
            try:
                res = run_ocr_pipeline(path)      # тот же конвейер, что и в одиночной вкладке
            except OcrError as e:
                self.file_failed.emit(i, str(e))
                continue
            except Exception as e:  # noqa: BLE001 — один плохой файл не должен ронять весь пакет
                self.file_failed.emit(i, f"Ошибка распознавания:\n{e}")
                continue
            self.file_done.emit(i, res["text"], res["ranks"], res["glob"], res.get("confs"))



def natural_key(path) -> list:
    """Ключ «естественной» сортировки имён файлов: shot2.png идёт раньше shot10.png."""
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", Path(path).name)]



# ---- НОВОЕ: «Скриншоты разом» — массовая обработка (100–200+ файлов) ----
MASS_GC_EVERY = 8          # как часто (в файлах) принудительно вызывать сборщик мусора



MASS_UI_SLICE_S = 0.025    # сколько секунд подряд работает «порция» разбора/построения списка в окне



MASS_LIST_ROWS = 10        # минимальная высота общего списка (строк без прокрутки)



class MassOcrThread(BatchOcrThread):
    """НОВОЕ: фоновый поток вкладки «Скриншоты разом». Те же сигналы и тот же конвейер
    (run_ocr_pipeline), что у BatchOcrThread, но с заботой о памяти: файлы идут СТРОГО по
    одному, результат каждого файла удаляется сразу после отправки (в окно уходят только
    короткий текст и ранги), а каждые MASS_GC_EVERY файлов вызывается gc.collect() — буферы
    изображений Pillow/OpenCV (вырезки строк, увеличенные копии) не копятся при 200+ файлах.
    Отмена: requestInterruption() — поток остановится после текущего файла."""

    def run(self):
        total = len(self.paths)
        for i, path in enumerate(self.paths):
            if self.isInterruptionRequested():
                break
            self.progress.emit(i, total)
            res = None
            try:
                res = run_ocr_pipeline(path)
            except OcrError as e:
                self.file_failed.emit(i, str(e))
            except Exception as e:  # noqa: BLE001 — один плохой файл не должен ронять пакет
                self.file_failed.emit(i, f"Ошибка распознавания:\n{e}")
            else:
                self.file_done.emit(i, res["text"], res["ranks"], res["glob"],
                                    res.get("confs"))
            del res                                   # освобождаем результат файла сразу
            if (i + 1) % MASS_GC_EVERY == 0:
                gc.collect()                          # явная уборка буферов изображений
        gc.collect()
