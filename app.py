"""Веб-приложение подготовки возражений на иски дольщиков (Streamlit).

Работает БЕЗ Claude Code. Мозг — Google Gemini (см. agents/llm.py), доступен
из России. Запуск:  streamlit run app.py

Конвейер: загрузка PDF (иск + ДДУ) → извлечение текста (OCR-фоллбэк) →
обезличивание ПДн → агенты на Gemini (обезличенный текст) → сборка .docx
(реальные ПДн возвращаются локально, в самом конце).
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import streamlit as st

from agents.llm import LLMConfigError
from agents.pipeline import run_pipeline
from tools.anonymizer import anonymize, natasha_available
from tools.ocr import NeedTextLayerError, extract_text

st.set_page_config(page_title="Возражения на иски дольщиков", page_icon="⚖️", layout="centered")

# ---------------------------------------------------------------------------
# Дисклеймер — крупная плашка сверху, видна всегда.
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div style="background:#7a1f1f;color:#fff;padding:18px 22px;border-radius:10px;
                font-size:1.05rem;line-height:1.5;">
      <b>⚠️ ВНИМАНИЕ. Это проект, подготовленный искусственным интеллектом.</b><br>
      Документ <b>не является юридической консультацией</b> и не может подаваться в
      суд без проверки. Обязательно покажите результат квалифицированному юристу:
      он отвечает за итоговую позицию, суммы и ссылки на нормы.
    </div>
    """,
    unsafe_allow_html=True,
)
st.title("⚖️ Генератор возражений на иск дольщика")
st.caption(
    "Для застройщика-ответчика (214-ФЗ). Загрузите исковое заявление и ДДУ — "
    "система подготовит ПРОЕКТ возражения в формате .docx."
)

# ---------------------------------------------------------------------------
# Инициализация состояния сессии.
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "stage": "idle",          # idle | awaiting_answers | done | error
    "log": [],
    "gen": None,
    "questions": [],
    "summary": None,
    "docx_path": None,
    "error": None,
}
for key, val in _DEFAULTS.items():
    st.session_state.setdefault(key, val)


def _reset() -> None:
    for key, val in _DEFAULTS.items():
        st.session_state[key] = val.copy() if isinstance(val, (list, dict)) else val


def _advance(send_value=None) -> None:
    """Продвинуть конвейер до следующей точки остановки (вопрос / готово / ошибка)."""
    gen = st.session_state.gen
    try:
        event = gen.send(send_value)
        while True:
            kind, data = event
            if kind == "progress":
                st.session_state.log.append(data)
                event = gen.send(None)
            elif kind == "question":
                st.session_state.questions = data["questions"]
                st.session_state.stage = "awaiting_answers"
                return
            elif kind == "done":
                st.session_state.summary = data
                st.session_state.docx_path = data["path"]
                st.session_state.stage = "done"
                return
    except StopIteration:
        st.session_state.stage = "done"
    except LLMConfigError as exc:
        st.session_state.error = str(exc)
        st.session_state.stage = "error"
    except Exception as exc:  # noqa: BLE001 - показываем пользователю любую ошибку агентов
        st.session_state.error = f"Ошибка при обработке: {exc}"
        st.session_state.stage = "error"


def _prepare(uploaded, mapping: dict) -> tuple[str, float]:
    """Сохранить PDF во временный файл, извлечь и обезличить текст.

    Возвращает (обезличенный_текст, confidence). Может бросить NeedTextLayerError.
    Найденные ПДн дописываются в общий mapping.
    """
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(uploaded.getbuffer())
        path = tmp.name
    text, conf = extract_text(path)
    anon, local_map = anonymize(text)
    mapping.update(local_map)
    return anon, conf


# ---------------------------------------------------------------------------
# Экран загрузки документов.
# ---------------------------------------------------------------------------
if st.session_state.stage == "idle":
    if not natasha_available():
        st.info(
            "Подсказка: библиотека Natasha не обнаружена — ФИО и адреса будут "
            "обезличены частично (телефоны, email, ИНН, СНИЛС, паспорт работают "
            "всегда). Для полного обезличивания установите natasha."
        )

    col1, col2 = st.columns(2)
    with col1:
        isk_file = st.file_uploader("Исковое заявление (PDF)", type=["pdf"], key="isk")
    with col2:
        ddu_file = st.file_uploader("Договор участия (ДДУ, PDF)", type=["pdf"], key="ddu")

    if st.button("Сгенерировать возражение", type="primary", disabled=not (isk_file and ddu_file)):
        pii_map: dict[str, str] = {}
        try:
            with st.spinner("Читаю PDF и обезличиваю персональные данные…"):
                isk_anon, isk_conf = _prepare(isk_file, pii_map)
                ddu_anon, _ = _prepare(ddu_file, pii_map)
        except NeedTextLayerError as exc:
            st.warning(str(exc))
            st.stop()

        out_path = str(Path(tempfile.gettempdir()) / f"vozrazhenie_{int(time.time())}.docx")
        st.session_state.gen = run_pipeline(isk_anon, ddu_anon, pii_map, out_path)
        st.session_state.log = []
        if isk_conf < 1.0:
            st.session_state.log.append(
                f"Текст иска распознан через OCR (уверенность ~{int(isk_conf * 100)}%) — "
                "проверьте ключевые данные особенно внимательно."
            )
        _advance(None)
        st.rerun()

# ---------------------------------------------------------------------------
# Ход работы (показываем простыми словами на всех «рабочих» экранах).
# ---------------------------------------------------------------------------
if st.session_state.log:
    st.subheader("Ход работы")
    for line in st.session_state.log:
        st.write("✅ " + line if not line.startswith("  ") else "    ↳ " + line.strip())

# ---------------------------------------------------------------------------
# Экран уточняющих вопросов (human-in-the-loop).
# ---------------------------------------------------------------------------
if st.session_state.stage == "awaiting_answers":
    st.subheader("Нужны уточнения")
    st.write("Чтобы продолжить, ответьте, пожалуйста, на вопросы ниже (можно кратко):")
    with st.form("clarify"):
        answers: dict[str, str] = {}
        for i, q in enumerate(st.session_state.questions):
            answers[q] = st.text_input(q, key=f"q_{i}")
        if st.form_submit_button("Продолжить", type="primary"):
            st.session_state.questions = []
            _advance(answers)
            st.rerun()

# ---------------------------------------------------------------------------
# Экран готового результата.
# ---------------------------------------------------------------------------
if st.session_state.stage == "done":
    summary = st.session_state.summary or {}
    st.success("Готово! Ниже — краткое резюме и кнопка скачивания проекта возражения.")

    if summary.get("requirements"):
        st.subheader("Требования истца")
        for r in summary["requirements"]:
            amount = r.get("amount_claimed")
            amount_str = f" — заявлено {amount:,.2f} ₽".replace(",", " ") if amount else ""
            st.write(f"• {r['type']}{amount_str}")

    verdict = summary.get("verdict")
    if verdict == "PASS":
        st.write("🟢 Внутренняя проверка (Критик): пройдена.")
    else:
        st.write("🟠 Внутренняя проверка (Критик): есть замечания — см. ниже.")
    for issue in summary.get("issues", []):
        st.write(f"  – [{issue.get('severity')}] {issue.get('where')}: {issue.get('message')}")

    docx_path = st.session_state.docx_path
    if docx_path and Path(docx_path).exists():
        with open(docx_path, "rb") as fh:
            st.download_button(
                "📄 Скачать возражение (.docx)",
                data=fh.read(),
                file_name="vozrazhenie_proekt.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary",
            )
    st.info("Напоминание: это ПРОЕКТ. Перед подачей в суд обязательна проверка юристом.")
    if st.button("Начать заново"):
        _reset()
        st.rerun()

# ---------------------------------------------------------------------------
# Экран ошибки.
# ---------------------------------------------------------------------------
if st.session_state.stage == "error":
    st.error(st.session_state.error or "Произошла ошибка.")
    if st.button("Начать заново", key="reset_err"):
        _reset()
        st.rerun()
