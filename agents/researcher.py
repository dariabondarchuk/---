"""Исследователь: собирает материалы по требованию.

КЛЮЧЕВОЙ ИНВАРИАНТ: все суммы считает детерминированный калькулятор
(tools.penalty_calculator / tools.date_calculator), а НЕ модель. Gemini здесь
только формулирует правовые тезисы и подбирает ссылки на нормы — числа ему
передаются уже посчитанными, и выдумывать их запрещено.
"""

from __future__ import annotations

import json

from agents.llm import call_json
from tools import penalty_calculator as pc
from tools.legal_norms import norms_for

# Типы требований, к которым применим лимит 3% (ч.4 ст.10 ФЗ-214).
_CAP_TYPES = {"defects", "penalty_defects", "fine"}
# Типы, к которым уместна просьба о снижении по ст.333 ГК.
_ART333_TYPES = {"penalty_delay", "penalty_defects", "fine"}

SYSTEM = """Ты — Исследователь. Готовишь материалы для возражения по ОДНОМУ требованию истца.
Сам текст возражения НЕ пишешь — только тезисы ответчика и ссылки на источники.

На вход — JSON: требование, факты дела, применимые нормы и УЖЕ ПОСЧИТАННЫЕ суммы (поле computed).

СТРОГО ЗАПРЕЩЕНО считать или менять любые суммы — бери их только из computed как есть.
Каждый тезис ОБЯЗАН иметь citation (норма из переданных или вывод калькулятора). Без источника тезис не включай.

Верни СТРОГО JSON:
{
  "requirement_type": "...",
  "arguments": [{"point": "тезис ответчика", "citation": "норма/расчёт-источник"}]
}
Только JSON."""


def _compute(requirement: dict, facts: dict) -> dict:
    """Детерминированные расчёты по требованию. Возвращает computed с _source."""
    rtype = requirement.get("type", "")
    amount = requirement.get("amount_claimed")
    price = facts.get("contract_price")
    computed: dict = {}

    if isinstance(price, (int, float)) and price > 0:
        cap = pc.cap_3_percent(price)
        computed["cap_3_percent"] = cap
        computed["_source_cap"] = (
            f"penalty_calculator.cap_3_percent(price={price}) — лимит ч.4 ст.10 ФЗ-214"
        )
        if rtype in _CAP_TYPES and isinstance(amount, (int, float)):
            computed["claim_exceeds_cap"] = amount > cap
            if amount > cap:
                computed["capped_amount"] = pc.apply_cap(amount, price)
                computed["_source_capped"] = (
                    f"penalty_calculator.apply_cap(amount={amount}, price={price})"
                )

    if rtype in _ART333_TYPES and isinstance(amount, (int, float)):
        computed["suggested_art_333"] = pc.apply_art_333(amount)
        computed["_source_333"] = (
            f"penalty_calculator.apply_art_333(amount={amount}, factor=0.3) — "
            f"ориентировочное снижение по ст.333 ГК (итог определяет суд)"
        )

    if rtype == "penalty_delay":
        computed["note_delay"] = (
            "Точный пересчёт неустойки за просрочку требует ключевой ставки ЦБ и "
            "даты фактической передачи — при наличии данных считать через "
            "penalty_calculator.penalty_delay()."
        )

    return computed


def research(requirement: dict, facts: dict) -> dict:
    """Собрать материалы по одному требованию."""
    rtype = requirement.get("type", "")
    computed = _compute(requirement, facts)
    norms = norms_for(rtype)

    payload = {
        "requirement": requirement,
        "facts": facts,
        "applicable_norms": norms,
        "computed": computed,
    }
    result = call_json(SYSTEM, json.dumps(payload, ensure_ascii=False))
    # Числа берём из НАШЕГО детерминированного расчёта, а не из ответа модели.
    result["computed"] = computed
    result["requirement_type"] = rtype
    result.setdefault("arguments", [])
    return result
