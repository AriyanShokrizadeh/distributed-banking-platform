FROM python:3.12-slim

ARG SERVICE

LABEL description="Distributed Banking Platform"

ENV SERVICE_NAME=${SERVICE} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update

RUN groupadd -g 10001 banking \
    && useradd -u 10001 -g banking -m -s /usr/sbin/nologin banking

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=banking:banking shared/ ./shared/
COPY --chown=banking:banking config/ ./config/
COPY --chown=banking:banking services/${SERVICE}/ ./services/${SERVICE}/

USER banking

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn services.${SERVICE_NAME}.app:app --host 0.0.0.0 --port 8000"]
