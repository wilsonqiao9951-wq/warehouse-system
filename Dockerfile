FROM python:3.12-slim

ARG OPENPARTSFLOW_VERSION=dev
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="OpenPartsFlow API" \
      org.opencontainers.image.version="${OPENPARTSFLOW_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements-runtime.txt ./
RUN python -m pip install --no-cache-dir -r requirements-runtime.txt \
    && groupadd --gid 10001 openpartsflow \
    && useradd --uid 10001 --gid openpartsflow --no-create-home --shell /usr/sbin/nologin openpartsflow

COPY --chown=10001:10001 alembic.ini ./
COPY --chown=10001:10001 alembic ./alembic
COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 scripts ./scripts

RUN mkdir -p /app/data/uploads /app/data/private /app/data/rollbacks \
    && chown -R 10001:10001 /app/data

USER 10001:10001
EXPOSE 8000
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
