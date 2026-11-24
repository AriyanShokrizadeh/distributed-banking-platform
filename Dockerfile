FROM python:3.12-slim

ARG SERVICE

LABEL description="Distributed Banking Platform"

ENV SERVICE_NAME=${SERVICE} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Run the API without root privileges.
RUN groupadd --gid 10001 banking \
    && useradd --uid 10001 --gid banking --create-home --shell /usr/sbin/nologin banking

WORKDIR /app

# Install dependencies before copying application code for better build caching.
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=banking:banking shared/ ./shared/
COPY --chown=banking:banking config/ ./config/
COPY --chown=banking:banking services/${SERVICE}/ ./services/${SERVICE}/

USER banking
EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn services.${SERVICE_NAME}.app:app --host 0.0.0.0 --port 8000"]
