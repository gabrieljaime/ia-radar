#!/usr/bin/env python3
import argparse
from uuid import UUID

from app.core.config import get_settings
from app.db.models import Article, CandidateRecord, Event, Source
from app.db.session import create_session_factory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect one persisted candidate without I/O")
    parser.add_argument("id", type=UUID, help="Candidate record ID")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with create_session_factory(get_settings().database_url)() as session:
        record = session.get(CandidateRecord, args.id)
        if record is None:
            print(f"Candidate record {args.id} not found.")
            return 1
        article = session.get(Article, record.article_id) if record.article_id else None
        event = session.get(Event, record.event_id) if record.event_id else None
        source = session.get(Source, article.source_id) if article else None
        fields = {
            "candidate_record_id": record.id,
            "source": source.name if source else record.source_name,
            "source_type": source.source_type if source else "unknown",
            "title": article.title if article else record.title,
            "url": article.canonical_url if article else record.canonical_url,
            "published_at": article.published_at if article else None,
            "first_seen_at": article.discovered_at if article else record.discovered_at,
            "raw_summary": article.summary_raw if article else None,
            "event_id": event.id if event else record.event_id,
            "analysis_summary": event.what_happened if event else None,
        }
        for name, value in fields.items():
            print(f"{name}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
