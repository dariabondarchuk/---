"""Супервизор-оркестратор: связывает агентов в конвейер.

Реализован как генератор событий, чтобы интерфейс (Streamlit) мог:
  * показывать ход работы простыми словами (события "progress");
  * приостановиться и спросить пользователя (событие "question"),
    получив ответы через .send(answers);
  * выдать готовый результат (событие "done").

Конвейер: Аналитик → Планировщик → [вопросы юристу] → Исследователь(каждое
требование) → Генератор → Критик (до 3 кругов) → сборка .docx.

В агентов уходит ТОЛЬКО обезличенный текст. Реальные ПДн восстанавливаются
в самом конце, локально, при сборке .docx (tools.docx_writer).
"""

from __future__ import annotations

from agents import analyst, critic, generator, planner, researcher
from tools.docx_writer import build_objection_docx

MAX_GEN_CRITIC_LOOPS = 3

# Человекочитаемые названия типов требований — для понятных сообщений и заголовков.
TYPE_LABELS = {
    "defects": "недостатки объекта",
    "penalty_defects": "неустойка за недостатки",
    "penalty_delay": "неустойка за просрочку передачи",
    "fine": "штраф",
    "moral": "компенсация морального вреда",
    "legal_costs": "судебные расходы",
}


def _label(rtype: str) -> str:
    return TYPE_LABELS.get(rtype, rtype)


def run_pipeline(isk_anon: str, ddu_anon: str, pii_map: dict, output_path: str):
    """Запустить конвейер. Генератор событий (см. модульный docstring).

    yield ("progress", str)         — сообщение о ходе работы;
    yield ("question", {...})       — нужен ответ юриста; ответы приходят через .send();
    yield ("done", {...})           — финал: путь к .docx и краткое резюме.
    """
    # 1. АНАЛИЗ
    yield ("progress", "Анализирую иск…")
    analyst_input = (
        "=== ТЕКСТ ИСКОВОГО ЗАЯВЛЕНИЯ ===\n"
        f"{isk_anon}\n\n"
        "=== ТЕКСТ ДДУ (для реквизитов, цены и дат) ===\n"
        f"{ddu_anon}"
    )
    analysis = analyst.analyze(analyst_input)
    facts = analysis.get("facts", {})
    requirements = analysis.get("requirements", [])
    labels = ", ".join(_label(r.get("type", "")) for r in requirements) or "не найдено"
    yield ("progress", f"Нашёл требования ({len(requirements)}): {labels}.")
    if analysis.get("ocr_warnings"):
        yield ("progress", "Внимание: в тексте есть сомнительные места (возможен плохой скан).")

    # 2. ПЛАН
    yield ("progress", "Составляю план возражения…")
    planning = planner.plan(analysis)

    # 3. ВОПРОСЫ ЮРИСТУ (human-in-the-loop)
    human_answers: dict[str, str] = {}
    open_questions = list(planning.get("open_questions", []))
    open_questions += [f"Подтвердите данные: {w}" for w in analysis.get("ocr_warnings", [])]
    if open_questions:
        answers = yield ("question", {"questions": open_questions})
        human_answers = answers or {}
        yield ("progress", "Спасибо, учитываю ваши уточнения.")

    # 4. ИССЛЕДОВАНИЕ (суммы считает калькулятор, не модель)
    yield ("progress", "Считаю суммы и подбираю нормы по каждому требованию…")
    research_items: list[dict] = []
    for req in requirements:
        yield ("progress", f"  • прорабатываю: {_label(req.get('type', ''))}…")
        research_items.append(researcher.research(req, facts))

    # 5. ГЕНЕРАЦИЯ + 6. КРИТИКА (цикл с лимитом)
    draft = None
    critic_result = {"verdict": "FAIL", "issues": []}
    for loop in range(1, MAX_GEN_CRITIC_LOOPS + 1):
        yield ("progress", f"Пишу черновик возражения… (попытка {loop})")
        draft = generator.generate(planning, facts, research_items, human_answers)
        yield ("progress", "Проверяю черновик на полноту и обоснованность…")
        critic_result = critic.review(analysis, draft, research_items)
        if critic_result.get("verdict") == "PASS":
            yield ("progress", "Проверка пройдена.")
            break
        blockers = [i for i in critic_result.get("issues", []) if i.get("severity") == "blocker"]
        if not blockers:
            yield ("progress", "Замечания только стилистические — продолжаю.")
            break
        yield ("progress", f"Критик нашёл {len(blockers)} серьёзных замечаний — дорабатываю.")
    else:
        yield ("progress", "Достигнут лимит доработок — соберу лучший черновик с пометкой.")

    # 7. СБОРКА .docx (ПДн восстанавливаются здесь, локально)
    yield ("progress", "Собираю итоговый документ (.docx) и возвращаю реальные данные…")
    sections = dict(draft.get("sections", {}))
    blockers = [i for i in critic_result.get("issues", []) if i.get("severity") == "blocker"]
    if critic_result.get("verdict") != "PASS" and blockers:
        notes = "; ".join(i.get("message", "") for i in blockers)
        sections = {"⚠ ТРЕБУЕТ РУЧНОЙ ДОРАБОТКИ": f"Критик отметил: {notes}", **sections}

    build_objection_docx(
        facts=facts,
        sections=sections,
        proshu_sud=draft.get("proshu_sud", []),
        prilozheniya=draft.get("prilozheniya", []),
        pii_map=pii_map,
        output_path=output_path,
    )

    summary = {
        "path": output_path,
        "requirements": [
            {"type": _label(r.get("type", "")), "amount_claimed": r.get("amount_claimed")}
            for r in requirements
        ],
        "verdict": critic_result.get("verdict"),
        "issues": critic_result.get("issues", []),
    }
    yield ("done", summary)
