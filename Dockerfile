FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# The container port is only reachable through the platform proxy, so client
# IPs arrive in X-Forwarded-For. Narrow this if the container is exposed directly.
ENV FORWARDED_ALLOW_IPS=*

COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --no-cache-dir .
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/.data \
    && chown -R appuser:appuser /app/.data

USER appuser

CMD ["python", "-m", "app.main"]
