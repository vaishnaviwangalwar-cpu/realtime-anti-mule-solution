# Build stage – install Python deps and copy source
FROM python:3.9-slim AS build
WORKDIR /app

# Install build utilities (none needed for pure pip)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY graph_analyzer.py ./

# Runtime stage – reuse same slim image
FROM python:3.9-slim
WORKDIR /app
COPY --from=build /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
COPY --from=build /app/graph_analyzer.py ./

# optional – not used for HTTP, just for healthchecks
EXPOSE 8080
CMD ["python", "graph_analyzer.py"]