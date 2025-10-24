import os, base64, mimetypes, requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from .ocr import extract_text_bytes
from .parsers import llm_parse
from .utils import fetch_bytes_from_url, gs_post, _guess_mime


load_dotenv()
GS_URL = os.getenv("GS_URL")
GS_TOKEN = os.getenv("GS_TOKEN")


app = FastAPI(title="Resume OCR+Parser API", version="1.0.0")


# ENV
MAX_BYTES = int(os.getenv("MAX_BYTES", "20000000"))
OCR_LANGS = os.getenv("OCR_LANGS", "eng").replace(" ", "")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))


# CORS
origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class UrlReq(BaseModel):
    file_url: str
    file_mime: str | None = None
    lang_hint: str | None = None


class B64Req(BaseModel):
    file_name: str | None = None
    file_mime: str
    file_base64: str
    lang_hint: str | None = None


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/parse-resume")
def parse_resume():
    """
    1) Lấy message mới nhất từ Apps Script (label: New_Apply_Emails has:attachment)
    2) Lấy file_url tương ứng
    3) OCR/parse và trả kết quả
    """
    # 1) Lấy message_id + subject mới nhất
    newest = gs_post({"token": GS_TOKEN, "action": "get_newest_message_id"})
    message_id = newest["message_id"]
    subject    = newest.get("subject", "")

    # 2) Lấy file_url cho message_id đó
    file_info = gs_post({
        "token": GS_TOKEN,
        "action": "get_file_url_for_message",
        "message_id": message_id
    })
    print("file_info -----> ", file_info)
    file_url = file_info["file_url"]
    file_mime = file_info.get("file_mime") or _guess_mime(file_url)

    # 3) Tải file & OCR/parse
    try:
        data = fetch_bytes_from_url(file_url, MAX_BYTES)
    except Exception as e:
        raise HTTPException(400, f"fetch_failed: {e}")

    text, mode = extract_text_bytes(data, file_mime, OCR_LANGS)
    if not text.strip():
        raise HTTPException(422, "empty_text_after_extraction")

    raw = llm_parse(text) or {}
    c = (raw.get("candidate") or raw)

    # 4) Trả về gọn + kèm meta email/file
    return {
        "ok": True,
        "parser_version": "v1",
        "message_id": message_id,
        "subject": subject,
        "file_url": file_url,
        "file_id": file_info.get("file_id"),
        "candidate": {
            "full_name": (c.get("full_name") or "").strip(),
            "email":     (c.get("email") or "").strip(),
            "phone":     (c.get("phone") or "").strip(),
        },
        # tuỳ chọn: trả thêm raw để debug
        # "raw": raw
    }


@app.post("/parse-resume-base64")
def parse_resume_b64(req: B64Req):
    try:
        data = base64.b64decode(req.file_base64)
    except Exception:
        raise HTTPException(400, "invalid_base64")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "file_too_large")
    text, mode = extract_text_bytes(data, req.file_mime, req.lang_hint or OCR_LANGS)
    if not text.strip():
        raise HTTPException(422, "empty_text_after_extraction")
    # parsed = llm_parse(text)
    # parsed.update({"ok": True, "parser_version": "v1"})
    # return parsed

    # custom response
    raw = llm_parse(text) or {}  # có thể là {}, None
    # Hỗ trợ cả 2 kiểu: candidate.* hoặc field ở root (đề phòng LLM lệch format)
    c = (raw.get("candidate") or raw)
    resp = {
        "ok": True,
        "candidate": {
            "full_name": (c.get("full_name") or "").strip(),
            "email": (c.get("email") or "").strip(),
            "phone": (c.get("phone") or "").strip(),
        },
    }
    return resp


# --- helpers ---


# def _guess_mime(url: str) -> str:
#     mime, _ = mimetypes.guess_type(url)
#     return mime or "application/pdf"

# def gs_get_file_url_by_msg(message_id: str) -> str:
#     """Nhờ Apps Script lấy/tạo file Drive từ Gmail message_id, trả về file_url."""
#     payload = {
#         "token": GS_TOKEN,
#         "action": "get_file_url_for_message",
#         "message_id": message_id
#     }
#     r = requests.post(GS_URL, json=payload, timeout=30)
#     try:
#         r.raise_for_status()
#     except Exception:
#         raise HTTPException(502, f"GS error: {r.text}")
#     data = r.json()
#     if not data.get("ok"):
#         raise HTTPException(502, f"GS fail: {data}")
#     return data["file_url"]
#
# def gs_upload_and_get_url(file_name: str, file_mime: str, file_b64: str) -> str:
#     """Nhờ Apps Script upload base64 lên Drive và trả về file_url."""
#     payload = {
#         "token": GS_TOKEN,
#         "action": "upload_and_share",
#         "file_name": file_name,
#         "file_mime": file_mime,
#         "file_base64": file_b64
#     }
#     r = requests.post(GS_URL, json=payload, timeout=60)
#     r.raise_for_status()
#     data = r.json()
#     if not data.get("ok"):
#         raise HTTPException(502, f"GS fail: {data}")
#     return data["file_url"]

# def gs_post(payload):
#     r = requests.post(GS_URL, json=payload, timeout=60)
#     r.raise_for_status()
#     data = r.json()
#     if not data.get("ok"):
#         raise HTTPException(502, f"GS fail: {data}")
#     return data
#
# @app.post("/orchestrate")
# def orchestrate():
#     # 1️⃣ Gọi Apps Script lấy message_id mới nhất
#     newest = gs_post({
#         "token": GS_TOKEN,
#         "action": "get_newest_message_id"
#     })
#     message_id = newest["message_id"]
#     subject = newest["subject"]
#     print("📩 Newest message_id =", message_id)
#
#     # 2️⃣ Gọi lại Apps Script để lấy file_url
#     file_info = gs_post({
#         "token": GS_TOKEN,
#         "action": "get_file_url_for_message",
#         "message_id": message_id,
#         "subject": subject
#     })
#
#     # 3️⃣ Trả về cho client
#     return {
#         "ok": True,
#         "message_id": message_id,
#         **file_info,
#         "subject": subject
#     }