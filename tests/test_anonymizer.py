"""Тесты обезличивания. Проверяем, что ПДн вырезаются и восстанавливаются.

Регэксп-слой работает без внешних зависимостей, поэтому эти тесты проходят
даже без установленной Natasha (ФИО/адреса проверяются отдельно, если она есть).
"""

from tools import anonymizer as an


def test_passport_is_removed_and_restored():
    text = "Паспорт 45 11 123456 выдан отделом."
    anon, mapping = an.anonymize(text)
    assert "123456" not in anon
    assert "[PASSPORT_1]" in anon
    assert an.restore(anon, mapping) == text


def test_inn_removed():
    text = "ИНН организации 7701234567 указан в договоре."
    anon, mapping = an.anonymize(text)
    assert "7701234567" not in anon
    assert an.restore(anon, mapping) == text


def test_email_and_phone_removed():
    text = "Связь: ivanov@example.com, тел. +7 916 123-45-67."
    anon, mapping = an.anonymize(text)
    assert "ivanov@example.com" not in anon
    assert "916" not in anon
    assert "[EMAIL_1]" in anon
    assert "[PHONE_1]" in anon
    assert an.restore(anon, mapping) == text


def test_snils_removed():
    text = "СНИЛС 112-233-445 95 в материалах дела."
    anon, mapping = an.anonymize(text)
    assert "112-233-445" not in anon
    assert an.restore(anon, mapping) == text


def test_repeated_value_uses_same_token():
    text = "ИНН 7701234567 и снова ИНН 7701234567."
    anon, mapping = an.anonymize(text)
    # Одно и то же значение -> один токен, в карте одна запись для этого значения
    assert anon.count("[INN_1]") == 2
    assert list(mapping.values()).count("7701234567") == 1


def test_restore_handles_double_digit_tokens():
    # Гарантия, что [X_1] не затирает часть [X_10] при восстановлении
    mapping = {"[PER_1]": "Иванов", "[PER_10]": "Петров"}
    text = "[PER_10] против [PER_1]"
    assert an.restore(text, mapping) == "Петров против Иванов"


def test_empty_text():
    anon, mapping = an.anonymize("")
    assert anon == ""
    assert mapping == {}
