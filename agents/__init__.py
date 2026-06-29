"""Агенты системы возражений в виде обычных Python-функций.

Бывшие субагенты Claude Code (analyst, planner, researcher, generator, critic)
и супервизор перенесены сюда как функции/генератор. Мозг — Google Gemini
(см. agents.llm). Работает без Claude Code, запускается из app.py (Streamlit).
"""
