import re, os
from typing import List, Tuple, Dict

import requests
from fastapi import HTTPException

# --- ĐÃ CÓ ở bạn, giữ nguyên/đặt ở đầu file ---
# heuristic_extract_basic(), fetch_bytes_from_url()

# ====== Bổ sung cho CV tiếng Việt ======

# Heading tiếng Việt (không dấu & có dấu)
SECTION_PAT = re.compile(
    r'^(giới thiệu bản thân|gioi thieu ban than|about me|học vấn|hoc van|education|'
    r'dự án|du an|personal projects|projects|'
    r'thực tập|thuc tap|internship|'
    r'tham gia dự án|tham gia du an|kinh nghiệm|kinh nghiem|work experience|'
    r'kỹ năng|ky nang|skills|'
    r'ngôn ngữ|ngon ngu|languages)\b.*$',
    re.IGNORECASE | re.MULTILINE
)

BULLET = re.compile(r'^[\s•\-\*]+')
URL_RE = re.compile(r'https?://\S+')

DATE_RANGE = re.compile(
    r'(?P<from>\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s*[-–]\s*(?P<to>(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|hiện tại|hien tai|present))',
    re.IGNORECASE
)

VIET_LOC_HINT = re.compile(
    r'(việt\s?nam|vietnam|hà nội|ha noi|đà nẵng|da nang|huế|hue|hcm|sài gòn|sai gon)',
    re.IGNORECASE
)

def _clean_link(u: str) -> str:
    # bỏ dấu chấm/ký tự thừa cuối link
    return u.rstrip(').,];:')

def split_sections_vi(text: str) -> Dict[str, str]:
    """
    Chia văn bản thành các vùng theo heading tiếng Việt -> dict{k:body}
    """
    lines = text.splitlines()
    sections: Dict[str, List[str]] = {}
    current = None
    buf: List[str] = []
    def flush():
        nonlocal buf, current
        if current and buf:
            body = "\n".join(buf).strip()
            sections[current] = body
    for ln in lines:
        s = ln.strip()
        if SECTION_PAT.match(s):
            flush()
            key = SECTION_PAT.match(s).group(1).lower()
            current = key
            buf = []
        else:
            buf.append(ln)
    flush()
    return sections

def parse_about_vi(sec: str) -> Tuple[str, str]:
    """Trả (headline, summary) từ 'Giới Thiệu Bản Thân'."""
    if not sec:
        return None, None
    lines = [BULLET.sub('', l).strip() for l in sec.splitlines() if l.strip()]
    headline = lines[0] if lines else None
    summary = " ".join(lines[1:])[:1000] if len(lines) > 1 else None
    return headline, summary

def parse_skills_vi(sec: str) -> List[str]:
    """
    Gom các dòng sau 'Kỹ Năng' thành danh sách kỹ năng (tách theo dấu : , ; /)
    """
    if not sec:
        return []
    out: List[str] = []
    for ln in sec.splitlines():
        s = BULLET.sub('', ln).strip()
        if not s:
            continue
        # bỏ phần nhãn trước dấu ":" (VD: 'Back-End: Node.js, Golang,...')
        if ':' in s:
            s = s.split(':', 1)[1]
        parts = re.split(r'[,\u00B7;\\/]', s)
        for p in parts:
            t = re.sub(r'\s+', ' ', p).strip()
            if t and len(t) <= 60:
                out.append(t)
    # unique (case-insensitive)
    uniq, seen = [], set()
    for w in out:
        k = w.lower()
        if k not in seen:
            uniq.append(w)
            seen.add(k)
    return uniq

def parse_education_vi(sec: str) -> List[Dict]:
    if not sec:
        return []
    items = []
    blocks = re.split(r'\n\s*\n', sec.strip())
    for blk in blocks:
        lines = [BULLET.sub('', l).strip() for l in blk.splitlines() if l.strip()]
        if not lines:
            continue
        item = {"school": lines[0]}
        for l in lines[1:]:
            if 'gpa' in l.lower():
                item["gpa"] = l.split(':', 1)[-1].strip()
            if re.search(r'(cử nhân|cu nhan|kỹ sư|ky su|software|cntt|cnpm|it|degree)', l, re.I):
                item.setdefault("degree", l)
        items.append(item)
    return items

def _to_yyyy_mm(d: str) -> str:
    parts = re.split(r'[/-]', d)
    if len(parts) == 3:
        dd, mm, yy = parts
    elif len(parts) == 2:
        dd, mm = parts; yy = '1900'
    else:
        return None
    if len(yy) == 2:
        yy = ('20' if int(yy) < 70 else '19') + yy
    return f"{yy}-{int(mm):02d}"

def parse_projects_vi(sec: str) -> List[Dict]:
    if not sec:
        return []
    items = []
    # chia block theo khoảng trắng đôi
    blocks = re.split(r'\n\s*\n', sec.strip())
    for blk in blocks:
        lines = [BULLET.sub('', l).strip() for l in blk.splitlines() if l.strip()]
        if not lines:
            continue
        name = lines[0]
        date_from = date_to = None
        m = DATE_RANGE.search(blk)
        if m:
            date_from = _to_yyyy_mm(m.group('from'))
            date_to = None if 'hiện tại' in m.group('to').lower() or 'hien tai' in m.group('to').lower() or 'present' in m.group('to').lower() else _to_yyyy_mm(m.group('to'))
        tech: List[str] = []
        links: List[str] = []
        desc_lines: List[str] = []
        for l in lines[1:]:
            if 'công nghệ' in l.lower() or 'technolog' in l.lower():
                # lấy phần sau dấu ":" rồi tách
                payload = l.split(':', 1)[-1]
                tech.extend([x.strip() for x in re.split(r'[,\u00B7;\\/]', payload) if x.strip()])
            elif 'source code' in l.lower() or 'demo' in l.lower():
                for u in URL_RE.findall(l):
                    links.append(_clean_link(u))
            else:
                desc_lines.append(l)
        items.append({
            "name": name,
            "start_date": date_from,
            "end_date": date_to,
            "desc": " ".join(desc_lines)[:800] if desc_lines else None,
            "links": links,
            "tech": tech
        })
    return items

def parse_experiences_vi(sec_list: List[str]) -> List[Dict]:
    """
    Nhận vào list các section liên quan tới kinh nghiệm: [ 'Thực tập', 'Tham gia dự án', 'Kinh nghiệm' ... ]
    Tách block theo khoảng trắng đôi, lấy dòng đầu làm 'company/title' đơn giản, gom 3-6 bullet làm highlights.
    """
    items = []
    for sec in sec_list:
        if not sec:
            continue
        blocks = re.split(r'\n\s*\n', sec.strip())
        for blk in blocks:
            lines = [BULLET.sub('', l).strip() for l in blk.splitlines() if l.strip()]
            if not lines:
                continue
            # Ngày
            m = DATE_RANGE.search(blk)
            date_from = date_to = None
            if m:
                date_from = _to_yyyy_mm(m.group('from'))
                date_to = None if 'hiện tại' in m.group('to').lower() or 'hien tai' in m.group('to').lower() or 'present' in m.group('to').lower() else _to_yyyy_mm(m.group('to'))
            # company/title rất đơn giản: lấy dòng đầu làm 'name' (nhiều CV VN ghi tên dự án/cty)
            head = lines[0]
            highlights = [l for l in lines[1:] if len(l) > 2][:8]
            items.append({
                "company": head,
                "title": None,
                "start_date": date_from,
                "end_date": date_to,
                "highlights": highlights,
                "skills": []
            })
    return items

def guess_location_vi(text: str) -> str:
    # lấy dòng đầu có từ khoá địa chỉ Việt Nam
    for ln in text.splitlines()[:60]:
        if VIET_LOC_HINT.search(ln):
            return ln.strip()
    return None

def extract_all_links(text: str) -> Dict[str, str]:
    m = {"linkedin": None, "github": None, "facebook": None, "portfolio_demo_movie": None}
    for u in URL_RE.findall(text):
        u = _clean_link(u)
        low = u.lower()
        if 'linkedin.com' in low:
            m["linkedin"] = u
        elif 'github.com' in low:
            m["github"] = u
        elif 'facebook.com' in low:
            m["facebook"] = u
        elif 'vercel.app' in low or 'portfolio' in low or 'movie' in low:
            m["portfolio_demo_movie"] = u
    return m


def heuristic_extract_basic(text: str) -> dict:
    """
    Trích xuất cơ bản các thông tin như tên, email, số điện thoại, và liên kết.
    Dùng cho chế độ fallback (không có LLM).
    """
    email = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    phone = re.findall(r"(?:\+?\d{1,3})?[\s\-]?(?:\(?\d{2,4}\)?[\s\-]?)?\d{3,4}[\s\-]?\d{3,4}", text)
    links = re.findall(r"https?://[^\s)]+", text)

    # Dòng đầu tiên viết hoa >2 từ, không chứa @ hoặc số
    lines = text.splitlines()
    full_name = None
    for ln in lines[:10]:
        ln_strip = ln.strip()
        if len(ln_strip.split()) >= 2 and not re.search(r"[\d@]", ln_strip):
            if all(word[0].isupper() for word in ln_strip.split() if word):
                full_name = ln_strip
                break

    return {
        "full_name": full_name,
        "email": email[0] if email else None,
        "phone": phone[0] if phone else None,
        "links": links,
    }

def fetch_bytes_from_url(url: str, max_bytes: int = 10 * 1024 * 1024) -> bytes:
    """
    Tải nội dung nhị phân (bytes) từ một URL — hỗ trợ HTTP/HTTPS.
    Có kiểm tra kích thước tối đa (mặc định 10MB).
    """
    try:
        with requests.get(url, stream=True, timeout=15) as resp:
            resp.raise_for_status()
            total = 0
            chunks = []
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail="file_too_large")
                chunks.append(chunk)
            return b"".join(chunks)
    except Exception as e:
        print(f"[fetch_bytes_from_url] Lỗi khi tải URL {url}: {e}")
        raise HTTPException(status_code=400, detail=f"fetch_failed: {e}")


# ---- helpers ----
def gs_post(payload: dict) -> dict:
    r = requests.post(os.getenv("GS_URL") , json=payload, timeout=60)
    try:
        r.raise_for_status()
    except Exception:
        # ném lỗi có body để dễ debug
        raise HTTPException(502, f"GS error: {r.text}")
    data = r.json()
    if not data.get("ok"):
        raise HTTPException(502, f"GS fail: {data}")
    return data

def _guess_mime(url: str) -> str:
    # fallback đơn giản theo đuôi file
    u = url.lower()
    if u.endswith(".pdf"): return "application/pdf"
    if u.endswith(".docx"): return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if u.endswith(".doc"): return "application/msword"
    return "application/octet-stream"

def extract_address(location: str) -> str:
    """
    Lấy phần sau email hoặc ký tự đặc biệt, ví dụ sau dấu ')' hoặc '#'
    """
    if not location:
        return ""

    # loại bỏ (cid:209) và các ký tự lạ
    cleaned = re.sub(r"\(cid:[^)]+\)", "", location)

    # tách theo email hoặc dấu '#' và lấy phần phía sau
    parts = re.split(r"#|\s[\w\.-]+@[\w\.-]+", cleaned, maxsplit=1)
    if len(parts) > 1:
        address = parts[-1]
    else:
        # fallback: nếu không tách được thì thử tìm cụm dạng số nhà hoặc từ khóa địa chỉ
        m = re.search(r"(\d+\/\d+.*)", cleaned)
        address = m.group(1) if m else cleaned

    # dọn khoảng trắng thừa
    return address.strip(" ,;:-")

def to_skills_str(v):
    import re
    if not v:
        return ""
    if isinstance(v, list):
        items = v
    elif isinstance(v, str):
        items = re.split(r"[,\n;•|/]+", v)
    else:
        return ""
    cleaned, seen, out = [], set(), []
    for s in items:
        if isinstance(s, str):
            t = re.sub(r"\s+", " ", s).strip(" .,-")
            if t:
                cleaned.append(t)
    for t in cleaned:
        k = t.lower()
        if k not in seen:
            seen.add(k); out.append(t)
    return ", ".join(out)

def extract_position(subject: str) -> str:
    """
    Trích ra vị trí tuyển dụng từ subject, ví dụ:
    'Ứng tuyển vị trí Backend - Trần Văn Đạt' => 'Backend'
    """
    if not subject:
        return ""

    # match các dạng thường gặp
    m = re.search(r"vị trí\s+([A-Za-zÀ-ỹ\s\-_/]+)", subject, re.IGNORECASE)
    if m:
        pos = m.group(1).strip(" -–—")
        # chỉ lấy 1-2 từ đầu (ví dụ: "Backend Developer" / "Fullstack")
        pos = re.split(r"[-–—,/]", pos)[0].strip()
        return pos

    # fallback: thử tìm keyword quen thuộc
    for kw in ["Backend", "FrontEnd", "Fullstack", "Mobile", "DevOps"]:
        if kw.lower() in subject.lower():
            return kw
    return ""