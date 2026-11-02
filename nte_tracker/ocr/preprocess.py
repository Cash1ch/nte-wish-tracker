"""Подготовка снимка к распознаванию (масштаб, бинаризация, Tesseract)."""

from pathlib import Path

from ..compat import cv2, Image, ImageOps, ImageStat, np, pytesseract
from .config import (
    OCR_ADAPTIVE_BLOCK, OCR_ADAPTIVE_C, OCR_BILATERAL, OCR_CLAHE_CLIP, OCR_CLAHE_TILE, OCR_DEBUG_DIR,
    OCR_MAX_SCALE, OCR_SHARPEN, OCR_TARGET_WIDTH,
)


_ocr_langs_cache = None



def _available_langs() -> list:
    """Языки, установленные в Tesseract (список кэшируется). При ошибке — пустой список."""
    global _ocr_langs_cache
    if _ocr_langs_cache is None:
        try:
            _ocr_langs_cache = list(pytesseract.get_languages(config=""))
        except Exception:
            _ocr_langs_cache = []
    return _ocr_langs_cache



def _choose_scale(width: int, height: int) -> float:
    """Во сколько раз увеличить снимок: до OCR_TARGET_WIDTH по ширине, но не больше
    OCR_MAX_SCALE. Широкие снимки (от OCR_TARGET_WIDTH) не увеличиваются вовсе."""
    scale = min(OCR_MAX_SCALE, max(1.0, OCR_TARGET_WIDTH / max(1, width)))
    return 1.0 if scale < 1.1 else scale



def _prepare_gray(rgb_img, scale: float):
    """Лёгкая подготовка: оттенки серого -> увеличение кубической интерполяцией -> тёмный
    интерфейс инвертируется (текст становится тёмным на светлом) -> мягкий CLAHE."""
    gray = cv2.cvtColor(np.array(rgb_img), cv2.COLOR_RGB2GRAY)
    if scale > 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if float(gray.mean()) < 110:                 # тёмный интерфейс игры
        gray = cv2.bitwise_not(gray)
    if OCR_BILATERAL:                            # шум и зернистость полупрозрачных панелей
        gray = cv2.bilateralFilter(gray, *OCR_BILATERAL)
    clahe = cv2.createCLAHE(clipLimit=OCR_CLAHE_CLIP,
                            tileGridSize=(OCR_CLAHE_TILE, OCR_CLAHE_TILE))
    gray = clahe.apply(gray)
    if OCR_SHARPEN:                              # нерезкая маска: чётче края букв
        blur = cv2.GaussianBlur(gray, (0, 0), 1.2)
        gray = cv2.addWeighted(gray, 1.0 + OCR_SHARPEN, blur, -OCR_SHARPEN, 0)
    return gray



def _binarize_fallback(gray):
    """ЗАПАСНОЙ вариант (только при низкой уверенности): порог Otsu и лёгкая морфология —
    открытие убирает одиночные пятна, закрытие склеивает разрывы штрихов. Возвращает чёрный
    текст на белом. Используется редко, поэтому стоит заметно дешевле прежнего конвейера."""
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.bitwise_not(bw) if (bw > 0).mean() >= 0.5 else bw     # текст = меньшинство
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    return cv2.bitwise_not(mask)



def _adaptive_binarize(gray):
    """Второй запасной вариант: адаптивный гауссов порог — хорошо работает при неравномерной
    подсветке (жёлтые / фиолетовые строки, полупрозрачные панели). Чёрный текст на белом."""
    block = OCR_ADAPTIVE_BLOCK if OCR_ADAPTIVE_BLOCK % 2 else OCR_ADAPTIVE_BLOCK + 1
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, block, OCR_ADAPTIVE_C)



def _save_debug(name: str, img) -> None:
    """Сохраняет промежуточную картинку в OCR_DEBUG_DIR (если папка задана)."""
    if not OCR_DEBUG_DIR:
        return
    try:
        folder = Path(OCR_DEBUG_DIR)
        folder.mkdir(parents=True, exist_ok=True)
        ok, buf = cv2.imencode(".png", img)   # imencode — чтобы работали пути с кириллицей
        if ok:
            (folder / f"{name}.png").write_bytes(buf.tobytes())
    except OSError:
        pass



def _prepare_for_ocr_pil(img):
    """ЗАПАСНОЙ вариант без OpenCV (Pillow): ×2, серый, инверсия тёмного фона, автоконтраст.
    Возвращает (картинка, масштаб относительно оригинала)."""
    img = ImageOps.exif_transpose(img).convert("L")
    scale = 1
    if img.width < 1600:  # мелкий текст читается лучше в увеличенном виде
        scale = 2
        img = img.resize((img.width * 2, img.height * 2), Image.BICUBIC)
    if ImageStat.Stat(img).mean[0] < 110:  # тёмный интерфейс игры -> тёмный текст на светлом
        img = ImageOps.invert(img)
    return ImageOps.autocontrast(img), scale
