"""Обёртка над Google Gemini (langchain-google-genai).

Мозг системы — Gemini, НЕ Anthropic: это сознательный выбор, т.к. сервис должен
работать из России, где Anthropic API недоступен. Ключ берётся из переменной
окружения GEMINI_API_KEY. Температура держится низкой (0..0.2) — задачи
извлечения/проверки требуют предсказуемости, а не креатива.
"""

from __future__ import annotations

import json
import os
import re

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")


class LLMConfigError(RuntimeError):
    """Не задан ключ GEMINI_API_KEY или не установлена библиотека."""


def _temperature() -> float:
    """Температура из env, зажатая в безопасный диапазон 0..0.2."""
    try:
        t = float(os.environ.get("GEMINI_TEMPERATURE", "0.1"))
    except ValueError:
        t = 0.1
    return max(0.0, min(0.2, t))


def get_llm(temperature: float | None = None):
    """Создать клиент Gemini. Бросает LLMConfigError при отсутствии ключа/пакета."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise LLMConfigError(
            "Не задана переменная окружения GEMINI_API_KEY. Получите ключ в "
            "Google AI Studio и задайте его перед запуском приложения."
        )
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:
        raise LLMConfigError(
            "Не установлен пакет langchain-google-genai. Установите зависимости "
            "из requirements.txt."
        ) from exc

    return ChatGoogleGenerativeAI(
        model=DEFAULT_MODEL,
        google_api_key=api_key,
        temperature=_temperature() if temperature is None else temperature,
    )


def _extract_json(text: str) -> str:
    """Достать JSON из ответа модели (снять ```json-ограждения, лишний текст)."""
    text = text.strip()
    # Снять markdown-ограждение ```json ... ```
    fence = re.match(r"^```(?:json)?\s*(.+?)\s*```$", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    # Иначе попробовать вырезать первый сбалансированный объект/массив.
    start = min(
        [i for i in (text.find("{"), text.find("[")) if i != -1], default=-1
    )
    if start != -1:
        return text[start:].strip()
    return text


def call_json(system_prompt: str, user_content: str, temperature: float | None = None):
    """Вызвать Gemini и распарсить ответ как JSON.

    Args:
        system_prompt: системная инструкция (роль агента).
        user_content: данные (УЖЕ обезличенные!).

    Returns:
        Распарсенный объект (dict или list).

    Raises:
        ValueError: если ответ не удалось распарсить как JSON.
    """
    llm = get_llm(temperature=temperature)
    resp = llm.invoke(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
    )
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    payload = _extract_json(raw)
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Модель вернула не-JSON ответ: {raw[:500]}"
        ) from exc
