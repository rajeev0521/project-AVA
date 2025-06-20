FROM python:3.8-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    portaudio19-dev \
    python3-pyaudio \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create directory for credentials
RUN mkdir -p /root/.config/gcloud

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["python", "ava/main.py"] 