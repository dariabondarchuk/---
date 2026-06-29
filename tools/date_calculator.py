"""Расчёт периодов просрочки в днях.

Детерминированный код, без LLM. Даты на входе — в формате ДД.ММ.ГГГГ
(как они извлекаются Аналитиком из иска/ДДУ) либо datetime.date.
"""

from __future__ import annotations

from datetime import date, datetime


def parse_ru_date(value: str | date) -> date:
    """Разобрать дату из строки ДД.ММ.ГГГГ (или вернуть date как есть)."""
    if isinstance(value, date):
        return value
    value = value.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Не удалось разобрать дату: {value!r}")


def days_between(start: str | date, end: str | date, inclusive: bool = True) -> int:
    """Число дней просрочки между двумя датами.

    Args:
        start: начало периода (напр. день, следующий за плановой датой передачи).
        end: конец периода (фактическая передача / дата иска).
        inclusive: включать ли последний день в расчёт.

    Returns:
        Число дней (>= 0). Если end раньше start — 0.
    """
    s = parse_ru_date(start)
    e = parse_ru_date(end)
    delta = (e - s).days
    if delta < 0:
        return 0
    return delta + 1 if inclusive else delta


def overdue_days(planned_handover: str | date, actual_or_claim: str | date) -> int:
    """Дни просрочки передачи объекта.

    Просрочка считается со дня, следующего за плановой датой передачи,
    по дату фактической передачи (или дату подачи иска).
    """
    planned = parse_ru_date(planned_handover)
    end = parse_ru_date(actual_or_claim)
    delta = (end - planned).days
    return max(delta, 0)
