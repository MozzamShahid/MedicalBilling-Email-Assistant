# Online deployment (Railway): builds the React CRM, then runs the API that serves it.
# Data lives in the DATABASE_URL database (Supabase), so the container keeps no state.

FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=web /app/frontend/dist frontend/dist

WORKDIR /app/backend
# No telemetry pings: they would keep a sleeping (serverless) service awake.
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    CREWAI_TRACING_ENABLED=false \
    CREWAI_DISABLE_TELEMETRY=true \
    OTEL_SDK_DISABLED=true
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips="*"
