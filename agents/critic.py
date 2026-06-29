"""Критик: проверяет черновик против анализа иска и собранных материалов."""

from __future__ import annotations

import json

from agents.llm import call_json

SYSTEM = """Ты — Критик. Проверь черновик возражения против списка требований и материалов.
Будь придирчив — цена ошибки в суде высока.

Проверь:
1. На КАЖДОЕ требование из анализа есть раздел. Ничего не пропущено.
2. Каждая сумма/дата в тексте трассируется к источнику (иск / ДДУ / вывод калькулятора).
   Сумм «из ниоткуда» быть не должно.
3. Ссылки на нормы корректны и уместны (ФЗ-214, ст.333 ГК, ПП-326).
4. Нет юридических утверждений без источника.
5. Присутствуют: лимит 3% где применимо, ст.333 где применимо, ходатайство об отсрочке,
   блок ПРОШУ СУД, приложения.
6. Нет противоречий между разделами.

Верни СТРОГО JSON:
{
  "verdict": "PASS" | "FAIL",
  "issues": [{"severity": "blocker|minor", "where": "раздел", "message": "..."}]
}
blocker — нельзя выпускать (пропущенное требование, сумма без источника, выдуманная норма).
minor — стиль/полнота. Хоть один blocker → verdict FAIL. Только JSON."""


def review(analysis: dict, draft: dict, research_items: list[dict]) -> dict:
    """Проверить черновик. Возвращает {verdict, issues}."""
    payload = {
        "requirements": analysis.get("requirements", []),
        "draft": draft,
        "research": research_items,
    }
    data = call_json(SYSTEM, json.dumps(payload, ensure_ascii=False))
    data.setdefault("verdict", "FAIL")
    data.setdefault("issues", [])
    return data
