# ===== Model chọn mặc định / từ ENV =====
import json
import os
import re
from typing import Any, Dict, List

import requests


def resolve_model_name() -> str:
    name = (os.getenv("GEMINI_MODEL_NAME") or "").strip()
    return name if name else "gemini-2.5-pro"

# ===== Chuẩn hoá text/JSON =====
def coerce_str(x: Any) -> str:
    return (x or "").strip() if isinstance(x, str) else ("" if x is None else str(x).strip())

def json_coerce(s: str) -> Dict[str, Any] | List[Any] | None:
    """Cố gắng parse JSON từ string; nếu fail trả None."""
    s = (s or "").strip()
    if not s:
        return None
    # cắt phần thừa nếu model lỡ in thêm text
    start = s.find("{")
    if start == -1:
        start = s.find("[")
    if start > 0:
        s = s[start:]
    # cắt đuôi nếu có rác sau JSON
    # đơn giản: cân ngoặc
    try:
        return json.loads(s)
    except Exception:
        # fallback nhẹ: tìm khối JSON lớn nhất bắt đầu bằng '{'
        # (có thể thay bằng parser robust hơn tuỳ nhu cầu)
        try:
            end = s.rfind("}")
            return json.loads(s[: end + 1])
        except Exception:
            return None

# ===== Kỹ năng → chuỗi hoặc list =====
def to_skills_str(sk: Any) -> str:
    if not sk:
        return ""
    if isinstance(sk, list):
        return ", ".join([coerce_str(x) for x in sk if coerce_str(x)])
    return coerce_str(sk)

# ===== Chuẩn hoá email/phone/location =====
def norm_email(s: str) -> str:
    s = coerce_str(s).lower()
    m = re.search(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", s)
    return m.group(0) if m else ""

def norm_phone(s: str) -> str:
    s = re.sub(r"[^\d+]", "", coerce_str(s))
    # chuẩn hoá dạng Việt Nam: bắt đầu +84 hoặc 0...
    if s.startswith("84") and not s.startswith("+"):
        s = "+" + s
    if s.startswith("0"):
        s = "+84" + s[1:]
    return s

def clean_location(s: str) -> str:
    s = coerce_str(s)
    s = re.sub(r"\s{2,}", " ", s)
    return s

# ===== Tách vị trí ứng tuyển từ subject =====
import re
import unicodedata

def normalize_text(s: str) -> str:
    """Chuẩn hóa text: bỏ dấu, lower, bỏ ký tự thừa."""
    s = s or ""
    s = s.lower().strip()
    s = ''.join(c for c in unicodedata.normalize('NFD', s)
                if unicodedata.category(c) != 'Mn')  # bỏ dấu tiếng Việt
    return s

def extract_position(subject: str) -> str:
    """
    Trích ra vị trí tuyển dụng từ subject email.
    Bao quát chữ hoa, chữ thường, có dấu và các bộ phận phổ biến.
    """
    raw = subject or ""
    norm = normalize_text(raw)

    # Bộ từ khóa mapping (không dấu)
    POSITIONS = {
        "backend": "Backend Developer",
        "front end": "Frontend Developer",
        "frontend": "Frontend Developer",
        "fullstack": "Fullstack Developer",
        "mobile": "Mobile Developer",
        "ios": "iOS Developer",
        "android": "Android Developer",
        "flutter": "Flutter Developer",
        "react": "React Developer",
        "node": "NodeJS Developer",
        "golang": "Golang Developer",
        "python": "Python Developer",
        "java": "Java Developer",
        "php": "PHP Developer",
        "devops": "DevOps Engineer",
        "data": "Data Engineer",
        "machine learning": "Machine Learning Engineer",
        "ai": "AI Engineer",
        "qa": "QA/QC Tester",
        "tester": "QA/QC Tester",
        "test": "QA/QC Tester",
        "designer": "UI/UX Designer",
        "ui ux": "UI/UX Designer",
        "product": "Product Manager",
        "project": "Project Manager",
        "pm": "Project Manager",
        "hr": "HR Executive",
        "human resource": "HR Executive",
        "accountant": "Accountant",
        "ke toan": "Accountant",
        "marketing": "Marketing Executive",
        "sale": "Sales Executive",
        "sales": "Sales Executive",
        "customer service": "Customer Service",
        "support": "Customer Support",
        "business analyst": "Business Analyst",
        "ba": "Business Analyst",
        "intern": "Intern",
        "thuc tap": "Intern",
        "content": "Content Writer",
        "copywriter": "Copywriter",
        "operation": "Operation Executive",
        "it helpdesk": "IT Helpdesk",
        "system admin": "System Administrator",
        "security": "Security Engineer",
        "network": "Network Engineer",
        "r&d": "R&D Engineer",
    }

    # Duyệt tìm keyword khớp trong chuỗi
    for kw, title in POSITIONS.items():
        if re.search(rf"\b{re.escape(kw)}\b", norm):
            return title

    # fallback: thử khớp các pattern chung
    if re.search(r"developer|engineer|programmer", norm):
        return "Software Engineer"

    return "Nằm ngoài tuyển dụng"


# ===== Google Drive helpers =====
def extract_drive_file_id(url: str) -> str:
    """
    Nhận link kiểu:
    - https://drive.google.com/file/d/<FILE_ID>/view?usp=sharing
    - https://drive.google.com/uc?id=<FILE_ID>&export=download
    """
    url = coerce_str(url)
    m = re.search(r"/d/([a-zA-Z0-9_-]{20,})", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]{20,})", url)
    if m:
        return m.group(1)
    raise ValueError("invalid_drive_url")

def download_drive_file(file_id: str) -> bytes:
    """Tải file từ Google Drive không xác thực (chia sẻ công khai)."""
    u = f"https://drive.google.com/uc?export=download&id={file_id}"
    r = requests.get(u, timeout=30)
    r.raise_for_status()
    return r.content

def drive_direct_url(file_id: str) -> str:
    return f"https://drive.google.com/uc?export=download&id={file_id}"

# ===== Tiện ích cắt text gửi LLM =====
MAX_CHARS = int(os.getenv("GEMINI_MAX_CHARS", "12000"))
def truncate_text(s: str, max_len: int = MAX_CHARS) -> str:
    s = coerce_str(s)
    return s if len(s) <= max_len else s[:max_len] + "\n...[TRUNCATED]"

def extract_text_bytes(file_bytes: bytes, mime_type: str, lang: str = "eng") -> tuple[str, str]:
    """
    Trích xuất text từ PDF hoặc ảnh.
    Trả về tuple (text, kind):
    - text: nội dung văn bản trích được
    - kind: "text" nếu là PDF có text, "image" nếu OCR, "unknown" nếu lỗi
    """
    from io import BytesIO
    from pdfminer.high_level import extract_text
    from pdf2image import convert_from_bytes
    import pytesseract

    # 1️⃣ Thử đọc PDF bằng pdfminer (đọc text thật)
    text = ""
    try:
        text = extract_text(BytesIO(file_bytes), maxpages=1)
    except Exception:
        pass

    if text and len(text.strip()) > 50:
        # Có text → PDF dạng text
        full_text = extract_text(BytesIO(file_bytes))
        return full_text.strip(), "text"

    # 2️⃣ Không có text → PDF scan → OCR
    try:
        images = convert_from_bytes(file_bytes)
        ocr_text = ""
        for img in images[:3]:  # chỉ đọc 3 trang đầu cho nhanh
            ocr_text += pytesseract.image_to_string(img, lang=lang or "eng")
        return ocr_text.strip(), "image"
    except Exception as e:
        print("[extract_text_bytes] OCR failed:", e)
        return "", "unknown"