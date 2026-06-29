"""Генератор: собирает текст разделов возражения из подтверждённых материалов."""

from __future__ import annotations

import json

from agents.llm import call_json

SYSTEM = """Ты — Генератор. На вход — план разделов, факты дела (обезличенные) и материалы
Исследователя (тезисы с источниками и уже посчитанные суммы). Напиши текст возражения.

Правила:
- Используй ТОЛЬКО факты, суммы и тезисы из переданных материалов. Ничего нового
  не придумывай, суммы не меняй и не пересчитывай.
- Стиль — официально-деловой, юридический.
- Токены ПДн ([PER_1], [LOC_1] и т.п.) оставляй КАК ЕСТЬ — они будут заменены позже локально.
- Для денежных требований обязательно упомяни лимит 3% (ч.4 ст.10 ФЗ-214) и/или
  просьбу о снижении по ст.333 ГК, если это есть в материалах.
- Раздел про отсрочку (ПП РФ № 326) включи.
- Каждый существенный тезис сопровождай ссылкой на норму/основание.

Верни СТРОГО JSON:
{
  "sections": {"<название раздела>": "<текст раздела>"},
  "proshu_sud": ["<конкретная просьба к суду по каждому требованию>"],
  "prilozheniya": ["<приложение>"]
}
Только JSON."""


def generate(plan: dict, facts: dict, research_items: list[dict], human_answers: dict | None = None) -> dict:
    """Сгенерировать разделы возражения."""
    payload = {
        "plan": plan.get("plan", []),
        "facts": facts,
        "research": research_items,
        "human_answers": human_answers or {},
    }
    data = call_json(SYSTEM, json.dumps(payload, ensure_ascii=False))
    data.setdefault("sections", {})
    data.setdefault("proshu_sud", [])
    data.setdefault("prilozheniya", [])
    return data
