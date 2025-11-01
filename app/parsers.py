import os, json
from .schema import ParseResult
from app.utils.common import (
    heuristic_extract_basic, split_sections_vi, parse_about_vi,
    parse_skills_vi, parse_projects_vi, parse_experiences_vi,
    parse_education_vi, guess_location_vi, extract_all_links
)

# Lấy cấu hình từ .env
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("OPENAI_MODEL", "openai/gpt-4o-mini")
LIMIT_MS = int(os.getenv("LLM_TIME_LIMIT_MS", "15000"))
BASE_URL = os.getenv("OPENAI_BASE_URL")  # <-- thêm base_url cho Haimaker

PROMPT = (
    "Bạn là bộ trích xuất CV. Hãy CHỈ trả về JSON đúng theo schema dưới đây.\n"
    "- Nếu thiếu dữ liệu, để null hoặc mảng rỗng.\n"
    "- Chuẩn hoá ngày về YYYY hoặc YYYY-MM.\n"
    "- Lấy tất cả liên kết (LinkedIn, GitHub, Facebook, portfolio/demo) nếu có.\n"
    "Schema:\n"
    "{\n  \"candidate\": {\n    \"full_name\": null, \"email\": null, \"phone\": null, \"location\": null, "
    "\"headline\": null, \"summary\": null, \"links\": {\"linkedin\":null,\"github\":null,\"facebook\":null,"
    "\"portfolio_demo_movie\":null}, \"skills\": [], \"languages\": [], \"quality_score\": 0.0\n  },\n"
    "  \"experiences\": [],\n  \"education\": [],\n  \"certifications\": [],\n  \"projects\": []\n}\n"
    "Văn bản CV:\n"
)

def llm_parse(text: str) -> dict:
    """
    Gọi LLM qua API Haimaker (OpenAI-compatible) nếu có key.
    Nếu không có key -> fallback heuristic (regex) miễn phí.
    """
    if not OPENAI_KEY:
        # 1) Bóc các phần chính theo heading tiếng Việt
        sections = split_sections_vi(text)

        # 2) Khởi tạo kết quả
        pr = ParseResult()

        # 3) Thông tin cơ bản
        base = heuristic_extract_basic(text)
        pr.candidate.full_name = base.get("full_name")
        pr.candidate.email = base.get("email")
        pr.candidate.phone = base.get("phone")
        pr.candidate.location = guess_location_vi(text)
        pr.candidate.links = extract_all_links(text)

        # 4) About me -> headline + summary
        hl, sm = parse_about_vi(
            sections.get("giới thiệu bản thân") or sections.get("gioi thieu ban than") or sections.get(
                "about me") or "")
        pr.candidate.headline = hl
        pr.candidate.summary = sm

        # 5) Skills
        pr.candidate.skills = parse_skills_vi(
            sections.get("kỹ năng") or sections.get("ky nang") or sections.get("skills") or "")

        # 6) Education
        pr.education = parse_education_vi(
            sections.get("học vấn") or sections.get("hoc van") or sections.get("education") or "")

        # 7) Projects
        pr.projects = parse_projects_vi(
            sections.get("dự án") or sections.get("du an") or sections.get("personal projects") or sections.get(
                "projects") or "")

        # 8) Experiences (gộp các mục liên quan)
        exp_sections = [
            sections.get("thực tập") or sections.get("thuc tap") or "",
            sections.get("tham gia dự án") or sections.get("tham gia du an") or "",
            sections.get("kinh nghiệm") or sections.get("kinh nghiem") or sections.get("work experience") or ""
        ]
        pr.experiences = parse_experiences_vi(exp_sections)

        # 9) languages
        langs_sec = sections.get("ngôn ngữ") or sections.get("ngon ngu") or sections.get("languages") or ""
        if langs_sec:
            langs = []
            for ln in langs_sec.splitlines():
                s = ln.strip()
                if not s:
                    continue
                # gom câu ngắn
                s = s.strip("•*- ").strip()
                if s:
                    langs.append(s)
            # unique
            seen = set();
            langs_uniq = []
            for l in langs:
                k = l.lower()
                if k not in seen:
                    langs_uniq.append(l);
                    seen.add(k)
            pr.candidate.languages = langs_uniq

        # 10) raw_text + quality
        pr.raw_text = text
        score = 0.3
        if pr.candidate.email or pr.candidate.phone: score += 0.3
        if pr.candidate.full_name: score += 0.15
        if pr.candidate.skills: score += 0.15
        if pr.experiences or pr.projects or pr.education: score += 0.1
        pr.candidate.quality_score = min(score, 0.98)

        return pr.model_dump()

    # --- Gọi Haimaker (OpenAI-compatible) ---
    from openai import OpenAI
    client_kwargs = {"api_key": OPENAI_KEY}
    if BASE_URL:  # ví dụ https://api.haimaker.io/v1
        client_kwargs["base_url"] = BASE_URL

    client = OpenAI(**client_kwargs)

    msg = PROMPT + text[:60_000]  # giới hạn prompt
    resp = client.chat.completions.create(
        model=MODEL,                   # ví dụ: "openai/gpt-4o-mini"
        messages=[{"role": "user", "content": msg}],
        temperature=0.1,
        timeout=LIMIT_MS/1000.0,
        response_format={"type": "json_object"}
    )
    content = resp.choices[0].message.content
    data = json.loads(content)
    pr = ParseResult(**data)
    pr.raw_text = text
    return pr.model_dump()
