FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SEMIBOT_STATE_ROOT=/app/state

WORKDIR /app

COPY . /app

RUN mkdir -p /app/state/config /app/state/reports /app/state/data

EXPOSE 8000

CMD ["python", "-c", "from semibot_web.server import run; run(host='0.0.0.0', port=8000)"]
