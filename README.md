# Vacancy Intelligence Assistant

Python CLI-приложение для анализа вакансий уровня **CIO / Директор по ИТ / CTO / CDTO**.

Принимает текст вакансии, сравнивает с профилем кандидата и формирует структурированный отчёт:
Match Score, рекомендацию, ключевые совпадения, риски, вопросы к HR, шаблон ответа и советы по резюме.

---

## Установка

```bash
cd vacancy_ai_assistant
pip install -r requirements.txt
```

Требуется **Python 3.11+**.

---

## Использование

### Анализ из файла

```bash
python main.py --file data/sample_vacancy.txt
```

### Через pipe (stdin)

```bash
cat data/sample_vacancy.txt | python main.py
```

### Интерактивный ввод

```bash
python main.py
# Введите текст вакансии, завершите строкой «.»
```

### Все параметры

```
python main.py [--file PATH] [--profile YAML] [--output DIR] [--no-registry]

  -f, --file PATH      Путь к .txt файлу с вакансией
  -p, --profile YAML   Профиль кандидата (по умолчанию: config/candidate_profile.yaml)
  -o, --output DIR     Директория для отчётов (по умолчанию: output/)
  --no-registry        Не добавлять запись в output/registry.csv
```

---

## Структура вывода

| Поле | Описание |
|---|---|
| **Match Score** | 0–100, совпадение с профилем кандидата |
| **Рекомендация** | ✅ ОТКЛИКАТЬСЯ (≥70) / ⚠️ УТОЧНИТЬ (45–69) / 🚫 ПРОПУСТИТЬ (<45) |
| **Ключевые совпадения** | Найденные навыки и компетенции из профиля |
| **Риски** | Красные флаги и несоответствия |
| **Вопросы к HR** | Список уточняющих вопросов перед откликом |
| **Шаблон ответа HR** | Готовое письмо на русском языке |
| **Рекомендации по резюме** | Советы по адаптации резюме под вакансию |

Каждый запуск сохраняет два файла в `output/` и строку в `output/registry.csv`:

```
output/
├── analysis_20260509_143022.md
├── analysis_20260509_143022.json
└── registry.csv
```

---

## Структура проекта

```
vacancy_ai_assistant/
├── main.py                        # CLI — точка входа
├── requirements.txt
├── README.md
├── config/
│   └── candidate_profile.yaml     # Профиль кандидата (редактируется)
├── core/
│   ├── models.py                  # Dataclass-модели и enum Recommendation
│   ├── analyzer.py                # Анализатор (placeholder → LLM)
│   ├── scoring.py                 # Keyword-based scoring с весами
│   └── report.py                  # Генерация Markdown, JSON, CSV
├── data/
│   └── sample_vacancy.txt         # Пример вакансии для теста
└── output/                        # Результаты (создаётся автоматически)
```

---

## Модель скоринга

Score считается как взвешенная сумма по 6 категориям. Внутри категории достаточно найти ~50% ключевых слов для получения полного балла — частичное совпадение засчитывается.

| Категория | Вес | Что проверяет |
|---|---|---|
| `role_fit` | 25 | Название роли и стратегические сигналы (CIO, ИТ-стратегия…) |
| `management_scope` | 20 | Масштаб управления (команда, бюджет, портфель проектов…) |
| `digital_ai_transformation` | 20 | Цифровизация, AI, ERP/1С, BI, MDM, автоматизация |
| `infrastructure_and_it_ops` | 15 | ITSM/ITIL, ИБ, инфраструктура, облако, DevOps |
| `business_scale` | 10 | Масштаб бизнеса (сотрудники, бюджет, холдинг…) |
| `industry_fit` | 10 | Предпочтительные отрасли (производство, логистика…) |

**Риски** формируются только по явным red flags: junior/middle роль, отсутствие управленческого контура, sales-роль, нежелательная отрасль, слишком короткое описание.

---

## Настройка профиля кандидата

Отредактируйте `config/candidate_profile.yaml`:

- `scoring_groups.<name>.keywords` — ключевые слова категории
- `scoring_groups.<name>.weight` — вес категории (сумма должна быть 100)
- `red_flags.<name>` — список фраз, при совпадении которых генерируется риск

---

## Vacancy Intake Pipeline

Единый ingestion-слой для вакансий из любых источников. Analysis layer никогда не работает напрямую с raw text — все входящие данные проходят нормализацию через `agents/intake.py`.

### Поддерживаемые источники

| Source Type | Метод | Описание |
|---|---|---|
| `text` | `from_text()` | Raw text string (stdin, paste) |
| `file` | `from_file()` | .txt / .md / .json файл |
| `html` | `from_html()` | Raw HTML с парсингом тегов |
| `json` | `from_json()` | Structured JSON (hh.ru API-совместимый) |
| `url` | `from_url()` | Stub — future Playwright/requests |

### VacancyInput schema

```python
@dataclass
class VacancyInput:
    source_type:         SourceType        # text | file | url | html | json
    source_name:         str               # filename или "stdin"
    raw_text:            str               # оригинальный текст
    normalized_text:     str               # clean input для анализатора
    title:               str               # extracted job title
    company:             str               # extracted company name
    location:            str               # extracted location
    salary:              str               # extracted salary
    url:                 str
    detected_language:   str               # ru | en | mixed
    ingestion_timestamp: datetime
    intake_confidence:   IntakeConfidence  # HIGH | MEDIUM | LOW
    confidence_notes:    list[str]         # причины снижения confidence
    metadata:            dict
```

### Normalization pipeline

1. Unicode NFC нормализация
2. Unescaping HTML entities (`&nbsp;` → пробел и т.д.)
3. Удаление HTML-тегов (если есть)
4. Удаление zero-width и soft-hyphen символов
5. Схлопывание пробелов и пустых строк
6. Удаление декоративных строк (`---`, `===`, `•••`)
7. Strip каждой строки

### Intake Confidence

| Уровень | Условие |
|---|---|
| **HIGH** | Текст ≥ 300 символов, заголовок найден, есть стандартные секции |
| **MEDIUM** | Текст 100–300 символов или нет заголовка/секций |
| **LOW** | Текст < 100 символов, ошибка парсинга, файл не найден |

### Future integrations

Добавить новый источник = написать одну функцию `from_X()` + добавить `SourceType.X`. Analysis layer не меняется.

Планируемые адаптеры: hh.ru API, LinkedIn, Telegram, Gmail, Google Docs.

---

## Decision Intelligence Layer

Финальный слой синтеза, объединяющий все сигналы в единое executive-level заключение.

### Архитектура синтеза

```
Deterministic Scoring
  ↓
Semantic LLM Analysis (Claude)
  ↓
Evolutionary Potential Evaluation
  ↓
recommendation_engine.synthesize()   ← Decision Intelligence Layer
  ↓
Final Recommendation + Explainability
```

### Новые поля анализа

| Поле | Описание |
|---|---|
| **strategic_rationale** | Объяснение итоговой рекомендации с учётом всех факторов |
| **career_risks** | Конкретные карьерные риски: operational trap, weak authority, delivery-heavy |
| **career_opportunities** | Конкретные возможности: board access, AI ownership, ROI visibility |
| **best_case_scenario** | Лучший сценарий карьерного развития через эту роль |
| **worst_case_scenario** | Реалистичный худший сценарий — чего следует опасаться |
| **strategic_validation_questions** | Вопросы для проверки реального upside перед откликом |

### Логика синтеза рекомендации

Рекомендация определяется **не только** по score. Пример:

```
score = 20  (rule-based: ПРОПУСТИТЬ)
evolutionary_potential = High
executive_visibility = High
AI_trajectory_relevance = High

→ recommended_action = ЗАПУСТИТЬ В РАБОТУ
```

### Explainability

Все рекомендации explainable — система показывает:
- `strategic_rationale`: почему именно такая рекомендация
- `career_risks` / `career_opportunities`: полный баланс рисков и возможностей
- `best_case_scenario` / `worst_case_scenario`: диапазон исходов
- `strategic_validation_questions`: что уточнить перед принятием решения

Никаких black-box решений: каждая рекомендация подкреплена конкретными аргументами.

### Fallback-безопасность

`recommendation_engine.synthesize()` работает в двух режимах:
1. **LLM подключён** — валидирует и дополняет вывод Claude, не перезаписывая его
2. **LLM недоступен** — генерирует детерминированный контент на основе scoring данных

Claude failure не ломает систему: все 6 новых полей всегда заполнены.

---

## Evolutionary Potential Analysis

Помимо keyword scoring система оценивает **стратегический потенциал** вакансии как точки входа в AI leadership — даже если роль формально не является CIO/CDTO.

### Рекомендации

| Статус | Смысл |
|---|---|
| ✅ **ОТКЛИКАТЬСЯ** | Прямое совпадение профиля, score ≥ 70 |
| ⚠️ **УТОЧНИТЬ** | Частичное совпадение, нужны уточнения |
| 🚀 **ЗАПУСТИТЬ В РАБОТУ** | Невысокий keyword fit, но высокий эволюционный потенциал |
| 🚫 **ПРОПУСТИТЬ** | Низкий fit, нет стратегического потенциала |

### Факторы Evolutionary Potential

| Фактор | Сигналы |
|---|---|
| **Organizational Visibility** | Прямой доступ к CEO / board, защита проектов |
| **AI Maturity Signals** | Новое AI-направление, ранняя стадия adoption |
| **Scope Expansion** | Ownership AI-инициатив, кросс-функциональное влияние |
| **ROI Gravity** | Measurable ROI, автоматизация, снижение затрат |
| **Executive Exposure** | Участие в стратегических сессиях |

**High** (3+ сигнала) → `ЗАПУСТИТЬ В РАБОТУ` &nbsp;|&nbsp; **Medium** (1–2) → `УТОЧНИТЬ` &nbsp;|&nbsp; **Low** → без изменений

---

## Архитектура анализаторов

```
core/
├── analyzers/
│   ├── base.py               ← BaseAnalyzer (ABC)
│   ├── rule_based.py         ← RuleBasedAnalyzer (keyword scoring)
│   ├── hybrid.py             ← HybridAnalyzer (rule-based + LLM placeholders)
│   └── claude_analyzer.py   ← ClaudeAnalyzer (full semantic + DI layer)
├── recommendation_engine.py ← Decision Intelligence (synthesis + fallback)
└── analyzer.py              ← analyze() — публичная точка входа
```

По умолчанию `analyze()` использует **HybridAnalyzer**: запускает rule-based scoring и заполняет LLM-поля плейсхолдером «Ожидает подключения LLM».

### Подключение LLM

Переопределите `_fill_llm_insights()` в субклассе и замените анализатор:

```python
from core.analyzers.hybrid import HybridAnalyzer
from core import analyzer as core_analyzer

class ClaudeAnalyzer(HybridAnalyzer):
    def _fill_llm_insights(self, analysis, vacancy_text, profile):
        # вызов Claude API
        analysis.semantic_summary = claude_client.call(...)
        analysis.role_level_fit = ...

core_analyzer._analyzer = ClaudeAnalyzer()
```

### LLM-поля в `VacancyAnalysis`

| Поле | Описание |
|---|---|
| `semantic_summary` | Общее семантическое резюме вакансии |
| `role_level_fit` | Соответствие уровню роли (C-level vs middle management) |
| `strategic_vs_operational_balance` | Баланс стратегических и операционных задач |
| `target_role_alignment` | Соответствие целевым позициям кандидата |
| `authority_signals` | Сигналы реальных полномочий (бюджет, команда, совет директоров) |

---

## Web UI / Docker

### Запуск через Docker (рекомендуется)

```bash
docker compose up --build
```

Приложение будет доступно по адресу: **http://localhost:8000**

Отчёты сохраняются в `output/` на хосте (примонтирован как volume).

### Запуск локально (без Docker)

```bash
pip install -r requirements.txt
uvicorn web.app:app --reload --port 8000
```

### Smoke test (пока сервер запущен)

```bash
python web/smoke_test.py
```

Проверяет 5 ключевых сценариев: health check, главная страница, анализ вакансии, обработка пустого ввода, наличие рекомендации в результате.

### Структура web/

```
web/
├── app.py              # FastAPI-приложение
├── smoke_test.py       # Smoke test (запускать при работающем сервере)
├── templates/
│   ├── index.html      # Форма ввода вакансии
│   └── result.html     # Страница результата
└── static/
    └── style.css       # Стили
```

---

## Функциональное тестирование

В папке `qa/` находится базовый QA-контур для проверки работоспособности после изменений.

### Запуск

```bash
python qa/run_functional_tests.py
```

### Что проверяется (8 тест-кейсов)

| TC | Тест | Тип |
|---|---|---|
| TC-01 | Анализ из файла (`--file`) | Авто |
| TC-02 | Анализ через stdin pipe | Авто |
| TC-03 | Интерактивный ввод (симуляция) | Авто |
| TC-04 | Markdown-отчёт создан со всеми секциями | Авто |
| TC-05 | JSON-отчёт валиден и содержит все поля | Авто |
| TC-06 | `registry.csv` обновлён новой записью | Авто |
| TC-07 | Сильная CIO-вакансия → `ОТКЛИКАТЬСЯ` | Авто |
| TC-08 | Слабая helpdesk-вакансия → `ПРОПУСТИТЬ` | Авто |

Результаты записываются в `qa/test_report.md`. Полное описание кейсов — в `qa/test_cases.md`.

---

## Подключение LLM

В [core/analyzer.py](core/analyzer.py) замените тело функции `analyze()` на вызов LLM API.
Сигнатура остаётся неизменной:

```python
def analyze(vacancy_text: str, profile: CandidateProfile) -> VacancyAnalysis:
    ...
```
