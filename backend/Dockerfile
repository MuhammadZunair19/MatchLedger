FROM python:3.12-slim
WORKDIR /workspace/backend
COPY backend/requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY backend .
COPY sample_data /workspace/sample_data
COPY tests /workspace/tests
COPY pytest.ini /workspace/pytest.ini
RUN useradd --create-home appuser && chown -R appuser:appuser /workspace
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
