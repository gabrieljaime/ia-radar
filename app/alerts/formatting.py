import html

from app.alerts.actions import humanize_action
from app.domain.models import Candidate
from app.llm.schemas import ArticleAnalysis
from app.profiles.models import ProfileConfig


def format_telegram_alert(
    candidate: Candidate,
    analysis: ArticleAnalysis,
    scores: dict[str, int],
    profiles: list[ProfileConfig],
) -> str:
    top_score = max(scores.values())
    evaluations = {item.profile: item for item in analysis.profiles}
    profile_configs = {profile.slug: profile for profile in profiles if profile.enabled}
    profile_lines = "\n\n".join(
        f"{profile_configs[profile].icon} "
        f"<b>{html.escape(profile_configs[profile].name)}</b>\n"
        f"Relevancia: {evaluations[profile].relevance_score}\nAlerta: {score}"
        for profile, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    )
    actions = "\n".join(
        f"{profile_configs[item.profile].icon} "
        f"<b>{html.escape(profile_configs[item.profile].name)}</b>: "
        f"{html.escape(humanize_action(item.suggested_action))}"
        for item in analysis.profiles
        if item.suggested_action
    )
    reasons = "\n".join(
        f"• {html.escape(profile_configs[item.profile].name)}: {html.escape(item.reason)}"
        for item in analysis.profiles
    )
    source_label = (
        "Fuente primaria: sí"
        if candidate.source_is_primary
        else "Fuente secundaria — pendiente de verificación primaria"
        if candidate.source_requires_primary_verification
        else "Fuente primaria: no"
    )
    return (
        f"🔥 <b>AI RADAR — {top_score}/100</b>\n\n"
        f"<b>{html.escape(candidate.title)}</b>\n"
        f"Confidence: {analysis.confidence:.2f}\n"
        f"Hype: {analysis.hype_probability:.2f}\n"
        f"{source_label}\n\n"
        f"{profile_lines}\n\n"
        f"<b>QUÉ PASÓ</b>\n{html.escape(analysis.what_happened)}\n\n"
        f"<b>POR QUÉ IMPORTA</b>\n{html.escape(analysis.why_it_matters)}\n\n"
        f"<b>MOTIVO</b>\n{reasons}\n\n"
        f"<b>ACCIÓN SUGERIDA</b>\n{actions or 'Sin acción sugerida.'}\n\n"
        f'<a href="{html.escape(candidate.canonical_url, quote=True)}">Fuente</a>'
    )
