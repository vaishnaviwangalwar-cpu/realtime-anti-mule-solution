FROM python:3.9-slim

WORKDIR /app

# Install system dependencies for Kafka and Redis client libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the generator source code
COPY generate_data.py .
COPY scripts/ ./scripts/

# Set entrypoint to the generator script
ENTRYPOINT ["python", "generate_data.py"]