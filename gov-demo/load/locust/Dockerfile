FROM python:3.12.8-slim-bookworm
RUN useradd --create-home --uid 10001 app
WORKDIR /app
RUN pip install --no-cache-dir locust==2.32.4
COPY locustfile.py shapes.py ./
USER app
# --autostart begins the test at once, the shape decides how many users run (none is zero users).
CMD ["locust", "-f", "locustfile.py", "--host", "http://web:8080", "--autostart"]
