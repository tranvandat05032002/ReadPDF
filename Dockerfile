# --- Base image ---
FROM python:3.11-slim

# Cài Tesseract + gói ngôn ngữ Anh & Việt
RUN apt-get update && apt-get install -y --no-install-recommends \
tesseract-ocr \
tesseract-ocr-eng \
tesseract-ocr-vie \
libglib2.0-0 \
libsm6 \
libxext6 \
libxrender1 \
&& rm -rf /var/lib/apt/lists/*


WORKDIR /srv
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt


COPY app ./app
COPY .env ./.env


ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/srv
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]