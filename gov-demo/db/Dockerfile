FROM python:3.12.8-slim-bookworm
RUN useradd --create-home --uid 10001 app
WORKDIR /app
RUN pip install --no-cache-dir psycopg[binary]==3.2.3
COPY seed.py retention.py schema.sql ./
USER app
CMD ["python", "seed.py"]
