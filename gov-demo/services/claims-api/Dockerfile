FROM python:3.12.8-slim-bookworm
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER app
CMD ["python", "main.py"]
