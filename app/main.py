import os, base64
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import google.generativeai as genai

from app.parsers import llm_parse
from app.utils.common import fetch_bytes_from_url, gs_post, _guess_mime, extract_address
from app.utils.pdf import (resolve_model_name,
                           coerce_str, json_coerce, to_skills_str,
                           norm_email, norm_phone, clean_location, extract_position,
                           extract_drive_file_id, download_drive_file, drive_direct_url,
                           truncate_text, extract_text_bytes)
from app.promt.geminni import PROMPT_RESUME_PARSER
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
    cand = (raw.get("candidate") or {})

    skills_str = to_skills_str(cand.get("skills") or cand.get("skill") or raw.get("skills"))

    # skill = (raw.get("skills") or raw)
    # school = data["education"][0]["school"]
    # gpa = data["education"][0]["gpa"]

    # 4) Trả về gọn + kèm meta email/file
    # skills_str = ", ".join(skill or "").strip())
    school = gpa = ""
    edu = raw.get("education") or []
    if isinstance(edu, dict):
        school = (edu.get("school") or "").strip()
        gpa = (edu.get("gpa") or "").strip()
    elif isinstance(edu, list) and len(edu) > 0 and isinstance(edu[0], dict):
        school = (edu[0].get("school") or "").strip()
        gpa = (edu[0].get("gpa") or "").strip()

    position = extract_position(subject)

    return {
        "ok": True,
        "parser_version": "v1",
        "message_id": message_id,
        "subject": subject,
        "position": position,
        "file_url": file_url,
        "file_id": file_info.get("file_id"),
        "candidate": {
            "full_name": (cand.get("full_name") or "").strip(),
            "email": (cand.get("email") or "").strip(),
            "phone": (cand.get("phone") or "").strip(),
            "location": extract_address((cand.get("location") or "").strip()),
            "skills": skills_str,
            "school": school,
            "gpa": gpa,
        }
    }

# Đọc PDF với Gemini
@app.post("/gemini/parse-resume")
def parse_resume_gemini():
    client = genai
    # Lấy file info
    newest = gs_post({"token": GS_TOKEN, "action": "get_newest_message_id"})
    message_id = newest["message_id"]
    subject = newest.get("subject", "")

    file_info = gs_post({
        "token": GS_TOKEN,
        "action": "get_file_url_for_message",
        "message_id": message_id
    })
    file_url = file_info["file_url"]
    file_mime = file_info.get("file_mime") or _guess_mime(file_url)
    file_sub = file_info.get("message_id")

    # 1) API key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(500, "missing_env_GEMINI_API_KEY")
    client.configure(api_key=api_key)

    # 2) Lấy file từ Google Drive
    drive_url = coerce_str(file_url)
    if not drive_url:
        raise HTTPException(400, "file_url_required")

    try:
        file_id = extract_drive_file_id(drive_url)
    except HTTPException as e:
        raise e

    pdf_bytes = download_drive_file(file_id)
    if not pdf_bytes:
        raise HTTPException(422, "empty_file_downloaded")

    # 3) Trích TEXT trước khi gọi Gemini
    file_mime = "application/pdf"
    text, kind = extract_text_bytes(pdf_bytes, file_mime, "vie+eng")

    # 4) Gọi Gemini (model hợp lệ)
    model_name = resolve_model_name()
    model = client.GenerativeModel(model_name=model_name)

    try:
        if kind == "text" and text and len(text.strip()) >= 100:
            # ✅ PDF có text thật → gửi TEXT
            text_for_llm = truncate_text(text)
            resp = model.generate_content([PROMPT_RESUME_PARSER, text_for_llm])
        else:
            # ⚠️ PDF scan/ít text → gửi BLOB PDF
            pdf_blob = {"mime_type": "application/pdf", "data": pdf_bytes}
            resp = model.generate_content([PROMPT_RESUME_PARSER, pdf_blob])
    except Exception as e:
        raise HTTPException(502, f"gemini_error: {e}")

    # 5) Parse JSON từ model
    raw = json_coerce(coerce_str(getattr(resp, "text", ""))) or {}
    cand = raw.get("candidate") if isinstance(raw, dict) else {}
    if not isinstance(cand, dict):
        cand = {}

    # 6) Chuẩn hoá về schema trả về
    position = extract_position(subject)

    skills_str = to_skills_str(cand.get("skills") or cand.get("skill") or raw.get("skills"))
    # fallback lấy school/gpa từ education[0] nếu cần
    if isinstance(raw.get("education"), list) and raw["education"]:
        school = coerce_str(cand.get("school") or raw["education"][0].get("school"))
        gpa    = coerce_str(cand.get("gpa")    or raw["education"][0].get("gpa"))
    else:
        school = coerce_str(cand.get("school"))
        gpa    = coerce_str(cand.get("gpa"))

    email    = norm_email(coerce_str(cand.get("email")))
    phone    = norm_phone(coerce_str(cand.get("phone")))
    location = clean_location(coerce_str(cand.get("location")))

    return {
        "ok": True,
        "parser_version": "v1",
        "message_id": message_id,
        "subject": subject,
        "position": position,
        "file_url": f"https://drive.google.com/uc?export=download&id={file_id}",
        "file_id": file_id,
        "candidate": {
            "full_name": coerce_str(cand.get("full_name")),
            "email": email,
            "phone": phone,
            "location": location,
            "skills": skills_str,
            "school": school,
            "gpa": gpa,
        }
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
    parsed = llm_parse(text)
    parsed.update({"ok": True, "parser_version": "v1"})
    return parsed

    # # custom response
    # raw = llm_parse(text) or {}  # có thể là {}, None
    # # Hỗ trợ cả 2 kiểu: candidate.* hoặc field ở root (đề phòng LLM lệch format)
    # c = (raw.get("candidate") or raw)
    # resp = {
    #     "ok": True,
    #     "candidate": {
    #         "full_name": (c.get("full_name") or "").strip(),
    #         "email": (c.get("email") or "").strip(),
    #         "phone": (c.get("phone") or "").strip(),
    #     },
    # }
    # return resp


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