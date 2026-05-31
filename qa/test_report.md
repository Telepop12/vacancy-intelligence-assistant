# QA Report — 17.05.2026 10:20

> Сгенерировано: `python qa/run_functional_tests.py`

**Результат: 32 / 32 тестов прошли**

| ID | Тест | Статус | Время | Сообщение |
|---|---|---|---|---|
| TC-01 | File input mode | ✅ PASS | 12670 мс | Exit 0, Match Score present |
| TC-02 | Stdin pipe mode | ✅ PASS | 1496 мс | Exit 0, stdin read correctly |
| TC-03 | Interactive input (simulated) | ✅ PASS | 1439 мс | Exit 0, text+terminator processed |
| TC-04 | Markdown report created | ✅ PASS | 14862 мс | analysis_20260517_101334.md — all sections present |
| TC-05 | JSON report created | ✅ PASS | 10219 мс | analysis_20260517_101349.json — valid, score=85 |
| TC-06 | Registry CSV updated | ✅ PASS | 11775 мс | New entry added: score=85, rec=ОТКЛИКАТЬСЯ |
| TC-07 | Strong vacancy → ОТКЛИКАТЬСЯ | ✅ PASS | 13596 мс | Recommendation: ОТКЛИКАТЬСЯ ✓ |
| TC-08 | Weak vacancy → ПРОПУСТИТЬ | ✅ PASS | 7379 мс | Recommendation: ПРОПУСТИТЬ ✓ |
| TC-09 | AI transformation → не ПРОПУСТИТЬ (45–65) | ✅ PASS | 11411 мс | ЗАПУСТИТЬ В РАБОТУ, score=56 |
| TC-10 | AI CoE → ЗАПУСТИТЬ В РАБОТУ | ✅ PASS | 11645 мс | ЗАПУСТИТЬ В РАБОТУ, rule-based score=23 |
| TC-11 | DI: ЗАПУСТИТЬ В РАБОТУ + strategic_rationale | ✅ PASS | 12021 мс | rationale=Несмотря на умеренный формальный match score (23/100), роль … |
| TC-12 | DI: career_risks + career_opportunities present | ✅ PASS | 10972 мс | risks=4, opportunities=4 |
| TC-13 | DI: ОТКЛИКАТЬСЯ + best/worst case | ✅ PASS | 12653 мс | best/worst present, validation_questions=4 |
| TC-14 | Intake: text source → JSON has intake block | ✅ PASS | 11769 мс | source=file, confidence=HIGH |
| TC-15 | Intake: file source_type='file' | ✅ PASS | 14567 мс | source_type=file, name=strong_ai_vacancy.txt |
| TC-16 | Intake: HTML → tags stripped | ✅ PASS | 2 мс | Clean: 'CTO / Директор по технологиям\n\nКомпания: TechCorp\n\nУправление командой' |
| TC-17 | Intake: broken JSON → confidence=LOW | ✅ PASS | 0 мс | note=Invalid JSON: Invalid control character at: line 1 column 53 |
| TC-18 | Intake: missing title → not HIGH confidence | ✅ PASS | 0 мс | confidence=LOW, notes=['Text too short (54 chars)', 'Company name not detected', 'No standard vacancy sections detected'] |
| TC-19 | Intake: very short text → confidence=LOW | ✅ PASS | 0 мс | LOW, notes=3 issue(s) |
| TC-20 | Resume: large CV -> ResumeProfile created | ✅ PASS | 22361 мс | years=17, domains=8, ai_signals=11 |
| TC-21 | Resume: AI signals detected (>=3) | ✅ PASS | 25304 мс | 11 signals: ai, ml, llm, gpt |
| TC-22 | Resume: trajectory or AI level detected | ✅ PASS | 27047 мс | trajectory=['CIO → CDTO (Digital Transformation Officer): демонстрирует переход от IT-управления к бизнес-трансформации через сквозные инициативы (стратегия холдинга, change management, ROI-фокус)', 'CIO → CAIO (Chief AI Officer): растущий портфель AI/ML-проектов (LLM в операциях, ML-прогнозирование, multi-agent системы) указывает на потенциал стратегического AI-лидерства'], ai_level=HIGH |
| TC-23 | Resume: minimal AI -> ai_positioning=LOW | ✅ PASS | 16229 мс | Correctly detected LOW AI positioning |
| TC-24 | Resume: strong transformation -> not LOW level | ✅ PASS | 21849 мс | level=HIGH, signals=5 |
| TC-25 | Scale: 2000+ + PMO -> enterprise/holding | ✅ PASS | 0 мс | scale=holding, rationale=HOLDING (score 7/10): 1,000+ employees · holding / group str |
| TC-26 | Framing: operational CV -> not strategic/executive | ✅ PASS | 0 мс | level=operational, score=0/100, op=9, ex=0 |
| TC-27 | Industry: vendor context -> no false telecom/finance | ✅ PASS | 0 мс | Industries=[] (no false positives) |
| TC-28 | Framing: strategic text -> exec signals >= 3 | ✅ PASS | 0 мс | level=strategic, score=100, ex_sigs=9 |
| TC-29 | AI: single mention -> not HIGH positioning | ✅ PASS | 14276 мс | ai_level=LOW, signals=1 |
| TC-30 | Career Match: returns CareerMatchResult | ✅ PASS | 47269 мс | career_match=88, keyword=75, rec=ОТКЛИКАТЬСЯ |
| TC-31 | Career Match: transferable competencies present | ✅ PASS | 46775 мс | 5 competencies, career_match=76 vs keyword=23 |
| TC-32 | Career Match: score > keyword for experienced CIO | ✅ PASS | 41095 мс | career_match=78 > keyword=23, rec=ЗАПУСТИТЬ В РАБОТУ |