from app.llm.schemas import ArticleAnalysis


def calculate_scores(
    analysis: ArticleAnalysis, source_trust: int, is_primary: bool
) -> dict[str, int]:
    credibility = (analysis.credibility_score + source_trust) / 2
    primary_bonus = 3 if is_primary else 0
    hype_penalty = analysis.hype_probability * 20
    scores = {}
    for evaluation in analysis.profiles:
        value = (
            evaluation.score * 0.65
            + analysis.novelty_score * 0.15
            + credibility * 0.20
            + primary_bonus
            - hype_penalty
        )
        scores[evaluation.profile] = max(0, min(100, round(value)))
    return scores
