# QA Report — 10.05.2026 09:20

> Сгенерировано: `python qa/run_functional_tests.py`

**Результат: 8 / 8 тестов прошли**

| ID | Тест | Статус | Время | Сообщение |
|---|---|---|---|---|
| TC-01 | File input mode | ✅ PASS | 190 мс | Exit 0, Match Score present |
| TC-02 | Stdin pipe mode | ✅ PASS | 177 мс | Exit 0, stdin read correctly |
| TC-03 | Interactive input (simulated) | ✅ PASS | 158 мс | Exit 0, text+terminator processed |
| TC-04 | Markdown report created | ✅ PASS | 161 мс | analysis_20260510_092045.md — all sections present |
| TC-05 | JSON report created | ✅ PASS | 164 мс | analysis_20260510_092045.json — valid, score=85 |
| TC-06 | Registry CSV updated | ✅ PASS | 170 мс | New entry added: score=85, rec=ОТКЛИКАТЬСЯ |
| TC-07 | Strong vacancy → ОТКЛИКАТЬСЯ | ✅ PASS | 160 мс | Recommendation: ОТКЛИКАТЬСЯ ✓ |
| TC-08 | Weak vacancy → ПРОПУСТИТЬ | ✅ PASS | 151 мс | Recommendation: ПРОПУСТИТЬ ✓ |