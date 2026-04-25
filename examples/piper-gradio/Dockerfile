FROM python:3.11-slim

# Install system dependencies for speech phonemization
RUN apt-get update && apt-get install -y \
    libasound2-dev \
    espeak-ng \
    libespeak-ng1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Ensure we have a local storage for temp audio
RUN mkdir -p /app/audio && chmod 777 /app/audio

# Install Python packages
RUN pip install --no-cache-dir gradio piper-tts

# Copy application files (app.py and models)
COPY . .

EXPOSE 7860
CMD ["python", "app.py"]
