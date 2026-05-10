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

## Подключение LLM

В [core/analyzer.py](core/analyzer.py) замените тело функции `analyze()` на вызов LLM API.
Сигнатура остаётся неизменной:

```python
def analyze(vacancy_text: str, profile: CandidateProfile) -> VacancyAnalysis:
    ...
```
