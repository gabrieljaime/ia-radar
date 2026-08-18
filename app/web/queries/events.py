from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import desc, exists, func, select
from sqlalchemy.orm import Session

from app.db.models import Article, Event, EventScore, PipelineRun, Profile, Source

DEFAULT_PAGE_SIZE = 25


@dataclass(slots=True)
class ProfileBadge:
    profile_name: str
    profile_icon: str
    relevance: int
    alert: int


@dataclass(slots=True)
class EventListItem:
    event: Event
    source_name: str | None
    published_at: datetime | None
    max_alert: int
    badges: list[ProfileBadge]


@dataclass(slots=True)
class EventFilters:
    profile: str | None = None
    source_id: UUID | None = None
    days: int | None = None
    primary_only: bool | None = None
    min_relevance: int | None = None
    min_alert: int | None = None
    search: str | None = None


@dataclass(slots=True)
class EventListPage:
    items: list[EventListItem]
    page: int
    page_size: int
    total: int

    @property
    def total_pages(self) -> int:
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        return self.page > 1


def _base_query(filters: EventFilters):
    query = select(Event).where(Event.status == "analyzed")

    if filters.search:
        query = query.where(Event.title.ilike(f"%{filters.search}%"))

    if filters.days:
        since = datetime.now(UTC) - timedelta(days=filters.days)
        query = query.where(
            exists(
                select(Article.id).where(
                    Article.event_id == Event.id, Article.published_at >= since
                )
            )
        )

    if filters.source_id:
        query = query.where(
            exists(
                select(Article.id).where(
                    Article.event_id == Event.id, Article.source_id == filters.source_id
                )
            )
        )

    if filters.primary_only is not None:
        query = query.where(Event.primary_source_verified == filters.primary_only)

    if filters.profile or filters.min_relevance is not None or filters.min_alert is not None:
        score_query = (
            select(EventScore.id)
            .join(Profile, Profile.id == EventScore.profile_id)
            .where(EventScore.event_id == Event.id)
        )
        if filters.profile:
            score_query = score_query.where(Profile.slug == filters.profile)
        if filters.min_relevance is not None:
            score_query = score_query.where(EventScore.relevance_score >= filters.min_relevance)
        if filters.min_alert is not None:
            score_query = score_query.where(EventScore.alert_score >= filters.min_alert)
        query = query.where(exists(score_query))

    return query


def count_events(session: Session, filters: EventFilters) -> int:
    query = _base_query(filters).with_only_columns(Event.id)
    return session.scalar(select(func.count()).select_from(query.subquery())) or 0


def list_events(
    session: Session, filters: EventFilters, *, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE
) -> EventListPage:
    total = count_events(session, filters)
    query = (
        _base_query(filters)
        .order_by(desc(Event.last_seen_at))
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    events = session.scalars(query).all()
    items = [build_list_item(session, event) for event in events]
    return EventListPage(items=items, page=page, page_size=page_size, total=total)


def build_list_item(session: Session, event: Event) -> EventListItem:
    article = session.scalar(
        select(Article)
        .where(Article.event_id == event.id)
        .order_by(desc(Article.published_at))
        .limit(1)
    )
    source = session.get(Source, article.source_id) if article else None
    score_rows = session.execute(
        select(Profile, EventScore)
        .join(EventScore, EventScore.profile_id == Profile.id)
        .where(EventScore.event_id == event.id, Profile.enabled.is_(True))
        .order_by(desc(EventScore.alert_score))
    ).all()
    badges = [
        ProfileBadge(profile.name, profile.icon, score.relevance_score, score.alert_score)
        for profile, score in score_rows[:3]
    ]
    max_alert = max((score.alert_score for _, score in score_rows), default=0)
    return EventListItem(
        event=event,
        source_name=source.name if source else None,
        published_at=article.published_at if article else None,
        max_alert=max_alert,
        badges=badges,
    )


@dataclass(slots=True)
class ProfileScore:
    profile: Profile
    score: EventScore


@dataclass(slots=True)
class ArticleSource:
    article: Article
    source: Source | None


@dataclass(slots=True)
class EventDetail:
    event: Event
    scores: list[ProfileScore]
    articles: list[ArticleSource]
    primary_source_article: ArticleSource | None
    analyzed_run: PipelineRun | None


def get_event_detail(session: Session, event_id: UUID) -> EventDetail | None:
    event = session.get(Event, event_id)
    if event is None:
        return None
    score_rows = session.execute(
        select(Profile, EventScore)
        .join(EventScore, EventScore.profile_id == Profile.id)
        .where(EventScore.event_id == event.id)
        .order_by(desc(EventScore.alert_score))
    ).all()
    scores = [ProfileScore(profile, score) for profile, score in score_rows]

    articles = session.scalars(
        select(Article).where(Article.event_id == event.id).order_by(desc(Article.published_at))
    ).all()
    source_ids = {article.source_id for article in articles}
    sources_by_id = {
        source.id: source
        for source in (
            session.scalars(select(Source).where(Source.id.in_(source_ids))).all()
            if source_ids
            else []
        )
    }
    article_sources = [
        ArticleSource(article, sources_by_id.get(article.source_id)) for article in articles
    ]
    primary_source_article = next(
        (
            item
            for item in article_sources
            if event.primary_source_url and item.article.canonical_url == event.primary_source_url
        ),
        None,
    )

    analyzed_run = (
        session.get(PipelineRun, event.analyzed_run_id) if event.analyzed_run_id else None
    )

    return EventDetail(
        event=event,
        scores=scores,
        articles=article_sources,
        primary_source_article=primary_source_article,
        analyzed_run=analyzed_run,
    )


def list_enabled_profiles(session: Session) -> list[Profile]:
    query = select(Profile).where(Profile.enabled.is_(True)).order_by(Profile.name)
    return list(session.scalars(query))


def list_filterable_sources(session: Session) -> list[Source]:
    return list(session.scalars(select(Source).order_by(Source.name)))
