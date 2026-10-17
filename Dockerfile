FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=4030 \
    FINOPS_DB_PATH=/data/finops_audit.db

RUN mkdir -p /data

COPY finops_agent.py /app/finops_agent.py
COPY finops_service /app/finops_service
COPY tests /app/tests

EXPOSE 4030

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4030/health', timeout=2)" || exit 1

CMD ["python3", "finops_agent.py", "serve", "--host", "0.0.0.0", "--port", "4030"]
