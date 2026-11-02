"""Улучшение отдельных фрагментов (названия, цветные плашки) для повторного OCR."""

from ..compat import cv2, np
from .config import OCR_DENOISE_H, OCR_ENHANCE_SCALE, OCR_PAD
from .preprocess import _adaptive_binarize


# ---------------------------------------------------------------------------
# НОВОЕ: ДВА НЕЗАВИСИМЫХ КОНВЕЙЕРА ДЛЯ КАЖДОЙ СТРОКИ
#   КОНВЕЙЕР А (цвет / ранг): читает пиксели НЕИЗМЕНЁННОГО исходного снимка по рамке текста
#       названия (detect_rarity_colors -> classify_rarity_color): жёлтый/золотой -> S,
#       фиолетовый -> A, серый/белый -> B. Логика цвета НЕ менялась и от обработки текста
#       не зависит: конвейер Б меняет только поле строки «text» и никогда не трогает рамки
#       («box», «words», «name_left»), по которым конвейер А вырезает свою область.
#   КОНВЕЙЕР Б (текст): копия вырезки строки -> увеличение cv2.resize (×2–3) -> оттенки
#       серого -> шумоподавление (убирает свечение шрифта и полупрозрачные элементы
#       интерфейса) -> порог Оцу (THRESH_BINARY + THRESH_OTSU): чёрный текст на чистом
#       белом -> медианный фильтр -> Tesseract. Результат объединяется с рангом из конвейера А
#       уже в parse_screenshot_text / ocr_extract_pulls, а опечатки исправляют нечёткие
#       справочники (difflib: персонажи, дуги, планеры, предметы).
# ---------------------------------------------------------------------------
def enhance_text_crop(rgb):
    """КОНВЕЙЕР Б: улучшенная КОПИЯ вырезки строки для Tesseract. rgb — массив RGB (исходная
    вырезка не изменяется). Возвращает одноканальную картинку: чёрный текст на белом фоне
    с белым полем по краям."""
    work = rgb.copy()                                               # исходник не трогаем
    work = cv2.resize(work, None, fx=OCR_ENHANCE_SCALE, fy=OCR_ENHANCE_SCALE,
                      interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(work, cv2.COLOR_RGB2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, h=OCR_DENOISE_H,
                                    templateWindowSize=7, searchWindowSize=21)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if (bw > 0).mean() < 0.5:        # белых пикселей меньшинство -> светлый текст на тёмном фоне
        bw = cv2.bitwise_not(bw)     # (тёмный интерфейс игры): делаем текст чёрным на белом
    bw = cv2.medianBlur(bw, 3)       # убирает одиночные пятна и «соль-перец» после порога
    pad = max(8, int(OCR_PAD * OCR_ENHANCE_SCALE))
    return cv2.copyMakeBorder(bw, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)



def _pad_white(img):
    pad = max(8, int(OCR_PAD * OCR_ENHANCE_SCALE))
    return cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)



def enhance_text_crop_variants(rgb) -> list:
    """Несколько независимых вариантов улучшенной КОПИИ вырезки строки (исходник не меняется):
      1) «отличие от фона»: цвет фона — медиана краёв вырезки, текст — пиксели, заметно
         отличающиеся от него по любому каналу; не зависит ни от цвета подсветки строки
         (жёлтая / фиолетовая), ни от полярности (светлый текст на тёмном и наоборот);
      2) серый + шумоподавление + порог Оцу (прежний вариант конвейера Б);
      3) CLAHE + адаптивный порог (неравномерный фон, полупрозрачные панели).
    Все варианты — чёрный текст на белом с белым полем по краям."""
    work = cv2.resize(rgb.copy(), None, fx=OCR_ENHANCE_SCALE, fy=OCR_ENHANCE_SCALE,
                      interpolation=cv2.INTER_CUBIC)
    out = []
    try:
        edge = np.concatenate([work[0, :], work[-1, :], work[:, 0], work[:, -1]]).reshape(-1, 3)
        bg = np.median(edge, axis=0).astype(np.int16)
        diff = np.abs(work.astype(np.int16) - bg).max(axis=2).astype(np.uint8)
        diff = cv2.GaussianBlur(diff, (3, 3), 0)
        _, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        out.append(_pad_white(cv2.medianBlur(cv2.bitwise_not(mask), 3)))
    except (ValueError, cv2.error):
        pass
    gray = cv2.cvtColor(work, cv2.COLOR_RGB2GRAY)
    den = cv2.fastNlMeansDenoising(gray, None, h=OCR_DENOISE_H,
                                   templateWindowSize=7, searchWindowSize=21)
    _, bw = cv2.threshold(den, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if (bw > 0).mean() < 0.5:
        bw = cv2.bitwise_not(bw)
    out.append(_pad_white(cv2.medianBlur(bw, 3)))
    if float(gray.mean()) < 110:
        gray = cv2.bitwise_not(gray)
    eq = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 4)).apply(gray)
    out.append(_pad_white(_adaptive_binarize(eq)))
    return out



def _color_fill_mask(rgb):
    """Маска ЗАЛИВКИ цветного названия (золото S / розово-фиолетовый A) на светлой строке
    таблицы: насыщенные яркие пиксели. Серый текст, светлый фон и чёрная обводка в маску не
    попадают. Возвращает (маска uint8 0/255, hsv) или (None, None), если цветного текста нет."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    fill = ((hsv[:, :, 1] > 110) & (hsv[:, :, 2] > 110)).astype(np.uint8) * 255
    fill = cv2.morphologyEx(fill, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    if int((fill > 0).sum()) < max(12, 0.002 * fill.size):
        return None, None
    return fill, hsv



def _fill_rank_hint(rgb):
    """Ранг по оттенку заливки названия: золото -> 5 (S), розово-фиолетовый -> 4 (A);
    нет цветной заливки -> 3 (серый, B). None — маску построить не удалось."""
    try:
        fill, hsv = _color_fill_mask(rgb)
        if fill is None:
            return 3
        hue = float(np.median(hsv[:, :, 0][fill > 0]))
        if 8 <= hue <= 45:
            return 5
        if 115 <= hue <= 179 or hue <= 3:
            return 4
        return None
    except (ValueError, cv2.error):
        return None



def _color_fill_variants(rgb) -> list:
    """ИСПРАВЛЕНО: цветные названия в таблице дуг (золотые / розовые буквы с ЧЁРНОЙ обводкой)
    обычная бинаризация читает частично или не читает вовсе: в строке оставалась «только
    дата». Текст выделяется по цвету заливки (чёрный текст на белом, белое поле по краям):
      1) ГЛАДКАЯ маска: мягкая насыщенность -> увеличение ×3 с интерполяцией -> размытие ->
         порог (ровные края букв, без «лесенки»);
      2) жёсткая маска заливки ×2.5;
      3) жёсткая маска со сглаженными краями (замкнуты мелкие разрывы букв)."""
    try:
        fill, hsv = _color_fill_mask(rgb)
        if fill is None:
            return []
        out = []
        sat = hsv[:, :, 1].astype(np.float32)
        soft = np.clip((sat - 70.0) / 80.0, 0.0, 1.0) * (hsv[:, :, 2] > 100)
        soft = cv2.bitwise_and((soft * 255).astype(np.uint8), cv2.dilate(fill, np.ones((3, 3), np.uint8)))
        big = cv2.resize(soft, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        big = cv2.GaussianBlur(big, (0, 0), 1.2)
        _, big = cv2.threshold(big, 110, 255, cv2.THRESH_BINARY)
        out.append(_pad_white(cv2.bitwise_not(big)))
        work_fill = cv2.resize(fill, None, fx=OCR_ENHANCE_SCALE, fy=OCR_ENHANCE_SCALE,
                               interpolation=cv2.INTER_CUBIC)
        _, work_fill = cv2.threshold(work_fill, 127, 255, cv2.THRESH_BINARY)
        out.append(_pad_white(cv2.bitwise_not(work_fill)))
        both = cv2.morphologyEx(work_fill, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        both = cv2.medianBlur(both, 5)
        out.append(_pad_white(cv2.bitwise_not(both)))
        return out
    except (ValueError, cv2.error):
        return []



def _text_bbox(rgb):
    """Рамка текста названия внутри вырезки (x0, y0, x1, y1) в координатах вырезки: сначала по
    цвету заливки, иначе по отличию от фона. None — текста не найдено."""
    try:
        mask, _hsv = _color_fill_mask(rgb)
        if mask is None:
            edge = np.concatenate([rgb[0, :], rgb[-1, :], rgb[:, 0], rgb[:, -1]]).reshape(-1, 3)
            bg = np.median(edge, axis=0).astype(np.int16)
            diff = np.abs(rgb.astype(np.int16) - bg).max(axis=2).astype(np.uint8)
            mask = ((diff > 60).astype(np.uint8)) * 255
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        ys, xs = np.nonzero(mask)
        if len(xs) < 12:
            return None
        return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    except (ValueError, cv2.error):
        return None
