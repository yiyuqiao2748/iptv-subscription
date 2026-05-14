FROM python:3.12-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Create output + cache dirs
RUN mkdir -p output cache logs

EXPOSE 8899

CMD ["python", "main.py", "--host", "0.0.0.0", "--port", "8899"]
