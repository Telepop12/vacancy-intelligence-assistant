"""
pytest configuration for Vacancy Intelligence Assistant QA suite.

Run from vacancy_ai_assistant/:
    pytest qa/
    pytest qa/ -v
    pytest qa/ -k "intake or resume"
    pytest qa/ -m "no_llm"   # only tests that don't need an API key
"""
import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
