"""
MONEY MACHINE V2 - AI Quality adapter.

Uses the existing locked Groq Judge V1.
No new AI capability is introduced here.
"""

from groq_judge_v1 import judge

from .contracts import AIQualityResult


_ALLOWED_DECISIONS = {"PASS", "WAIT"}
_ALLOWED_QUALITY = {"HIGH", "MEDIUM", "LOW"}


def review_candidate(candidate: dict) -> AIQualityResult:
    """
    Send an existing candidate to the existing AI Quality Judge.

    AI remains limited to:
      - PASS / WAIT
      - HIGH / MEDIUM / LOW
      - up to 5 reasons
    """

    result = judge(candidate)

    decision = result.get("decision")
    quality = result.get("quality")
    reasons = result.get("reasons", [])

    if decision not in _ALLOWED_DECISIONS:
        raise ValueError(f"Invalid AI decision: {decision}")

    if quality not in _ALLOWED_QUALITY:
        raise ValueError(f"Invalid AI quality: {quality}")

    if not isinstance(reasons, list):
        raise ValueError("AI reasons must be a list")

    return AIQualityResult(
        decision=decision,
        quality=quality,
        reasons=[str(reason) for reason in reasons[:5]],
        source=result.get("source"),
        model=result.get("model"),
    )
