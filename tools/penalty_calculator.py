"""Калькулятор неустойки и сумм по делам дольщиков (214-ФЗ).

ВАЖНО: все денежные суммы в системе считаются ТОЛЬКО здесь, детерминированно.
LLM не имеет права считать арифметику — это запрещено инвариантами проекта.
Все функции чистые, без побочных эффектов, округление до копеек (2 знака).
"""

from __future__ import annotations


def _round_kopecks(value: float) -> float:
    """Округление до копеек (2 знака после запятой)."""
    return round(value + 1e-9, 2)


def penalty_delay(price: float, days_overdue: int, daily_rate: float) -> float:
    """Неустойка за просрочку передачи объекта долевого строительства.

    Args:
        price: цена договора (руб.).
        days_overdue: число дней просрочки.
        daily_rate: дневная ставка неустойки (доля, напр. 1/150 ключевой ставки).

    Returns:
        Сумма неустойки в рублях, округлённая до копеек.
    """
    if price < 0 or days_overdue < 0 or daily_rate < 0:
        raise ValueError("Цена, дни и ставка не могут быть отрицательными")
    return _round_kopecks(price * daily_rate * days_overdue)


def cap_3_percent(price: float) -> float:
    """Лимит взыскания 3% цены договора (ч.4 ст.10 ФЗ-214).

    Применяется как потолок для требований о расходах на устранение
    недостатков и связанных неустоек/штрафов.

    Args:
        price: цена договора (руб.).

    Returns:
        3% от цены договора, округлённые до копеек.
    """
    if price < 0:
        raise ValueError("Цена не может быть отрицательной")
    return _round_kopecks(price * 0.03)


def apply_cap(amount: float, price: float) -> float:
    """Применить лимит 3% к заявленной сумме.

    Возвращает меньшее из заявленной суммы и лимита 3% цены договора.

    Args:
        amount: заявленная истцом сумма (руб.).
        price: цена договора (руб.).

    Returns:
        Сумма, ограниченная лимитом 3%.
    """
    return _round_kopecks(min(amount, cap_3_percent(price)))


def apply_art_333(amount: float, factor: float = 0.3) -> float:
    """Ориентировочное снижение неустойки/штрафа по ст.333 ГК РФ.

    Это ДОВОД ответчика (просьба к суду о снижении), а не точная цифра —
    итоговый размер определяет суд. factor по умолчанию 0.3 (снижение до 30%).

    Args:
        amount: исходная сумма (руб.).
        factor: коэффициент, на который предлагается снизить (0..1).

    Returns:
        Предлагаемая сниженная сумма, округлённая до копеек.
    """
    if not 0 <= factor <= 1:
        raise ValueError("Коэффициент снижения должен быть в диапазоне 0..1")
    if amount < 0:
        raise ValueError("Сумма не может быть отрицательной")
    return _round_kopecks(amount * factor)


def fine_consumer(awarded_to_consumer: float) -> float:
    """Штраф 50% за неудовлетворение требований потребителя (ст.13 ЗоЗПП).

    Args:
        awarded_to_consumer: сумма, присуждённая в пользу потребителя (руб.).

    Returns:
        50% от присуждённой суммы.
    """
    if awarded_to_consumer < 0:
        raise ValueError("Сумма не может быть отрицательной")
    return _round_kopecks(awarded_to_consumer * 0.5)
