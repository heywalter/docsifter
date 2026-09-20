FROM python:3.11-slim

ARG INSTALL_MODEL_RUNTIME=false

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/data/model-cache/huggingface

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && useradd --create-home --uid 10001 docsifter \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-model.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir "gunicorn>=23,<24" \
    && if [ "$INSTALL_MODEL_RUNTIME" = "true" ]; then \
         pip install --no-cache-dir -r requirements-model.txt; \
       fi

COPY --chown=docsifter:docsifter pyproject.toml README.md LICENSE ./
COPY --chown=docsifter:docsifter src ./src
RUN pip install --no-cache-dir --no-deps . \
    && mkdir -p /app/data && chown -R docsifter:docsifter /app/data

USER docsifter

EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--timeout", "120", "docsifter.wsgi:app"]
