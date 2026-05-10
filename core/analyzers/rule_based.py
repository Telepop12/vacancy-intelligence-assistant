from __future__ import annotations

from datetime import datetime

from core.analyzers.base import BaseAnalyzer
from core.models import CandidateProfile, Recommendation, VacancyAnalysis
from core.scoring import THRESHOLD_APPLY, calculate_score, get_recommendation

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_HR_QUESTIONS: list[str] = [
    "Каков размер ИТ-команды и её структура (инфраструктура, разработка, поддержка)?",
    "Каков годовой ИТ-бюджет и уровень полномочий по его управлению?",
    "На каком уровне выстраивается взаимодействие с советом директоров / акционерами?",
    "Какова доля стратегической работы vs операционного управления на этой позиции?",
    "Какие ключевые ИТ-проекты и инициативы запланированы на ближайшие 1–2 года?",
    "Есть ли утверждённая ИТ-стратегия или её разработка входит в задачи роли?",
    "Какова причина открытия вакансии — новая позиция или замена? Если замена — почему ушёл предыдущий руководитель?",
    "Как выглядит текущий технологический стек и каковы планы по его эволюции?",
]

_RESUME_TIPS: list[str] = [
    "Добавьте конкретные цифры: размер команды, бюджет ИТ, количество проектов в портфеле.",
    "Опишите результаты реализованных ИТ-стратегий с бизнес-эффектом (% снижения издержек, рост производительности).",
    "Выделите внедрённые системы (1С, ERP, BI) с масштабом и достигнутыми показателями.",
    "Отразите опыт взаимодействия с советом директоров, C-level и ключевыми стейкхолдерами.",
    "Добавьте раздел AI/цифровая трансформация с конкретными реализованными инициативами.",
    "Убедитесь, что в профиле явно указаны компетенции в кибербезопасности и ITSM/ITIL.",
]

_LETTER_APPLY = """\
Добрый день!

Ознакомился с описанием позиции {role} и готов рассмотреть её в качестве приоритетной.

Мой опыт напрямую соответствует задачам роли — в частности, в части {matches}.
За последние годы мне удалось сформировать и реализовать ИТ-стратегии в производственно-сервисных компаниях, \
выстроить эффективные команды и цифровые процессы с измеримым бизнес-результатом.

Буду рад обсудить детали в удобное для вас время.

С уважением"""

_LETTER_CLARIFY = """\
Добрый день!

Позиция {role} привлекла моё внимание — вижу пересечение с опытом в части {matches}.

Прежде чем принять решение об отклике, хотел бы уточнить несколько ключевых вопросов \
по формату роли, масштабу ответственности и задачам на первый год.

Готов к предварительному разговору в любое удобное для вас время.

С уважением"""

_LETTER_SKIP = """\
Добрый день!

Ознакомился с описанием вакансии. Формат роли частично соответствует моему профилю, \
однако ряд ключевых параметров требует дополнительного уточнения.

Если вы считаете, что мой опыт может быть релевантен, готов к короткому созвону.

С уважением"""


# ---------------------------------------------------------------------------
# RuleBasedAnalyzer
# ---------------------------------------------------------------------------


class RuleBasedAnalyzer(BaseAnalyzer):
    """Keyword-based analyzer using the categorical scoring model."""

    def analyze(self, vacancy_text: str, profile: CandidateProfile) -> VacancyAnalysis:
        score, matches, risks = calculate_score(vacancy_text, profile)
        recommendation = get_recommendation(score)

        role_hint = self._extract_role_hint(vacancy_text, profile.target_roles)
        matches_str = ", ".join(matches[:4]) if matches else "ИТ-управление и цифровая трансформация"

        if recommendation == Recommendation.APPLY:
            hr_response = _LETTER_APPLY.format(role=role_hint, matches=matches_str)
        elif recommendation == Recommendation.CLARIFY:
            hr_response = _LETTER_CLARIFY.format(role=role_hint, matches=matches_str)
        else:
            hr_response = _LETTER_SKIP

        if not risks and score < THRESHOLD_APPLY:
            risks.append("Недостаточно данных в тексте вакансии для точной оценки совпадения")

        return VacancyAnalysis(
            vacancy_text=vacancy_text,
            analyzed_at=datetime.now(),
            match_score=score,
            recommendation=recommendation,
            key_matches=matches,
            risks=risks,
            hr_questions=list(_HR_QUESTIONS),
            hr_response=hr_response,
            resume_tips=list(_RESUME_TIPS),
        )

    @staticmethod
    def _extract_role_hint(vacancy_text: str, target_roles: list[str]) -> str:
        text_lower = vacancy_text.lower()
        for role in target_roles:
            if role.lower() in text_lower:
                return role
        return "ИТ-руководителя"
