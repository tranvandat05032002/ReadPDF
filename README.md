# Resume OCR+Parser API (AgilePoint-ready)


FastAPI service đọc/scan CV, trả JSON theo schema chuẩn để map vào Data Entities của AgilePoint.


## Chạy local
```bash
python -m venv .venv && source .venv/bin/activate # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env .env # điền OPENAI_API_KEY nếu muốn dùng LLM
uvicorn app.main:app --host 0.0.0.0 --port 8080