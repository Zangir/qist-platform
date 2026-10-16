# Build from the repository root:  docker build -f backend/Dockerfile -t qist-api .
# The API reads data/*.json (taxonomy, countries, seeds), so the image carries the data folder too.
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY data data
ENV QIST_DB_URL=sqlite:////data/qist.db
EXPOSE 8000
# Set QIST_ADMIN_PASSWORD, QIST_JWT_SECRET and QIST_CORS_ORIGINS in the host; mount a volume at /data so the database survives restarts.
CMD ["sh", "-c", "cd backend && uvicorn app.main:main_app --host 0.0.0.0 --port ${PORT:-8000}"]
