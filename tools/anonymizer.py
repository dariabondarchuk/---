"""Обезличивание персональных данных (ПДн) перед отправкой в облако (Gemini).

ИНВАРИАНТ ПРОЕКТА: реальные ПДн (ФИО, адреса, телефоны, паспорта и т.п.) НЕ
должны покидать локальную машину. Перед любым вызовом LLM текст прогоняется
через anonymize(); реальные значения восстанавливаются только в финальном
.docx локально через restore().

Стратегия:
  1) regex — телефон / email / ИНН / СНИЛС / паспорт (работает всегда);
  2) Natasha NER — ФИО (PER) и адреса (LOC), если библиотека установлена.

Natasha импортируется лениво и опционально: если её нет в окружении, regex-слой
всё равно отрабатывает, а вызывающий код предупреждается через natasha_available().
"""

from __future__ import annotations

import re

# Порядок важен: более специфичные шаблоны раньше общих (паспорт раньше ИНН и т.п.)
PATTERNS: dict[str, str] = {
    "EMAIL": r"[\w.\-]+@[\w.\-]+\.\w+",
    "PHONE": r"(?:\+7|8)[\s\-(]?\d{3}[\s\-)]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",
    "SNILS": r"\b\d{3}-\d{3}-\d{3}\s?\d{2}\b",
    # Паспорт: серия (4 цифры, м.б. с пробелом) + пробел + номер (6 цифр).
    # Пробел перед номером обязателен, иначе голый 10-значный номер не отличить
    # от ИНН — такой случай уводим в ИНН ниже.
    "PASSPORT": r"\b\d{2}\s?\d{2}\s\d{6}\b",
    "INN": r"\b\d{10}\b|\b\d{12}\b",
}

# Кэш Natasha-теггера, чтобы не инициализировать модель на каждый вызов.
_natasha_cache: dict[str, object] | None = None
_natasha_failed = False


def natasha_available() -> bool:
    """Доступна ли Natasha NER в текущем окружении."""
    return _load_natasha() is not None


def _load_natasha():
    """Лениво инициализировать Natasha. Вернуть dict с объектами или None."""
    global _natasha_cache, _natasha_failed
    if _natasha_cache is not None:
        return _natasha_cache
    if _natasha_failed:
        return None
    try:
        from natasha import Doc, NewsEmbedding, NewsNERTagger, Segmenter

        emb = NewsEmbedding()
        _natasha_cache = {
            "Doc": Doc,
            "segmenter": Segmenter(),
            "ner": NewsNERTagger(emb),
        }
        return _natasha_cache
    except Exception:
        # Библиотека не установлена или не смогла загрузить модели — деградируем.
        _natasha_failed = True
        return None


def _make_substituter(mapping: dict[str, str]):
    """Фабрика функции-замены, ведущей карту токен -> реальное значение."""
    counter: dict[str, int] = {}

    def sub(kind: str, value: str) -> str:
        # Если такое значение уже встречалось — переиспользуем тот же токен.
        for token, existing in mapping.items():
            if existing == value and token.startswith(f"[{kind}_"):
                return token
        counter[kind] = counter.get(kind, 0) + 1
        token = f"[{kind}_{counter[kind]}]"
        mapping[token] = value
        return token

    return sub


def anonymize(text: str) -> tuple[str, dict[str, str]]:
    """Обезличить текст.

    Returns:
        (обезличенный_текст, карта_замен), где карта: токен -> реальное значение.
        Карту нужно сохранить локально и передать в restore() для финального .docx.
    """
    if not text:
        return text, {}

    mapping: dict[str, str] = {}
    sub = _make_substituter(mapping)

    # 1) regex-сущности
    for kind, pat in PATTERNS.items():
        text = re.sub(pat, lambda m, k=kind: sub(k, m.group()), text)

    # 2) ФИО / адреса через Natasha (если доступна)
    nat = _load_natasha()
    if nat is not None:
        doc = nat["Doc"](text)
        doc.segment(nat["segmenter"])
        doc.tag_ner(nat["ner"])
        # Заменяем с конца текста, чтобы не сбить offset'ы предыдущих замен.
        for span in sorted(doc.spans, key=lambda s: s.start, reverse=True):
            if span.type in ("PER", "LOC"):
                token = sub(span.type, span.text)
                text = text[: span.start] + token + text[span.stop :]

    return text, mapping


def restore(text: str, mapping: dict[str, str]) -> str:
    """Восстановить реальные ПДн из карты замен (вызывать ЛОКАЛЬНО, для .docx)."""
    # Восстанавливаем от длинных токенов к коротким, чтобы [PER_10] не пострадал
    # от подстановки [PER_1].
    for token in sorted(mapping, key=len, reverse=True):
        text = text.replace(token, mapping[token])
    return text
