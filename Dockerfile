FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONPATH=/app
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .
COPY config ./config
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts
RUN addgroup --system radar && adduser --system --ingroup radar radar \
    && chown -R radar:radar /app
USER radar
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
USER root
COPY tests ./tests
RUN pip install --no-cache-dir ".[dev]"
USER radar
CMD ["pytest", "-q"]
