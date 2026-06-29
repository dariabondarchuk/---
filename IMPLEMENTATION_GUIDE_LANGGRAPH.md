# Пошаговая инструкция: мультиагентный генератор возражений (LangGraph)

Этот документ — спутник к `CURSOR_PROMPT.md`. Промпт заставляет Cursor сгенерировать каркас; здесь — пояснения, ключевые куски кода и порядок сборки, чтобы ты понимала, что именно делает Cursor, и могла поправить.

Стек: **Python 3.11+, LangGraph, LangChain, pydantic v2, Chroma (RAG), python-docx, Natasha (анонимизация ПДн), Tesseract (OCR).**

---

## 0. Что мы строим (карта графа)

```
                          ┌─────────────┐
                   ┌─────▶│  SUPERVISOR │◀──────┐
                   │      └──────┬──────┘       │
        (роутинг по состоянию)   │   (агрегация результатов нод)
                   │             ▼              │
   ┌────────┬──────┴────┬────────────┬──────────┴──┬───────────┐
   ▼        ▼           ▼            ▼             ▼            ▼
ANALYST  PLANNER   INTERVIEWER  RESEARCHER     GENERATOR    CRITIC
декомп.  план +    вопросы      tools/subagents сборка       проверка
иска     контроль  человеку     RAG/калькулятор .docx        всех нод
                   (interrupt)  /нормы
```

Принцип: **ноды не вызывают друг друга напрямую.** Каждая нода отработала → вернула управление Супервизору → Супервизор по состоянию решает, кто следующий (это и есть «supervisor pattern» в LangGraph). Это даёт контролируемые циклы и точку, где легко вставить лимиты и логи.

---

## ШАГ 1. Каркас и зависимости

`pyproject.toml` (ключевые зависимости):
```toml
[project]
dependencies = [
  "langgraph>=0.2.0",
  "langchain>=0.3.0",
  "langchain-anthropic>=0.2.0",   # или langchain-openai
  "pydantic>=2.6",
  "chromadb>=0.5.0",
  "python-docx>=1.1.0",
  "docxtpl>=0.18.0",
  "natasha>=1.6.0",               # NER для русских ФИО/адресов
  "pytesseract>=0.3.10",          # OCR сканов
  "pdf2image>=1.17.0",
  "pdfplumber>=0.11.0",
  "python-dotenv>=1.0.0",
]
```

`.env.example`:
```
ANTHROPIC_API_KEY=
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-5
LLM_TEMPERATURE=0.1
CHROMA_PATH=./.chroma
MAX_TOTAL_ITERATIONS=12
MAX_GENERATE_CRITIC_LOOPS=3
```

---

## ШАГ 2. State — сердце системы (`state.py`)

Всё состояние графа — один объект. Ноды читают из него и дописывают в него.

```python
from __future__ import annotations
from enum import Enum
from typing import Annotated, Literal
from pydantic import BaseModel, Field
import operator


class RequirementType(str, Enum):
    DEFECTS = "defects"            # недостатки / уменьшение цены
    PENALTY_DEFECTS = "penalty_defects"
    PENALTY_DELAY = "penalty_delay"   # просрочка передачи объекта
    FINE = "fine"                  # штраф
    MORAL = "moral"                # моральный вред
    LEGAL_COSTS = "legal_costs"    # судебные расходы


class Requirement(BaseModel):
    type: RequirementType
    amount_claimed: float | None = None       # сумма из иска
    description: str = ""
    source_quote: str = ""                    # цитата из ИЗ (трассируемость)


class CaseFacts(BaseModel):
    case_number: str = ""
    court: str = ""
    plaintiff: str = ""
    defendant: str = ""
    ddu_number: str = ""
    ddu_date: str = ""
    handover_date: str = ""          # дата акта приёма-передачи
    contract_price: float | None = None
    confidence: float = 1.0          # уверенность OCR/извлечения


class ResearchItem(BaseModel):
    requirement: RequirementType
    tool_used: str                   # rag / penalty_calculator / legal_norms ...
    content: str
    citation: str                    # источник: норма, дело, расчёт


class CriticIssue(BaseModel):
    severity: Literal["blocker", "minor"]
    where: str                       # к какой ноде/разделу относится
    message: str


class AgentState(BaseModel):
    # вход
    isk_text: str = ""               # текст искового (после OCR+анонимизации)
    ddu_text: str = ""
    pii_map: dict[str, str] = Field(default_factory=dict)  # для восстановления ПДн

    # результаты нод
    facts: CaseFacts | None = None
    requirements: list[Requirement] = Field(default_factory=list)
    plan: list[str] = Field(default_factory=list)          # TODO-разделы
    open_questions: list[str] = Field(default_factory=list)
    human_answers: dict[str, str] = Field(default_factory=dict)
    research: list[ResearchItem] = Field(default_factory=list)
    draft_docx_path: str | None = None
    draft_sections: dict[str, str] = Field(default_factory=dict)
    critic_issues: list[CriticIssue] = Field(default_factory=list)

    # управление (для Супервизора)
    next_node: str = "analyst"
    total_iterations: int = 0
    gen_critic_loops: int = 0
    log: Annotated[list[str], operator.add] = Field(default_factory=list)
    finished: bool = False
```

> Совет: `next_node` — ключевое поле. Супервизор пишет в него имя следующей ноды, а условное ребро графа читает его.

---

## ШАГ 3. Инструменты (`tools/`)

### 3.1 Анонимизатор (`tools/anonymizer.py`) — обязателен до облака
```python
import re
from natasha import Segmenter, NewsEmbedding, NewsNERTagger, Doc

_seg = Segmenter()
_ner = NewsNERTagger(NewsEmbedding())

PATTERNS = {
    "PHONE": r"\+?7[\s\-(]?\d{3}[\s\-)]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",
    "EMAIL": r"[\w.\-]+@[\w.\-]+\.\w+",
    "INN":   r"\b\d{10,12}\b",
    "SNILS": r"\b\d{3}-\d{3}-\d{3}\s?\d{2}\b",
    "PASSPORT": r"\b\d{4}\s?\d{6}\b",
}

def anonymize(text: str) -> tuple[str, dict[str, str]]:
    """Возвращает обезличенный текст и карту замен для восстановления."""
    mapping: dict[str, str] = {}
    counter: dict[str, int] = {}

    def sub(kind: str, value: str) -> str:
        counter[kind] = counter.get(kind, 0) + 1
        token = f"[{kind}_{counter[kind]}]"
        mapping[token] = value
        return token

    # regex-сущности
    for kind, pat in PATTERNS.items():
        text = re.sub(pat, lambda m: sub(kind, m.group()), text)

    # ФИО / адреса через Natasha
    doc = Doc(text)
    doc.segment(_seg)
    doc.tag_ner(_ner)
    # заменяем с конца, чтобы не сбить offsets
    for span in sorted(doc.spans, key=lambda s: s.start, reverse=True):
        if span.type in ("PER", "LOC"):
            token = sub(span.type, span.text)
            text = text[:span.start] + token + text[span.stop:]
    return text, mapping

def restore(text: str, mapping: dict[str, str]) -> str:
    for token, value in mapping.items():
        text = text.replace(token, value)
    return text
```

### 3.2 Калькулятор неустойки (`tools/penalty_calculator.py`) — детерминированный, не доверяем LLM арифметику
```python
from datetime import date

def penalty_delay(price: float, days_overdue: int, rate: float) -> float:
    """Неустойка за просрочку передачи. rate — дневная ставка (доля)."""
    return round(price * rate * days_overdue, 2)

def cap_3_percent(price: float) -> float:
    """Лимит взыскания по ч.4 ст.10 ФЗ-214 — 3% цены договора."""
    return round(price * 0.03, 2)

def apply_art_333(amount: float, factor: float = 0.3) -> float:
    """Ориентировочное снижение по ст.333 ГК (аргумент в возражении)."""
    return round(amount * factor, 2)
```
Под каждый — юнит-тест в `tests/test_calculator.py`. Это то, что **никогда** не должно галлюцинироваться.

### 3.3 RAG (`tools/rag.py`)
```python
import chromadb
from chromadb.utils import embedding_functions

def get_collection(path: str):
    client = chromadb.PersistentClient(path=path)
    return client.get_or_create_collection(
        "objections",
        embedding_function=embedding_functions.DefaultEmbeddingFunction(),
    )

def rag_search(collection, query: str, k: int = 4) -> list[dict]:
    res = collection.query(query_texts=[query], n_results=k)
    return [
        {"text": doc, "citation": meta.get("source", "kb")}
        for doc, meta in zip(res["documents"][0], res["metadatas"][0])
    ]
```
Индексацию эталонных возражений (твоих PDF) делает `scripts/ingest_kb.py`: режет каждый эталон по разделам (ФАКТЫ / НЕДОСТАТКИ / НЕУСТОЙКА / ШТРАФ / ...) и кладёт с метаданными.

### 3.4 OCR (`tools/ocr.py`)
```python
import pytesseract, pdfplumber
from pdf2image import convert_from_path

def extract_text(pdf_path: str) -> tuple[str, float]:
    """Сначала пробуем текстовый слой; если пусто — OCR. Возвращаем (текст, confidence)."""
    with pdfplumber.open(pdf_path) as pdf:
        native = "\n".join(p.extract_text() or "" for p in pdf.pages)
    if len(native.strip()) > 100:
        return native, 1.0
    # скан → OCR
    pages = convert_from_path(pdf_path, dpi=300)
    text, confs = [], []
    for img in pages:
        data = pytesseract.image_to_data(img, lang="rus",
                                         output_type=pytesseract.Output.DICT)
        words = [w for w in data["text"] if w.strip()]
        page_conf = [int(c) for c in data["conf"] if c not in ("-1", -1)]
        text.append(" ".join(words))
        confs += page_conf
    confidence = (sum(confs) / len(confs) / 100) if confs else 0.0
    return "\n".join(text), round(confidence, 2)
```
Низкий `confidence` → Планировщик добавит вопрос Интервьюеру.

---

## ШАГ 4. Промпты агентов (`prompts/*.md`)

Каждый промпт — отдельный файл. Скелеты:

**`analyst.md`**
```
Ты — Аналитик. На вход — текст искового заявления дольщика (обезличенный).
Извлеки строго в JSON: реквизиты (суд, № дела, истец, ответчик), данные ДДУ
(номер, дата), дату передачи объекта, цену договора, и СПИСОК требований истца
по типам: defects, penalty_defects, penalty_delay, fine, moral, legal_costs —
с заявленной суммой и дословной цитатой-основанием из иска.
Не выдумывай суммы. Если данных нет — null. Только JSON, без пояснений.
```

**`planner.md`**
```
Ты — Планировщик. На вход — список требований и факты дела. Составь план разделов
возражения (по одному на каждое требование + «Фактические обстоятельства»,
«Ходатайство об отсрочке», «ПРОШУ СУД», «Приложения»). Для каждого раздела укажи,
какие данные/материалы нужны (нормы, расчёты, RAG). Если каких-то фактов не хватает
или confidence низкий — сформируй список вопросов пользователю (open_questions).
Верни JSON: {plan: [...], open_questions: [...]}.
```

**`researcher.md`**
```
Ты — Исследователь. Для каждого требования собери материалы, ВЫЗЫВАЯ ИНСТРУМЕНТЫ:
rag_search (эталонные аргументы и практика), legal_norms (ФЗ-214 ст.7/10, ГК ст.333,
ПП РФ № 326), penalty_calculator / date_calculator (суммы и периоды).
Каждый тезис должен иметь citation. Не пиши финальный текст — только материалы.
```

**`critic.md`**
```
Ты — Критик. Проверь черновик против списка требований и собранных материалов:
1) на каждое требование есть раздел; 2) каждая сумма/дата трассируется к источнику
(иск/ДДУ/расчёт); 3) ссылки на нормы корректны; 4) нет утверждений без citation;
5) есть лимит 3%, ст.333, ходатайство об отсрочке, «ПРОШУ СУД».
Верни JSON: {verdict: "PASS"|"FAIL", issues: [{severity, where, message}]}.
```

**`generator.md`** — даёт структуру документа (см. ШАГ 6, шаблон).
**`supervisor.md`** — правила маршрутизации (см. ниже).
**`interviewer.md`** — как формулировать короткие вопросы пользователю.

---

## ШАГ 5. Ноды (`nodes/*.py`)

Каждая нода — функция `(_state) -> dict` (возвращает патч состояния). Пример Аналитика:

```python
import json
from state import AgentState, Requirement, CaseFacts
from llm import get_llm
from pathlib import Path

ANALYST_PROMPT = Path("prompts/analyst.md").read_text(encoding="utf-8")

def analyst_node(state: AgentState) -> dict:
    llm = get_llm()
    resp = llm.invoke([
        {"role": "system", "content": ANALYST_PROMPT},
        {"role": "user", "content": state.isk_text},
    ])
    data = json.loads(resp.content)
    facts = CaseFacts(**data["facts"])
    reqs = [Requirement(**r) for r in data["requirements"]]
    return {
        "facts": facts,
        "requirements": reqs,
        "log": [f"[Analyst] требований: {len(reqs)}, дело {facts.case_number}"],
        "next_node": "supervisor",
    }
```

Супервизор — маршрутизатор:
```python
from config import MAX_TOTAL_ITERATIONS, MAX_GENERATE_CRITIC_LOOPS

def supervisor_node(state: AgentState) -> dict:
    it = state.total_iterations + 1
    if it > MAX_TOTAL_ITERATIONS:
        return {"next_node": "END", "finished": True,
                "log": ["[Supervisor] лимит итераций, выходим"]}

    # порядок этапов по наличию результатов в state
    if state.facts is None:
        nxt = "analyst"
    elif not state.plan:
        nxt = "planner"
    elif state.open_questions and not state.human_answers:
        nxt = "interviewer"
    elif not state.research:
        nxt = "researcher"
    elif state.draft_docx_path is None:
        nxt = "generator"
    elif not state.critic_issues and state.gen_critic_loops == 0:
        nxt = "critic"                       # первая проверка
    else:
        blockers = [i for i in state.critic_issues if i.severity == "blocker"]
        if blockers and state.gen_critic_loops < MAX_GENERATE_CRITIC_LOOPS:
            nxt = "researcher" if any("источник" in b.message for b in blockers) else "generator"
        else:
            nxt = "END"
    return {"next_node": nxt, "total_iterations": it,
            "log": [f"[Supervisor] →{nxt} (итерация {it})"]}
```

Интервьюер использует прерывание графа (human-in-the-loop):
```python
from langgraph.types import interrupt

def interviewer_node(state: AgentState) -> dict:
    answers = interrupt({"questions": state.open_questions})  # граф паузится здесь
    return {"human_answers": answers, "next_node": "supervisor",
            "log": [f"[Interviewer] получено ответов: {len(answers)}"]}
```

---

## ШАГ 6. Сборка графа (`graph.py`)

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from state import AgentState
from nodes.supervisor import supervisor_node
from nodes.analyst import analyst_node
from nodes.planner import planner_node
from nodes.interviewer import interviewer_node
from nodes.researcher import researcher_node
from nodes.generator import generator_node
from nodes.critic import critic_node

def route(state: AgentState) -> str:
    return END if state.next_node in ("END", None) else state.next_node

def build_graph():
    g = StateGraph(AgentState)
    g.add_node("supervisor", supervisor_node)
    g.add_node("analyst", analyst_node)
    g.add_node("planner", planner_node)
    g.add_node("interviewer", interviewer_node)
    g.add_node("researcher", researcher_node)
    g.add_node("generator", generator_node)
    g.add_node("critic", critic_node)

    g.add_edge(START, "supervisor")
    # все рабочие ноды возвращаются к супервизору
    for n in ["analyst", "planner", "interviewer", "researcher", "generator", "critic"]:
        g.add_edge(n, "supervisor")
    # супервизор маршрутизирует по next_node
    g.add_conditional_edges("supervisor", route, {
        "analyst": "analyst", "planner": "planner",
        "interviewer": "interviewer", "researcher": "researcher",
        "generator": "generator", "critic": "critic", END: END,
    })
    return g.compile(checkpointer=MemorySaver())  # checkpointer нужен для interrupt
```

Шаблон документа (`generator_node` заполняет `templates/objection_template.docx`) повторяет структуру твоих эталонов:
```
В [СУД]
Ответчик: [реквизиты застройщика]
Истец: [ФИО]   Дело № [...]
                ВОЗРАЖЕНИЯ на исковое заявление
1. ФАКТИЧЕСКИЕ ОБСТОЯТЕЛЬСТВА ДЕЛА
2. ПО ТРЕБОВАНИЮ … О ВОЗМЕЩЕНИИ РАСХОДОВ НА УСТРАНЕНИЕ НЕДОСТАТКОВ (лимит 3%, ч.4 ст.10)
3. ПО ТРЕБОВАНИЮ … О ВЗЫСКАНИИ НЕУСТОЙКИ (+ст.333 ГК)
4. ПО ТРЕБОВАНИЮ … О НЕУСТОЙКЕ ЗА ПРОСРОЧКУ ПЕРЕДАЧИ
5. ПО ТРЕБОВАНИЮ … О ШТРАФЕ
6. ПО ТРЕБОВАНИЮ … О КОМПЕНСАЦИИ МОРАЛЬНОГО ВРЕДА
7. ПО ТРЕБОВАНИЮ … О СУДЕБНЫХ РАСХОДАХ (7.1 экспертиза / 7.2 доверенность / 7.3 представитель / 7.4 пошлина, почта)
8. ХОДАТАЙСТВО ОБ ОТСРОЧКЕ ИСПОЛНЕНИЯ (ПП РФ № 326)
   ПРОШУ СУД: …
   Приложения: …
```
Генератор включает только те разделы, типы которых реально есть в `state.requirements` (из дел видно: бывают «только неустойка», «только недостатки», «неустойка + недостатки»).

---

## ШАГ 7. Запуск и проверка

`scripts/run_cli.py` (упрощённо):
```python
from tools.ocr import extract_text
from tools.anonymizer import anonymize
from graph import build_graph
from langgraph.types import Command

isk_raw, conf = extract_text("cases/case_2/ИЗ.pdf")
ddu_raw, _ = extract_text("cases/case_2/ДДУ.pdf")
isk_anon, pii1 = anonymize(isk_raw)
ddu_anon, pii2 = anonymize(ddu_raw)

app = build_graph()
cfg = {"configurable": {"thread_id": "case-2"}}
state = {"isk_text": isk_anon, "ddu_text": ddu_anon,
         "pii_map": {**pii1, **pii2}}

result = app.invoke(state, cfg)
# если граф остановился на вопросах интервьюера:
if not result.get("finished"):
    answers = {q: input(q + " ") for q in result["open_questions"]}
    result = app.invoke(Command(resume=answers), cfg)
print("Готово:", result["draft_docx_path"])
```

Прогон smoke-теста: возьми `case_2` (самое полное — неустойка + недостатки), убедись, что:
1) Аналитик нашёл все 6 требований; 2) суммы совпали с иском; 3) в документе есть все разделы; 4) Критик дал PASS; 5) на выходе .docx с дисклеймером «ПРОЕКТ. Требует проверки юристом».

---

## Чек-лист готовности к боевому использованию
- [ ] Анонимизация прогоняется на 100% входящего текста до облака; восстановление ПДн — только в финальном .docx локально.
- [ ] Все суммы/даты считает калькулятор (детерминированно), а не LLM.
- [ ] Каждый тезис в документе имеет citation; Критик блокирует тезисы без источника.
- [ ] Лимит 3% (ч.4 ст.10 ФЗ-214), ст.333 ГК и ходатайство об отсрочке (ПП-326) присутствуют, когда применимы.
- [ ] Жёсткие лимиты итераций работают (нет вечного цикла Generator↔Critic).
- [ ] Дисклеймер о проверке юристом — в каждом документе.
- [ ] Тексты норм и ПП-326 актуализированы (проверяй редакции — мораторий/отсрочка меняются подзаконкой).

---

### Что я взял из твоих файлов
5 дел (Видновский горсуд): по каждому — исковое (скан), ДДУ и **готовые возражения юриста**. Типы исков в выборке: «неустойка», «недостатки», «устранение недостатков», «неустойка + недостатки». Структура эталонного возражения (разделы, ст. 333, лимит 3%, отсрочка по ПП-326, «ПРОШУ СУД», приложения) перенесена в шаблон Генератора и в критерии Критика. Эти эталоны — твой стартовый корпус для RAG (`scripts/ingest_kb.py`).
