from __future__ import annotations

import hashlib
import html
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.alerts.actions import humanize_action
from app.alerts.base import AlertChannel
from app.db.models import Alert, Article, Digest, Event, EventScore, PipelineRun, Profile, Source
from app.pipeline.score import classify_alert_score

TELEGRAM_SAFE_LENGTH = 3800


@dataclass(slots=True)
class DigestEvent:
    event: Event
    article: Article | None
    source: Source | None
    scores: dict[str, EventScore]
    profiles: dict[str, Profile]
    previously_alerted: bool

    @property
    def max_alert(self) -> int:
        return max(score.alert_score for score in self.scores.values())

    @property
    def max_relevance(self) -> int:
        return max(score.relevance_score for score in self.scores.values())

    @property
    def max_actionability(self) -> int:
        return max(score.actionability_score for score in self.scores.values())

    @property
    def recency(self) -> float:
        value = self.article.published_at if self.article else None
        return value.timestamp() if value else float("-inf")


@dataclass(slots=True)
class DigestResult:
    status: str
    messages: list[str]
    telegram_calls: int = 0


class DigestService:
    def __init__(
        self,
        session: Session,
        channel: AlertChannel | None,
        *,
        min_alert_score: int = 60,
        max_items: int = 10,
        max_actions: int = 3,
        max_message_length: int = TELEGRAM_SAFE_LENGTH,
        now: datetime | None = None,
    ) -> None:
        self.session = session
        self.channel = channel
        self.min_alert_score = min_alert_score
        self.max_items = max_items
        self.max_actions = max_actions
        self.max_message_length = max_message_length
        self.now = now or datetime.now(UTC)

    async def send_digest(
        self,
        *,
        hours: int = 24,
        run_id: UUID | None = None,
        dry_run: bool = False,
        force: bool = False,
    ) -> DigestResult:
        period_start, period_end, run = self._period(hours, run_id)
        all_events = self._load_events(period_start, period_end, run)
        selected = [item for item in all_events if item.max_alert >= self.min_alert_score]
        selected.sort(
            key=lambda item: (
                item.max_alert,
                item.max_relevance,
                item.max_actionability,
                item.recency,
            ),
            reverse=True,
        )
        selected = selected[: self.max_items]
        if not selected:
            return DigestResult("empty", [])

        blocks = self._render_blocks(selected, len(all_events), hours, run)
        messages = split_digest_messages(blocks, self.max_message_length)
        content_hash = hashlib.sha256("\n".join(messages).encode()).hexdigest()
        if run:
            period_key = f"run:{run.id}"
        else:
            hour_bucket = period_end.replace(minute=0, second=0, microsecond=0)
            period_key = f"rolling:{hours}:{hour_bucket.isoformat()}"
        key_material = f"{period_key}|{content_hash}"
        idempotency_key = hashlib.sha256(key_material.encode()).hexdigest()

        if dry_run:
            return DigestResult("dry_run", messages)
        if self.channel is None:
            raise ValueError("Telegram configuration is required to send a digest")
        digest = self._reserve(
            period_start, period_end, content_hash, None if force else idempotency_key
        )
        if digest is None:
            return DigestResult("already_sent", messages)
        message_ids = []
        try:
            for message in messages:
                message_ids.append(await self.channel.send(message))
        except Exception:
            digest.status = "failed"
            digest.telegram_message_id = ",".join(message_ids) or None
            self.session.commit()
            raise
        digest.status = "sent"
        digest.telegram_message_id = ",".join(message_ids)
        digest.sent_at = datetime.now(UTC)
        self.session.commit()
        return DigestResult("sent", messages, len(message_ids))

    def _period(
        self, hours: int, run_id: UUID | None
    ) -> tuple[datetime, datetime, PipelineRun | None]:
        if run_id:
            run = self.session.get(PipelineRun, run_id)
            if run is None:
                raise LookupError(f"Pipeline run {run_id} not found.")
            return run.started_at, run.finished_at or self.now, run
        end = self.now
        return end - timedelta(hours=hours), end, None

    def _load_events(
        self, period_start: datetime, period_end: datetime, run: PipelineRun | None
    ) -> list[DigestEvent]:
        run_condition = Event.analyzed_run_id == run.id if run else True
        events = self.session.scalars(
            select(Event)
            .join(EventScore, EventScore.event_id == Event.id)
            .join(Article, Article.event_id == Event.id)
            .where(
                run_condition,
                Article.published_at.is_not(None),
                Article.published_at >= period_start,
                Article.published_at <= period_end,
            )
            .distinct()
        ).all()
        return [
            item
            for event in events
            if (item := self._hydrate(event, period_start, period_end)).scores
        ]

    def _hydrate(self, event: Event, period_start: datetime, period_end: datetime) -> DigestEvent:
        article = self.session.scalar(
            select(Article)
            .where(
                Article.event_id == event.id,
                Article.published_at.is_not(None),
                Article.published_at >= period_start,
                Article.published_at <= period_end,
            )
            .order_by(desc(Article.published_at))
            .limit(1)
        )
        if article is None:
            return DigestEvent(event, None, None, {}, {}, False)
        source = self.session.get(Source, article.source_id) if article else None
        rows = self.session.execute(
            select(Profile, EventScore)
            .join(EventScore, EventScore.profile_id == Profile.id)
            .where(EventScore.event_id == event.id, Profile.enabled.is_(True))
        ).all()
        alerted = self.session.scalar(
            select(Alert.id).where(
                Alert.event_id == event.id,
                Alert.alert_type == "immediate",
                Alert.delivery_status == "sent",
            )
        )
        scores = {profile.slug: score for profile, score in rows}
        profiles = {profile.slug: profile for profile, _ in rows}
        return DigestEvent(event, article, source, scores, profiles, alerted is not None)

    def _render_blocks(
        self,
        events: list[DigestEvent],
        analyzed_count: int,
        hours: int,
        run: PipelineRun | None,
    ) -> list[str]:
        categories = {"CRITICAL": 0, "RELEVANT": 0, "INTERESTING": 0}
        for item in events:
            category = classify_alert_score(item.max_alert)
            if category in categories:
                categories[category] += 1
        period_label = f"Corrida {run.id}" if run else f"Últimas {hours} horas"
        header = (
            f"{html.escape(period_label)}\n\n"
            f"📊 {analyzed_count} noticias analizadas\n"
            f"🔥 Críticas: {categories['CRITICAL']}\n"
            f"🟠 Relevantes: {categories['RELEVANT']}\n"
            f"🟡 Interesantes: {categories['INTERESTING']}\n\n"
            f"<b>📌 PARA MIRAR HOY</b>\n{self._executive_summary(events)}"
        )
        blocks = [header]
        blocks.extend(self._event_block(index, item) for index, item in enumerate(events, 1))
        actions = self._top_actions(events)
        if actions:
            blocks.append(
                "<b>✅ ACCIONES SUGERIDAS</b>\n"
                + "\n".join(f"• {html.escape(action)}" for action in actions)
            )
        return blocks

    def _executive_summary(self, events: list[DigestEvent]) -> str:
        lines = []
        profiles = {slug: profile for item in events for slug, profile in item.profiles.items()}
        for slug, profile in sorted(profiles.items(), key=lambda item: item[1].name):
            count = sum(
                1
                for item in events
                if slug in item.scores
                and (item.scores[slug].relevance_score >= 50 or item.scores[slug].alert_score >= 50)
            )
            if count:
                noun = "novedad relevante" if count == 1 else "novedades relevantes"
                lines.append(f"• {count} {noun} para {html.escape(profile.name)}")
        return "\n".join(lines)

    def _event_block(self, index: int, item: DigestEvent) -> str:
        category = {
            "CRITICAL": "🔥 Crítica",
            "RELEVANT": "🟠 Relevante",
            "INTERESTING": "🟡 Interesante",
        }[classify_alert_score(item.max_alert)]
        lines = [f"<b>{index}. {html.escape(item.event.title)}</b>", category]
        if item.previously_alerted:
            lines.append("🔥 Alerta enviada anteriormente")
        ordered_profiles = sorted(
            item.profiles.values(),
            key=lambda profile: item.scores[profile.slug].relevance_score,
            reverse=True,
        )
        for profile in ordered_profiles:
            score = item.scores.get(profile.slug)
            if score and (score.relevance_score >= 50 or score.alert_score >= 50):
                lines.extend(
                    [
                        "",
                        f"{profile.icon} <b>{html.escape(profile.name)}</b>",
                        f"Relevancia: {score.relevance_score} · Alerta: {score.alert_score}",
                    ]
                )
        if item.event.what_happened:
            lines.extend(["", "<b>Qué pasó:</b>", html.escape(item.event.what_happened)])
        if item.event.why_it_matters:
            lines.extend(["", "<b>Por qué importa:</b>", html.escape(item.event.why_it_matters)])
        best_action = max(item.scores.values(), key=lambda score: score.actionability_score)
        if best_action.suggested_action:
            lines.extend(
                [
                    "",
                    "<b>💡 Acción sugerida:</b>",
                    html.escape(humanize_action(best_action.suggested_action)),
                ]
            )
        best_url = item.event.primary_source_url or (
            item.article.canonical_url if item.article else None
        )
        if best_url:
            url = html.escape(best_url, quote=True)
            lines.extend(
                [
                    "",
                    f'<a href="{url}">🔗 Fuente</a>',
                ]
            )
        if item.event.primary_source_verified:
            lines.append("✅ Fuente primaria verificada")
        elif item.source and item.source.requires_primary_verification:
            lines.append("⚠️ Fuente secundaria — pendiente de verificación primaria")
        elif item.source:
            lines.append("⚠️ Fuente secundaria")
        return "\n".join(lines)

    def _top_actions(self, events: list[DigestEvent]) -> list[str]:
        if self.max_actions <= 0:
            return []
        candidates = sorted(
            (score for item in events for score in item.scores.values() if score.suggested_action),
            key=lambda score: score.actionability_score,
            reverse=True,
        )
        result = []
        for score in candidates:
            action = humanize_action(score.suggested_action)
            if action not in result:
                result.append(action)
            if len(result) == self.max_actions:
                break
        return result

    def _reserve(
        self,
        period_start: datetime,
        period_end: datetime,
        content_hash: str,
        idempotency_key: str | None,
    ) -> Digest | None:
        if idempotency_key:
            existing = self.session.scalar(
                select(Digest).where(
                    Digest.idempotency_key == idempotency_key,
                    Digest.status.in_(("pending", "sent")),
                )
            )
            if existing:
                return None
        digest = Digest(
            period_start=period_start,
            period_end=period_end,
            content_hash=content_hash,
            idempotency_key=idempotency_key,
        )
        self.session.add(digest)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            return None
        return digest


def split_digest_messages(blocks: list[str], max_length: int = TELEGRAM_SAFE_LENGTH) -> list[str]:
    content_limit = max_length - 50
    expanded_blocks = []
    for block in blocks:
        if len(block) <= content_limit:
            expanded_blocks.append(block)
            continue
        part = ""
        for line in block.splitlines():
            candidate = f"{part}\n{line}" if part else line
            if len(candidate) <= content_limit:
                part = candidate
                continue
            if part:
                expanded_blocks.append(part)
            if len(line) > content_limit:
                words = line.split(" ")
                part = ""
                for word in words:
                    if len(word) > content_limit:
                        raise ValueError("Digest contains a word or URL too long for Telegram")
                    candidate = f"{part} {word}" if part else word
                    if len(candidate) > content_limit:
                        expanded_blocks.append(part)
                        part = word
                    else:
                        part = candidate
            else:
                part = line
        if part:
            expanded_blocks.append(part)

    chunks: list[str] = []
    current = ""
    for block in expanded_blocks:
        candidate = f"{current}\n\n━━━━━━━━━━━━━━━━━━\n\n{block}" if current else block
        if len(candidate) <= content_limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = block
    if current:
        chunks.append(current)
    total = len(chunks)
    return [
        f"<b>🧠 AI RADAR — RESUMEN{f' ({index}/{total})' if total > 1 else ''}</b>\n\n{chunk}"
        for index, chunk in enumerate(chunks, 1)
    ]
