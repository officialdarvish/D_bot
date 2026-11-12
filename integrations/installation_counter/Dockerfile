FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.115.6 uvicorn==0.34.0
WORKDIR /counter
COPY service.py .
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
