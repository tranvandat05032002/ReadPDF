import os, base64, mimetypes
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from .ocr import extract_text_bytes
from .parsers import llm_parse
from .utils import fetch_bytes_from_url


load_dotenv()


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
def parse_resume(req: UrlReq):
    try:
        data = fetch_bytes_from_url(req.file_url, MAX_BYTES)
    except Exception as e:
        raise HTTPException(400, f"fetch_failed: {e}")
    mime = req.file_mime or _guess_mime(req.file_url)
    text, mode = extract_text_bytes(data, mime, req.lang_hint or OCR_LANGS)
    if not text.strip():
        raise HTTPException(422, "empty_text_after_extraction")
    parsed = llm_parse(text)
    parsed.update({"ok": True, "parser_version": "v1"})
    return parsed


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


# --- helpers ---


def _guess_mime(url: str) -> str:
    mime, _ = mimetypes.guess_type(url)
    return mime or "application/pdf"