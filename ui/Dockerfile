FROM python:3.11-slim
WORKDIR /app
COPY ui/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ui/ ./
CMD ["gunicorn", "-w", "2", "-k", "gthread", "--threads", "8", "-b", "0.0.0.0:${PORT}", "ui_app:app"]
