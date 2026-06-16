FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --no-cache-dir .
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/.data \
    && chown -R appuser:appuser /app/.data

USER appuser

CMD ["python", "-m", "app.main"]
