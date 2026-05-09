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

## Настройка профиля кандидата

Отредактируйте `config/candidate_profile.yaml`:

- `skills.critical` — ключевые компетенции (вес ×3 в scoring)
- `skills.important` — важные навыки (вес ×2)
- `skills.technologies` — технологический стек (вес ×1)
- `industries.negative` — отрасли со штрафом к Score

---

## Подключение LLM

В [core/analyzer.py](core/analyzer.py) замените тело функции `analyze()` на вызов LLM API.
Сигнатура остаётся неизменной:

```python
def analyze(vacancy_text: str, profile: CandidateProfile) -> VacancyAnalysis:
    ...
```
