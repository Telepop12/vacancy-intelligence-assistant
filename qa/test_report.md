# QA Report — 11.05.2026 18:12

> Сгенерировано: `python qa/run_functional_tests.py`

**Результат: 10 / 10 тестов прошли**

| ID | Тест | Статус | Время | Сообщение |
|---|---|---|---|---|
| TC-01 | File input mode | ✅ PASS | 18251 мс | Exit 0, Match Score present |
| TC-02 | Stdin pipe mode | ✅ PASS | 1560 мс | Exit 0, stdin read correctly |
| TC-03 | Interactive input (simulated) | ✅ PASS | 1719 мс | Exit 0, text+terminator processed |
| TC-04 | Markdown report created | ✅ PASS | 13886 мс | analysis_20260511_181110.md — all sections present |
| TC-05 | JSON report created | ✅ PASS | 15473 мс | analysis_20260511_181124.json — valid, score=85 |
| TC-06 | Registry CSV updated | ✅ PASS | 14186 мс | New entry added: score=85, rec=ОТКЛИКАТЬСЯ |
| TC-07 | Strong vacancy → ОТКЛИКАТЬСЯ | ✅ PASS | 15487 мс | Recommendation: ОТКЛИКАТЬСЯ ✓ |
| TC-08 | Weak vacancy → ПРОПУСТИТЬ | ✅ PASS | 8648 мс | Recommendation: ПРОПУСТИТЬ ✓ |
| TC-09 | AI transformation → не ПРОПУСТИТЬ (45–65) | ✅ PASS | 16592 мс | ЗАПУСТИТЬ В РАБОТУ, score=56 |
| TC-10 | AI CoE → ЗАПУСТИТЬ В РАБОТУ | ✅ PASS | 12124 мс | ЗАПУСТИТЬ В РАБОТУ, rule-based score=23 |