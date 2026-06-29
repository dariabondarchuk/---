"""Юнит-тесты калькулятора сумм. Это фундамент — суммы не должны галлюцинироваться."""

import pytest

from tools import penalty_calculator as pc


def test_penalty_delay_basic():
    # 5 000 000 * (1/150) * 30 дней = 1 000 000
    assert pc.penalty_delay(5_000_000, 30, 1 / 150) == 1_000_000.00


def test_penalty_delay_rounds_to_kopecks():
    result = pc.penalty_delay(1_234_567, 17, 1 / 300)
    assert result == round(1_234_567 * (1 / 300) * 17, 2)
    # ровно 2 знака после запятой
    assert result == round(result, 2)


def test_penalty_delay_zero_days():
    assert pc.penalty_delay(5_000_000, 0, 1 / 150) == 0.0


def test_penalty_delay_negative_raises():
    with pytest.raises(ValueError):
        pc.penalty_delay(-1, 10, 0.01)
    with pytest.raises(ValueError):
        pc.penalty_delay(100, -1, 0.01)


def test_cap_3_percent():
    assert pc.cap_3_percent(5_000_000) == 150_000.00
    assert pc.cap_3_percent(0) == 0.0


def test_apply_cap_limits_amount():
    # Заявлено больше лимита -> ограничиваем лимитом 3%
    assert pc.apply_cap(500_000, 5_000_000) == 150_000.00
    # Заявлено меньше лимита -> остаётся как есть
    assert pc.apply_cap(50_000, 5_000_000) == 50_000.00


def test_apply_art_333_default():
    assert pc.apply_art_333(1_000_000) == 300_000.00


def test_apply_art_333_custom_factor():
    assert pc.apply_art_333(1_000_000, 0.5) == 500_000.00


def test_apply_art_333_invalid_factor():
    with pytest.raises(ValueError):
        pc.apply_art_333(1000, 1.5)


def test_fine_consumer():
    assert pc.fine_consumer(200_000) == 100_000.00
