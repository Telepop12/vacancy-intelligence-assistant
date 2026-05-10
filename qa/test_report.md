# QA Report — 10.05.2026 10:29

> Сгенерировано: `python qa/run_functional_tests.py`

**Результат: 9 / 9 тестов прошли**

| ID | Тест | Статус | Время | Сообщение |
|---|---|---|---|---|
| TC-01 | File input mode | ✅ PASS | 207 мс | Exit 0, Match Score present |
| TC-02 | Stdin pipe mode | ✅ PASS | 183 мс | Exit 0, stdin read correctly |
| TC-03 | Interactive input (simulated) | ✅ PASS | 181 мс | Exit 0, text+terminator processed |
| TC-04 | Markdown report created | ✅ PASS | 153 мс | analysis_20260510_102915.md — all sections present |
| TC-05 | JSON report created | ✅ PASS | 196 мс | analysis_20260510_102916.json — valid, score=85 |
| TC-06 | Registry CSV updated | ✅ PASS | 193 мс | New entry added: score=85, rec=ОТКЛИКАТЬСЯ |
| TC-07 | Strong vacancy → ОТКЛИКАТЬСЯ | ✅ PASS | 180 мс | Recommendation: ОТКЛИКАТЬСЯ ✓ |
| TC-08 | Weak vacancy → ПРОПУСТИТЬ | ✅ PASS | 171 мс | Recommendation: ПРОПУСТИТЬ ✓ |
| TC-09 | AI transformation → УТОЧНИТЬ (45–65) | ✅ PASS | 175 мс | УТОЧНИТЬ, score=56 |