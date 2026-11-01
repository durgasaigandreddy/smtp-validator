FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/srv
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
COPY sql ./sql
COPY examples ./examples
COPY tests ./tests
CMD ["uvicorn", "app.api:app", "--host", "127.0.0.1", "--port", "8000"]
