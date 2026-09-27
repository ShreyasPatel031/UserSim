# UserSim backend + report pages for Cloud Run. Browsers run on Browserbase,
# so no local Chromium is installed here.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/src:/app PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements-vercel.txt .
RUN pip install -r requirements-vercel.txt "uvicorn[standard]>=0.30"
COPY src ./src
COPY mvp ./mvp
COPY api ./api
COPY scripts/local ./scripts/local
COPY pyproject.toml vercel.json ./
CMD exec uvicorn mvp.server:app --host 0.0.0.0 --port ${PORT:-8080} --timeout-keep-alive 75
