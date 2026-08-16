import html

from app.domain.models import Candidate
from app.llm.schemas import ArticleAnalysis

PROFILE_ICONS = {"course": "🤖", "bank": "🏦", "educator": "🎓"}


def format_telegram_alert(
    candidate: Candidate, analysis: ArticleAnalysis, scores: dict[str, int]
) -> str:
    top_score = max(scores.values())
    profile_lines = "\n".join(
        f"{PROFILE_ICONS.get(profile, '•')} {html.escape(profile.title())}: {score}"
        for profile, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    )
    actions = "\n".join(
        f"{PROFILE_ICONS.get(item.profile, '•')} <b>{html.escape(item.profile.title())}</b>: "
        f"{html.escape(item.suggested_action)}"
        for item in analysis.profiles
        if item.suggested_action
    )
    reasons = "\n".join(
        f"• {html.escape(item.profile.title())}: {html.escape(item.reason)}"
        for item in analysis.profiles
    )
    return (
        f"🔥 <b>AI RADAR — {top_score}/100</b>\n\n"
        f"<b>{html.escape(candidate.title)}</b>\n"
        f"Confidence: {analysis.confidence:.2f}\n\n{profile_lines}\n\n"
        f"<b>QUÉ PASÓ</b>\n{html.escape(analysis.what_happened)}\n\n"
        f"<b>POR QUÉ IMPORTA</b>\n{html.escape(analysis.why_it_matters)}\n\n"
        f"<b>MOTIVO</b>\n{reasons}\n\n"
        f"<b>PARA VOS</b>\n{actions or 'Sin acción sugerida.'}\n\n"
        f'<a href="{html.escape(candidate.canonical_url, quote=True)}">Fuente</a>'
    )
