# Build context is the repository root (see docker-compose.yml) so migrations can be bundled.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY services/ai-qualification/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/ai-qualification/app ./app
COPY database/migrations ./migrations

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
