FROM python:3.12-slim AS base
WORKDIR /workspace/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend .
COPY sample_data /workspace/sample_data
COPY tests /workspace/tests
COPY pytest.ini /workspace/pytest.ini
RUN useradd --create-home appuser && mkdir -p /workspace/private_documents /home/appuser/.paddlex && chown -R appuser:appuser /workspace /home/appuser
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS worker
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libgl1 libglib2.0-0 fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements-ocr.txt
USER appuser

FROM base AS api
