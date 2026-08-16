from app.llm.schemas import ArticleAnalysis


def classify_alert_score(score: int) -> str:
    if score >= 90:
        return "CRITICAL"
    if score >= 75:
        return "RELEVANT"
    if score >= 60:
        return "INTERESTING"
    return "IGNORE"


def calculate_scores(
    analysis: ArticleAnalysis, source_trust: int, is_primary: bool
) -> dict[str, int]:
    """Return final alert scores; thematic relevance is deliberately left untouched.

    Confidence scales the LLM alert signal between 75% and 100%. Source trust contributes
    -8..+2 points around a neutral trust of 80, a primary source adds 2, and hype removes up
    to 20 points. This keeps the operational decision deterministic without redefining relevance.
    """
    confidence_factor = 0.75 + analysis.confidence * 0.25
    source_adjustment = (source_trust - 80) * 0.1
    primary_bonus = 2 if is_primary else 0
    hype_penalty = analysis.hype_probability * 20
    scores = {}
    for evaluation in analysis.profiles:
        value = (
            evaluation.alert_score * confidence_factor
            + source_adjustment
            + primary_bonus
            - hype_penalty
        )
        scores[evaluation.profile] = max(0, min(100, round(value)))
    return scores
