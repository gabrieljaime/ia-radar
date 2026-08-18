from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import create_session_factory


def get_session() -> Iterator[Session]:
    settings = get_settings()
    session_factory = create_session_factory(settings.database_url)
    with session_factory() as session:
        yield session
