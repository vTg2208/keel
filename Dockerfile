FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.lock .
RUN pip install -r requirements.lock && useradd --uid 10001 --create-home app
COPY pyproject.toml .
COPY payops ./payops
USER app
EXPOSE 8000 8001 8002
CMD ["uvicorn", "payops.api:app", "--host", "0.0.0.0", "--port", "8000"]
