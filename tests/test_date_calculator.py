"""Тесты расчёта периодов просрочки."""

from tools import date_calculator as dc


def test_parse_ru_date():
    d = dc.parse_ru_date("15.03.2023")
    assert (d.day, d.month, d.year) == (15, 3, 2023)


def test_overdue_days():
    # с 01.01.2023 (план) по 31.01.2023 = 30 дней просрочки
    assert dc.overdue_days("01.01.2023", "31.01.2023") == 30


def test_overdue_days_no_overdue():
    assert dc.overdue_days("01.02.2023", "01.01.2023") == 0


def test_days_between_inclusive():
    assert dc.days_between("01.01.2023", "01.01.2023", inclusive=True) == 1
    assert dc.days_between("01.01.2023", "01.01.2023", inclusive=False) == 0
