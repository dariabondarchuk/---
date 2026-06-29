"""Извлечение текста из PDF: сначала текстовый слой, затем OCR (если доступен).

Требование задачи: иски часто приходят сканами без текстового слоя. Если OCR
в окружении недоступен (нет tesseract / pytesseract / pdf2image), модуль НЕ
падает с технической ошибкой, а поднимает NeedTextLayerError с понятным для
пользователя сообщением.
"""

from __future__ import annotations

# Минимальная длина текста, при которой считаем, что текстовый слой есть.
_MIN_NATIVE_CHARS = 100


class NeedTextLayerError(Exception):
    """PDF без текстового слоя, а OCR недоступен. Сообщение — для пользователя."""

    DEFAULT_MESSAGE = (
        "Похоже, это скан без текстового слоя, а распознавание (OCR) в этом "
        "окружении недоступно. Пожалуйста, загрузите PDF с текстовым слоем "
        "(например, экспортированный из Word или прошедший распознавание)."
    )

    def __init__(self, message: str | None = None):
        super().__init__(message or self.DEFAULT_MESSAGE)


def _read_native_layer(pdf_path: str) -> str:
    """Прочитать встроенный текстовый слой через pdfplumber."""
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise NeedTextLayerError(
            "Не установлена библиотека pdfplumber для чтения PDF. "
            "Установите зависимости из requirements.txt."
        ) from exc

    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _ocr_available() -> bool:
    """Доступен ли OCR-стек (pytesseract + pdf2image + бинарь tesseract)."""
    try:
        import shutil

        import pdf2image  # noqa: F401
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    # Бинарь tesseract тоже должен присутствовать в системе.
    return shutil.which("tesseract") is not None


def _ocr_pdf(pdf_path: str, lang: str = "rus") -> tuple[str, float]:
    """Распознать скан через pytesseract. Вернуть (текст, confidence 0..1)."""
    import pdf2image
    import pytesseract

    pages = pdf2image.convert_from_path(pdf_path, dpi=300)
    texts: list[str] = []
    confs: list[int] = []
    for img in pages:
        data = pytesseract.image_to_data(
            img, lang=lang, output_type=pytesseract.Output.DICT
        )
        words = [w for w in data["text"] if w.strip()]
        page_conf = [int(c) for c in data["conf"] if str(c) not in ("-1",)]
        texts.append(" ".join(words))
        confs.extend(page_conf)
    confidence = (sum(confs) / len(confs) / 100) if confs else 0.0
    return "\n".join(texts), round(confidence, 2)


def extract_text(pdf_path: str) -> tuple[str, float]:
    """Извлечь текст из PDF.

    Returns:
        (текст, confidence). Для текстового слоя confidence = 1.0;
        для OCR — средняя уверенность распознавания (0..1).

    Raises:
        NeedTextLayerError: если текстового слоя нет, а OCR недоступен.
    """
    native = _read_native_layer(pdf_path)
    if len(native.strip()) >= _MIN_NATIVE_CHARS:
        return native, 1.0

    # Текстового слоя нет — пробуем OCR.
    if not _ocr_available():
        raise NeedTextLayerError()

    text, confidence = _ocr_pdf(pdf_path)
    if len(text.strip()) < _MIN_NATIVE_CHARS:
        raise NeedTextLayerError()
    return text, confidence
