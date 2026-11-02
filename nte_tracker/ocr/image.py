"""Точка входа OCR для изображения (ocr_image)."""

from ..compat import cv2, Image, ImageOps, np, pytesseract
from ..errors import OcrError
from ..paths import find_tesseract
from .columns import (
    _fill_row_gaps, _find_page_in_lines, _flag_rows_without_icon, _read_page_below, _refine_date_column,
    _refine_qty_column, _refine_time_column,
)
from .config import OCR_PSM_LAYOUT, OCR_TABLE_ROI
from .layout import _filter_table_lines, _group_words, _layout_pass, _run_langs
from .names_read import _header_label_right, _recover_missing_names, _refine_name_column
from .preprocess import _choose_scale, _prepare_for_ocr_pil, _prepare_gray, _save_debug


def _ocr_pipeline(src, info=None) -> list:
    """Конвейер на OpenCV: серая картинка (≤×2) -> проход 1 (весь снимок, один запуск) ->
    группировка по строкам -> отсев мусора и строк вне таблицы -> перечитывание слабых названий.
    src — Pillow RGB. Возвращает строки в координатах src."""
    scale = _choose_scale(src.width, src.height)
    gray = _prepare_gray(src, scale)
    _save_debug("gray_prepared", gray)
    words, lang = _layout_pass(gray, scale)
    raw = _group_words(words)
    lines = _filter_table_lines(raw)
    lines = _refine_name_column(lines, src, lang)
    lines = _refine_time_column(lines, src)
    lines = _refine_date_column(lines, src)
    lines = _refine_qty_column(lines, src)
    lines = _recover_missing_names(lines, src, lang)
    lines = _fill_row_gaps(lines)
    lines = _flag_rows_without_icon(lines, src)
    label_right = _header_label_right(lines)
    if label_right is not None:
        for ln in lines:
            ln["label_right"] = label_right
    if info is not None:
        page = _find_page_in_lines(raw, lines)
        alts = [(page, 1)] if page else []
        if page is None:
            page, alts = _read_page_below(src, lines)
        info["page"], info["page_alts"] = page, alts
    return lines



def _ocr_pipeline_pil(src, info=None) -> list:
    """Упрощённый конвейер без OpenCV: одна попытка --psm 6 по подготовленной Pillow картинке
    с той же очисткой мусора и группировкой строк."""
    img, scale = _prepare_for_ocr_pil(src)
    words, _, err = _run_langs(img, OCR_PSM_LAYOUT, scale)
    if words is None:
        raise OcrError(f"Ошибка распознавания:\n{err}")
    raw = _group_words(words)
    lines = [dict(ln, name_left=ln["box"][0]) for ln in _filter_table_lines(raw)]
    if info is not None:
        info["page"] = _find_page_in_lines(raw, lines)
    return lines



def ocr_image(path: str, roi=None, info=None) -> list:
    """Распознаёт текст на изображении. Возвращает строки [{"text", "box", "name_left", ...}]
    в порядке сверху вниз; box и name_left — в пикселях ИСХОДНОГО файла (нужны цветовому
    анализу рангов). roi — область таблицы в долях снимка (левый, верхний, правый, нижний);
    по умолчанию OCR_TABLE_ROI. Бросает OcrError с понятным текстом."""
    if pytesseract is None or Image is None:
        raise OcrError("Для распознавания скриншотов нужны библиотеки:\n"
                       "    pip install pytesseract pillow opencv-python numpy\n"
                       "и программа Tesseract OCR с языковым пакетом rus.")
    exe = find_tesseract()      # встроенная папка Tesseract-OCR, Program Files или PATH
    if exe is not None:
        pytesseract.pytesseract.tesseract_cmd = str(exe)
    try:
        src = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        raise OcrError(f"Не удалось открыть изображение:\n{e}") from e

    # необязательная вырезка области таблицы; смещение вернём в координаты полного снимка
    ox = oy = 0
    roi = roi if roi is not None else OCR_TABLE_ROI
    if roi:
        fl, ft, fr, fb = (min(1.0, max(0.0, float(v))) for v in roi)
        box = (int(src.width * fl), int(src.height * ft),
               int(src.width * fr), int(src.height * fb))
        if box[2] - box[0] > 50 and box[3] - box[1] > 50:
            src, (ox, oy) = src.crop(box), box[:2]

    if cv2 is not None and np is not None:
        lines = _ocr_pipeline(src, info)
    else:
        lines = _ocr_pipeline_pil(src, info)

    if ox or oy:
        def shift(b):
            return (b[0] + ox, b[1] + oy, b[2] + ox, b[3] + oy)
        for ln in lines:
            ln["box"] = shift(ln["box"])
            ln["name_left"] = ln.get("name_left", ln["box"][0] - ox) + ox
            for w in ln.get("words", ()):
                w["box"] = shift(w["box"])
    return lines
