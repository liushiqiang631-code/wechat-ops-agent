FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY THIRD_PARTY_NOTICES.md ./
COPY licenses ./licenses
COPY app ./app
COPY data ./data
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
RUN python -m pip install .

RUN useradd --create-home --uid 10001 agent && \
    mkdir -p /app/outputs && chown -R agent:agent /app
USER agent

EXPOSE 8000
CMD ["python", "-m", "app.cli", "serve", "--host", "0.0.0.0", "--port", "8000", "--no-reload"]
