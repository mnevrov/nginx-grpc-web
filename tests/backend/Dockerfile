FROM python:3.12-slim

WORKDIR /app

COPY tests/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tests/proto/test.proto /proto/test.proto
COPY tests/backend/server.py /app/server.py

RUN mkdir -p /app/gen && \
    python -m grpc_tools.protoc \
      -I/proto \
      --python_out=/app/gen \
      --grpc_python_out=/app/gen \
      /proto/test.proto

ENV PYTHONUNBUFFERED=1
EXPOSE 50051

CMD ["python", "/app/server.py"]
