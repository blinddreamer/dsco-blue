FROM python:3.12-slim

# Pull Debian security fixes not yet in the base image
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

# Create data directory for persistence
RUN mkdir -p /data

CMD ["python", "-u", "bot.py"]
