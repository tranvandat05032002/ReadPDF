# Định nghĩa Pydantic models

from pydantic import BaseModel, Field
from typing import List, Optional, Dict


class ExperienceItem(BaseModel):
    company: Optional[str] = None
    title: Optional[str] = None
    start_date: Optional[str] = None # YYYY or YYYY-MM
    end_date: Optional[str] = None # YYYY or YYYY-MM or null
    highlights: List[str] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)


class EducationItem(BaseModel):
    school: Optional[str] = None
    degree: Optional[str] = None
    major: Optional[str] = None
    gpa: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ProjectItem(BaseModel):
    name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    desc: Optional[str] = None
    links: List[str] = Field(default_factory=list)
    tech: List[str] = Field(default_factory=list)


class Candidate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    headline: Optional[str] = None
    summary: Optional[str] = None
    links: Dict[str, Optional[str]] = Field(default_factory=dict)
    skills: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    quality_score: float = 0.5


class ParseResult(BaseModel):
    ok: bool = True
    candidate: Candidate = Candidate()
    experiences: List[ExperienceItem] = Field(default_factory=list)
    education: List[EducationItem] = Field(default_factory=list)
    certifications: List[dict] = Field(default_factory=list)
    projects: List[ProjectItem] = Field(default_factory=list)
    raw_text: Optional[str] = None
    parser_version: str = "v1"