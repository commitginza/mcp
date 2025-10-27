FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["sh","-lc","gunicorn -w ${WORKERS:-2} -k gthread --threads ${THREADS:-8} -b 0.0.0.0:${PORT:-8080} ui_app:app"]
