import inspect
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.db.models import Alert, Article, Digest, Event, EventScore, Profile, Source
from app.digest.service import DigestService, split_digest_messages
from scripts import send_digest


class RecordingDigestChannel:
    def __init__(self):
        self.messages = []

    async def send(self, text):
        self.messages.append(text)
        return str(len(self.messages))


def add_event(
    session,
    *,
    title,
    alert,
    relevance=80,
    actionability=70,
    age_minutes=0,
    alerted=False,
):
    analyzed_at = datetime.now(UTC) - timedelta(minutes=age_minutes)
    source = Source(
        name="Official & Source",
        source_type="rss",
        base_url=f"https://feed.example/{uuid4()}",
        trust_level=100,
        is_primary=True,
    )
    event = Event(
        event_hash=uuid4().hex,
        normalized_title=title.lower(),
        title=title,
        status="analyzed",
        what_happened="Cambió <algo> & ahora es mejor.",
        why_it_matters="Importa para agentes & gobernanza.",
        confidence=0.9,
        hype_probability=0.1,
    )
    session.add_all([source, event])
    session.flush()
    session.add(
        Article(
            event_id=event.id,
            source_id=source.id,
            canonical_url=f"https://article.example/{uuid4()}?a=1&b=2",
            normalized_title=event.normalized_title,
            title=title,
            summary_raw="summary",
            published_at=analyzed_at,
            content_hash=uuid4().hex,
        )
    )
    metadata = {
        "ai_agent_developer": ("AI Agent Developer", "🤖"),
        "educator": ("Educator", "🎓"),
        "bank_risk": ("Bank Risk Intelligence", "🏦"),
        "general_ai": ("AI General Radar", "🌐"),
    }
    for slug, (name, icon) in metadata.items():
        profile = session.scalar(select(Profile).where(Profile.slug == slug))
        if profile is None:
            profile = Profile(slug=slug, name=name, icon=icon)
            session.add(profile)
            session.flush()
        session.add(
            EventScore(
                event_id=event.id,
                profile_id=profile.id,
                relevance_score=relevance if slug == "ai_agent_developer" else 40,
                novelty_score=60,
                actionability_score=actionability if slug == "ai_agent_developer" else 30,
                strategic_impact_score=65,
                alert_score=alert if slug == "ai_agent_developer" else 35,
                relevance_reason="Motivo",
                suggested_action=(f"Acción para {title}" if slug == "ai_agent_developer" else None),
                related_topics=[],
                related_classes=[],
                created_at=analyzed_at,
            )
        )
    session.flush()
    if alerted:
        session.add(
            Alert(
                event_id=event.id,
                content_fingerprint=uuid4().hex,
                delivery_status="sent",
                provider_message_id="42",
            )
        )
    session.commit()
    return event


async def test_digest_selects_threshold_and_orders_events(session):
    add_event(session, title="Critical", alert=91, relevance=70, actionability=60)
    add_event(session, title="Relevant", alert=84, relevance=95, actionability=90)
    add_event(session, title="Interesting", alert=63, relevance=80, actionability=80)
    add_event(session, title="Ignored", alert=55, relevance=100, actionability=100)
    result = await DigestService(session, None).send_digest(dry_run=True)
    text = "\n".join(result.messages)
    assert all(title in text for title in ("Critical", "Relevant", "Interesting"))
    assert "Ignored" not in text
    assert text.index("1. Critical") < text.index("2. Relevant") < text.index("3. Interesting")


async def test_digest_order_uses_all_tiebreakers(session):
    add_event(session, title="By recency", alert=80, relevance=80, actionability=80)
    add_event(
        session, title="By actionability", alert=80, relevance=80, actionability=90, age_minutes=5
    )
    add_event(session, title="By relevance", alert=80, relevance=90, actionability=10)
    result = await DigestService(session, None).send_digest(dry_run=True)
    text = "\n".join(result.messages)
    assert text.index("By relevance") < text.index("By actionability") < text.index("By recency")


async def test_digest_is_idempotent_and_force_resends(session):
    add_event(session, title="One", alert=80)
    channel = RecordingDigestChannel()
    service = DigestService(session, channel)
    first = await service.send_digest()
    second = await service.send_digest()
    forced = await service.send_digest(force=True)
    assert first.status == "sent"
    assert second.status == "already_sent"
    assert forced.status == "sent"
    assert len(channel.messages) == 2


async def test_digest_dry_run_neither_sends_nor_reserves(session):
    add_event(session, title="One", alert=80)
    channel = RecordingDigestChannel()
    service = DigestService(session, channel)
    result = await service.send_digest(dry_run=True)
    assert result.status == "dry_run"
    assert channel.messages == []
    assert session.query(Digest).count() == 0


async def test_empty_digest_does_not_send(session):
    add_event(session, title="Ignored", alert=55)
    channel = RecordingDigestChannel()
    result = await DigestService(session, channel).send_digest()
    assert result.status == "empty"
    assert channel.messages == []


def test_digest_splits_by_blocks_within_telegram_limit():
    messages = split_digest_messages(["A" * 120, "B" * 120, "C" * 120], max_length=220)
    assert len(messages) == 3
    assert all(len(message) <= 220 for message in messages)
    assert all(block in "\n".join(messages) for block in ("A" * 120, "B" * 120, "C" * 120))


async def test_digest_escapes_html_and_marks_prior_alert(session):
    add_event(session, title="Unsafe <title> & news", alert=91, alerted=True)
    result = await DigestService(session, None).send_digest(dry_run=True)
    text = "\n".join(result.messages)
    assert "Unsafe &lt;title&gt; &amp; news" in text
    assert "Cambió &lt;algo&gt; &amp; ahora" in text
    assert "?a=1&amp;b=2" in text
    assert "🔥 Alerta enviada anteriormente" in text


def test_digest_command_has_no_llm_dependency():
    assert "LLMProvider" not in inspect.getsource(send_digest)
    assert "app.llm" not in inspect.getsource(send_digest)


async def test_digest_hides_disabled_profiles_and_does_not_duplicate_events(session):
    event = add_event(session, title="Multi-profile", alert=91)
    bank = session.scalar(select(Profile).where(Profile.slug == "bank_risk"))
    bank.enabled = False
    for score in session.scalars(select(EventScore).where(EventScore.event_id == event.id)):
        score.relevance_score = 90
        score.alert_score = 80
    session.commit()
    result = await DigestService(session, None).send_digest(dry_run=True)
    text = "\n".join(result.messages)
    assert text.count("1. Multi-profile") == 1
    assert "Bank Risk Intelligence" not in text
    assert "AI General Radar" in text
