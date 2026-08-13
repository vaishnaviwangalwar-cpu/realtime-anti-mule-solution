FROM python:3.9-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY anomaly_detector.py .
COPY models/ ./models/
COPY utils/ ./utils/
COPY config/ ./config/

# Create data directories
RUN mkdir -p /data /logs /models

# Set environment variables
ENV PYTHONPATH=/app
ENV NUMPY_NUM_THREADS=1
ENV TF_CPP_MIN_LOG_LEVEL=2

# Default command
CMD ["python", "anomaly_detector.py"]