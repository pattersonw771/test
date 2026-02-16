from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2000)


class AnalyzeResponse(BaseModel):
    analysis_id: Optional[int] = None
    status: str = "done"
    input_url: str
    normalized_url: Optional[str] = None
    extraction_kind: Optional[str] = None
    extracted_chars: int = 0
    duration_ms: int = 0
    source: str = "unknown"
    summary: str
    essay: str
    top_signal: str
    global_perspective: str
    bias_scores: Dict[str, float]


class JobCreateResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class FeedbackRequest(BaseModel):
    vote: str = Field(pattern="^(up|down)$")
    note: str = Field(default="", max_length=600)
    analysis_id: Optional[int] = None
