#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Article, Event, EventScore, PipelineRun, Profile, Source
from app.db.session import create_session_factory


@dataclass(slots=True)
class DisplayEvent:
    event: Event
    article: Article | None
    source: Source | None
    scores: dict[str, EventScore]

    @property
    def max_alert(self) -> int:
        return max((score.alert_score for score in self.scores.values()), default=0)

    @property
    def max_relevance(self) -> int:
        return max((score.relevance_score for score in self.scores.values()), default=0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect a persisted AI Radar pipeline run")
    parser.add_argument("--details", action="store_true", help="Show full per-profile scoring")
    parser.add_argument("--run-id", type=UUID, help="Inspect a specific pipeline run")
    parser.add_argument("--limit", type=int, default=20, help="Maximum events to display")
    return parser.parse_args()


def load_display_events(session: Session, run: PipelineRun) -> list[DisplayEvent]:
    conditions = [Event.analyzed_run_id == run.id]
    if run.finished_at is not None:
        conditions.append(
            and_(
                Event.analyzed_run_id.is_(None),
                EventScore.created_at >= run.started_at,
                EventScore.created_at <= run.finished_at,
            )
        )
    events = session.scalars(
        select(Event)
        .outerjoin(EventScore, EventScore.event_id == Event.id)
        .where(or_(*conditions))
        .distinct()
    ).all()
    result = []
    for event in events:
        article = session.scalar(
            select(Article)
            .where(Article.event_id == event.id)
            .order_by(desc(Article.published_at), desc(Article.discovered_at))
            .limit(1)
        )
        source = session.get(Source, article.source_id) if article else None
        score_rows = session.execute(
            select(Profile.slug, EventScore)
            .join(EventScore, EventScore.profile_id == Profile.id)
            .where(EventScore.event_id == event.id)
        ).all()
        result.append(DisplayEvent(event, article, source, dict(score_rows)))
    return sorted(
        result,
        key=lambda item: (
            item.max_alert,
            item.max_relevance,
            item.article.published_at.timestamp()
            if item.article and item.article.published_at
            else float("-inf"),
        ),
        reverse=True,
    )


def _score(item: DisplayEvent, profile: str, field: str) -> str:
    score = item.scores.get(profile)
    return str(getattr(score, field)) if score else "-"


def _run_header(run: PipelineRun, cost_configured: bool) -> list[str]:
    cost = f"${run.estimated_cost_usd:.6f}" if cost_configured else "not configured"
    lines = [
        "AI RADAR — LAST RUN",
        "",
        f"Run ID: {run.id}",
        f"Started: {run.started_at}",
        f"Finished: {run.finished_at or '-'}",
        "",
        f"Articles found: {run.collected}",
        f"Events analyzed: {run.analyzed}",
        f"LLM calls: {run.llm_calls}",
        f"Input tokens: {run.input_tokens}",
        f"Output tokens: {run.output_tokens}",
        f"Estimated cost: {cost}",
        f"Errors: {len(run.error_summary or [])}",
    ]
    if run.discard_counts:
        lines.extend(["", "Discarded:"])
        lines.extend(f"  {key}: {value}" for key, value in sorted(run.discard_counts.items()))
    return lines


def _summary(events: list[DisplayEvent]) -> list[str]:
    width = shutil.get_terminal_size((140, 24)).columns
    fixed_width = 95
    title_width = max(20, min(55, width - fixed_width))
    headers = [
        ("NOTICIA", title_width),
        ("FUENTE", 18),
        ("FECHA", 10),
        ("EDU_REL", 7),
        ("EDU_ALT", 7),
        ("COUR_REL", 8),
        ("COUR_ALT", 8),
        ("BANK_REL", 8),
        ("BANK_ALT", 8),
        ("CONF", 5),
        ("HYPE", 5),
    ]

    def row(values: list[str]) -> str:
        return " ".join(
            value[:size].ljust(size) for value, (_, size) in zip(values, headers, strict=True)
        )

    lines = [row([name for name, _ in headers]), "-" * min(width, sum(x[1] for x in headers) + 10)]
    for item in events:
        published = (
            item.article.published_at.strftime("%Y-%m-%d")
            if item.article and item.article.published_at
            else "-"
        )
        lines.append(
            row(
                [
                    item.event.title,
                    item.source.name if item.source else "-",
                    published,
                    _score(item, "educator", "relevance_score"),
                    _score(item, "educator", "alert_score"),
                    _score(item, "course", "relevance_score"),
                    _score(item, "course", "alert_score"),
                    _score(item, "bank", "relevance_score"),
                    _score(item, "bank", "alert_score"),
                    f"{item.event.confidence:.2f}",
                    f"{item.event.hype_probability:.2f}",
                ]
            )
        )
    return lines


def _details(events: list[DisplayEvent]) -> list[str]:
    lines = []
    for item in events:
        lines.extend(
            [
                "-" * 80,
                f"TITLE:\n{item.event.title}",
                f"SOURCE:\n{item.source.name if item.source else '-'}",
                f"PUBLISHED:\n{item.article.published_at if item.article else '-'}",
                f"CONFIDENCE:\n{item.event.confidence:.2f}",
                f"HYPE:\n{item.event.hype_probability:.2f}",
                "PRIMARY_SOURCE_VERIFIED:\n"
                + ("yes" if item.source and item.source.is_primary else "no"),
            ]
        )
        if item.source and item.source.is_primary and item.article:
            lines.append(f"PRIMARY_SOURCE_URL:\n{item.article.canonical_url}")
        for profile in ("course", "bank", "educator"):
            score = item.scores.get(profile)
            if score is None:
                continue
            lines.extend(
                [
                    profile.upper(),
                    f"  relevance: {score.relevance_score}",
                    f"  alert: {score.alert_score}",
                    f"  novelty: {score.novelty_score}",
                    f"  actionability: {score.actionability_score}",
                    f"  strategic_impact: {score.strategic_impact_score}",
                    f"  reason: {score.relevance_reason}",
                    f"  suggested_action: {score.suggested_action or '-'}",
                    f"  related_topics: {', '.join(score.related_topics or []) or '-'}",
                    "  related_classes: "
                    + (", ".join(map(str, score.related_classes or [])) or "-"),
                ]
            )
    return lines


def render_run(
    session: Session,
    *,
    run_id: UUID | None = None,
    details: bool = False,
    limit: int = 20,
    cost_configured: bool = False,
) -> tuple[int, str]:
    run = (
        session.get(PipelineRun, run_id)
        if run_id
        else session.scalar(select(PipelineRun).order_by(desc(PipelineRun.started_at)).limit(1))
    )
    if run is None:
        message = f"Pipeline run {run_id} not found." if run_id else "No pipeline runs found."
        return (1 if run_id else 0), message
    events = load_display_events(session, run)[: max(0, limit)]
    lines = _run_header(run, cost_configured)
    if not events:
        lines.extend(["", f"Run {run.id} contains no analyzed events."])
    else:
        lines.extend(["", *(_details(events) if details else _summary(events))])
    return 0, "\n".join(lines)


def main() -> int:
    args = parse_args()
    settings = get_settings()
    with create_session_factory(settings.database_url)() as session:
        code, output = render_run(
            session,
            run_id=args.run_id,
            details=args.details,
            limit=args.limit,
            cost_configured=bool(
                settings.llm_input_cost_per_million_usd or settings.llm_output_cost_per_million_usd
            ),
        )
    print(output)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
