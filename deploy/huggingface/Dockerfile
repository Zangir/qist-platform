# Hugging Face Space (Docker). Built from the folder that build_space.py assembles; see deploy/huggingface/DEPLOY.md.
FROM python:3.12-slim
RUN useradd -m -u 1000 user
WORKDIR /app
COPY --chown=user backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY --chown=user backend backend
COPY --chown=user data data
COPY --chown=user pipeline pipeline
USER user
# The database lives on the Space's Persistent Storage, mounted at /data. Without it the app refuses to start rather than
# quietly keeping accounts on a disk that is wiped at every restart.
ENV QIST_DB_URL=sqlite:////data/qist.db \
    QIST_TRUST_PROXY=1 \
    PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "cd backend && uvicorn app.main:main_app --host 0.0.0.0 --port 7860 --proxy-headers --forwarded-allow-ips='*'"]
