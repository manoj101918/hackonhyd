FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY backend ./backend
RUN pip install --no-cache-dir .
COPY data ./data
COPY scripts ./scripts
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "dejavu.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
