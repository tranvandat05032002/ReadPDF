import re
from typing import List, Tuple, Dict

import requests

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

def fetch_bytes_from_url(url: str) -> bytes:
    """
    Tải nội dung nhị phân (bytes) từ một URL — hỗ trợ HTTP/HTTPS.
    Dùng cho /parse-resume (khi CV có link URL).
    """
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        print(f"[fetch_bytes_from_url] Lỗi khi tải URL {url}: {e}")
        raise