FROM python:3.14-slim

# Install build tools needed by some STT plugins
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ libsndfile1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# SpeechRecognition is required at runtime by ovos-stt-plugin-server but not declared by it
RUN pip install --no-cache-dir "ovos-stt-http-server[audio]" \
                               ovos-stt-plugin-server \
                               SpeechRecognition

# Default config location — mount your own or bake it in
ENV XDG_CONFIG_HOME=/config
WORKDIR /app

EXPOSE 9666

ENTRYPOINT ["ovos-stt-server", "--host", "0.0.0.0", "--port", "9666"]
