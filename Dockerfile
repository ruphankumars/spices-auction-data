# The auction-report pipeline for a Render cron job (scripts/worker.py).
FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends poppler-utils tesseract-ocr imagemagick libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -q requests rapidocr-onnxruntime opencv-python-headless numpy
WORKDIR /app
COPY . .
CMD ["python", "scripts/worker.py"]
