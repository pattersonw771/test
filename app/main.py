import time
import uuid
from typing import Dict, Optional

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth_utils import hash_password, new_session_token, session_expiry, verify_password
from app.bias_model import full_bias_analysis
from app.schemas import AnalyzeRequest, JobCreateResponse, JobStatusResponse
from app.scraper import ScrapeError, detect_source, extract_content
from app.storage import (
    create_job,
    create_user,
    create_user_session,
    delete_user_session,
    get_job,
    get_metrics,
    get_user_by_email,
    get_user_by_session_token,
    init_db,
    list_history,
    log_event,
    save_feedback,
    save_history,
    update_job_status,
)

app = FastAPI(title="EquiLens")

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
templates = Jinja2Templates(directory="frontend/templates")

AUTH_COOKIE = "equilens_auth"
SESSION_COOKIE = "equilens_sid"


def to_percent(value):
    try:
        v = float(value) * 100
        return max(0, min(round(v, 1), 100))
    except Exception:
        return 0.0


def ensure_session_id(request: Request) -> str:
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        return session_id
    return uuid.uuid4().hex


def get_current_user(request: Request) -> Optional[Dict]:
    token = request.cookies.get(AUTH_COOKIE)
    if not token:
        return None
    return get_user_by_session_token(token)


def _history_for_context(session_id: str, user_id: Optional[int]):
    if user_id is not None:
        return list_history(session_id, user_id=user_id)
    return list_history(session_id)


def render_with_context(request: Request, template_name: str, context: Dict, *, status_code: int = 200):
    session_id = context.get("session_id") or ensure_session_id(request)
    current_user = context.get("current_user")
    user_id = current_user["id"] if current_user else None

    payload = {
        "request": request,
        "current_user": current_user,
        "history": _history_for_context(session_id, user_id),
        **context,
    }
    response = templates.TemplateResponse(template_name, payload, status_code=status_code)

    if SESSION_COOKIE not in request.cookies:
        response.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 60)

    return response


def run_analysis_pipeline(input_url: str, session_id: str, user_id: Optional[int] = None) -> Dict:
    started = time.perf_counter()

    extraction = extract_content(input_url)
    article_text = extraction["text"]
    normalized_url = extraction.get("normalized_url", input_url)
    extraction_kind = extraction.get("content_kind", "unknown")

    source = detect_source(normalized_url)
    analysis = full_bias_analysis(article_text, source)
    scores = analysis["bias_scores"]

    duration_ms = int((time.perf_counter() - started) * 1000)

    result = {
        "input_url": input_url,
        "normalized_url": normalized_url,
        "extraction_kind": extraction_kind,
        "extracted_chars": len(article_text),
        "duration_ms": duration_ms,
        "source": source,
        "summary": analysis["summary"],
        "essay": analysis["essay"],
        "top_signal": analysis["top_signal"],
        "global_perspective": analysis.get("global_perspective", ""),
        "bias_scores": scores,
        "left_pct": to_percent(scores.get("Left")),
        "center_pct": to_percent(scores.get("Center")),
        "right_pct": to_percent(scores.get("Right")),
    }

    analysis_id = save_history(
        {
            "session_id": session_id,
            "user_id": user_id,
            "input_url": input_url,
            "normalized_url": normalized_url,
            "source": source,
            "extraction_kind": extraction_kind,
            "extracted_chars": len(article_text),
            "duration_ms": duration_ms,
            "summary": result["summary"],
            "global_perspective": result["global_perspective"],
            "top_signal": result["top_signal"],
            "left_pct": result["left_pct"],
            "center_pct": result["center_pct"],
            "right_pct": result["right_pct"],
            "result_json": result,
        }
    )

    result["analysis_id"] = analysis_id
    return result


def process_job(job_id: str, input_url: str, session_id: str, user_id: Optional[int] = None) -> None:
    update_job_status(job_id, "running")
    try:
        result = run_analysis_pipeline(input_url, session_id, user_id=user_id)
        update_job_status(job_id, "done", result=result)
    except Exception as e:
        update_job_status(job_id, "failed", error=str(e))


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    session_id = ensure_session_id(request)
    current_user = get_current_user(request)
    user_id = current_user["id"] if current_user else None
    log_event(session_id, "page_view", {"page": "home"}, user_id=user_id)
    return render_with_context(request, "index.html", {"session_id": session_id, "current_user": current_user})


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    session_id = ensure_session_id(request)
    return render_with_context(request, "signup.html", {"session_id": session_id, "current_user": get_current_user(request)})


@app.post("/signup", response_class=HTMLResponse)
def signup(request: Request, email: str = Form(...), password: str = Form(...)):
    session_id = ensure_session_id(request)

    try:
        password_hash = hash_password(password)
        user_id = create_user(email, password_hash)
        token = new_session_token()
        create_user_session(token, user_id, session_expiry().isoformat())

        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(AUTH_COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
        if SESSION_COOKIE not in request.cookies:
            response.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 60)
        log_event(session_id, "signup_success", {"email": email.lower()}, user_id=user_id)
        return response
    except ValueError as e:
        return render_with_context(
            request,
            "signup.html",
            {"session_id": session_id, "error": str(e), "email": email},
            status_code=400,
        )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    session_id = ensure_session_id(request)
    return render_with_context(request, "login.html", {"session_id": session_id, "current_user": get_current_user(request)})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    session_id = ensure_session_id(request)
    user = get_user_by_email(email)

    if not user or not verify_password(password, user["password_hash"]):
        return render_with_context(
            request,
            "login.html",
            {"session_id": session_id, "error": "Invalid email or password.", "email": email},
            status_code=400,
        )

    token = new_session_token()
    create_user_session(token, user["id"], session_expiry().isoformat())
    log_event(session_id, "login_success", {"email": email.lower()}, user_id=user["id"])

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(AUTH_COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    if SESSION_COOKIE not in request.cookies:
        response.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 60)
    return response


@app.post("/logout")
def logout(request: Request):
    session_id = ensure_session_id(request)
    token = request.cookies.get(AUTH_COOKIE)
    if token:
        delete_user_session(token)
    log_event(session_id, "logout", {})

    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(AUTH_COOKIE)
    return response


@app.post("/analyze", response_class=HTMLResponse)
def analyze(request: Request, url: str = Form(...)):
    session_id = ensure_session_id(request)
    current_user = get_current_user(request)
    user_id = current_user["id"] if current_user else None
    log_event(session_id, "analyze_submit", {"url": url}, user_id=user_id)

    try:
        result = run_analysis_pipeline(url, session_id, user_id=user_id)
        log_event(session_id, "analyze_success", {"analysis_id": result["analysis_id"]}, user_id=user_id)
        return render_with_context(
            request,
            "index.html",
            {
                "session_id": session_id,
                "current_user": current_user,
                "input_link": result["input_url"],
                "analysis_id": result["analysis_id"],
                "summary": result["summary"],
                "essay": result["essay"],
                "top_signal": result["top_signal"],
                "global_perspective": result["global_perspective"],
                "left_pct": result["left_pct"],
                "center_pct": result["center_pct"],
                "right_pct": result["right_pct"],
                "source": result["source"],
                "extraction_kind": result["extraction_kind"],
                "extracted_chars": result["extracted_chars"],
                "duration_ms": result["duration_ms"],
            },
        )
    except ScrapeError as e:
        log_event(session_id, "analyze_scrape_error", {"error": str(e)}, user_id=user_id)
        return render_with_context(
            request,
            "index.html",
            {
                "session_id": session_id,
                "current_user": current_user,
                "input_link": url,
                "error": str(e),
            },
            status_code=400,
        )
    except Exception as e:
        log_event(session_id, "analyze_error", {"error": str(e)}, user_id=user_id)
        return render_with_context(
            request,
            "index.html",
            {
                "session_id": session_id,
                "current_user": current_user,
                "input_link": url,
                "error": "Analysis failed. Please try again in a moment.",
            },
            status_code=500,
        )


@app.post("/feedback")
def feedback(request: Request, analysis_id: int = Form(...), vote: str = Form(...), note: str = Form("")):
    session_id = ensure_session_id(request)
    current_user = get_current_user(request)
    user_id = current_user["id"] if current_user else None

    vote = vote.strip().lower()
    if vote not in {"up", "down"}:
        raise HTTPException(status_code=400, detail="Invalid vote")

    save_feedback(session_id=session_id, vote=vote, note=note, analysis_id=analysis_id, user_id=user_id)
    log_event(session_id, "feedback", {"analysis_id": analysis_id, "vote": vote}, user_id=user_id)
    return RedirectResponse(url="/", status_code=303)


@app.post("/api/analyze", response_model=dict)
def api_analyze(payload: AnalyzeRequest, request: Request):
    session_id = ensure_session_id(request)
    current_user = get_current_user(request)
    user_id = current_user["id"] if current_user else None

    result = run_analysis_pipeline(payload.url, session_id, user_id=user_id)
    return {
        "analysis_id": result["analysis_id"],
        "status": "done",
        "input_url": result["input_url"],
        "normalized_url": result["normalized_url"],
        "extraction_kind": result["extraction_kind"],
        "extracted_chars": result["extracted_chars"],
        "duration_ms": result["duration_ms"],
        "source": result["source"],
        "summary": result["summary"],
        "essay": result["essay"],
        "top_signal": result["top_signal"],
        "global_perspective": result["global_perspective"],
        "bias_scores": result["bias_scores"],
    }


@app.post("/api/jobs", response_model=JobCreateResponse)
def api_create_job(payload: AnalyzeRequest, request: Request, background_tasks: BackgroundTasks):
    session_id = ensure_session_id(request)
    current_user = get_current_user(request)
    user_id = current_user["id"] if current_user else None

    job_id = uuid.uuid4().hex
    create_job(job_id, session_id, payload.url, user_id=user_id)
    background_tasks.add_task(process_job, job_id, payload.url, session_id, user_id)
    log_event(session_id, "job_created", {"job_id": job_id}, user_id=user_id)
    return JobCreateResponse(job_id=job_id, status="queued")


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def api_job_status(job_id: str, request: Request):
    session_id = ensure_session_id(request)
    current_user = get_current_user(request)
    user_id = current_user["id"] if current_user else None

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if user_id is not None:
        if job.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Forbidden")
    else:
        if job["session_id"] != session_id:
            raise HTTPException(status_code=403, detail="Forbidden")

    return JobStatusResponse(job_id=job_id, status=job["status"], error=job.get("error"), result=job.get("result_json"))


@app.get("/api/history")
def api_history(request: Request):
    session_id = ensure_session_id(request)
    current_user = get_current_user(request)
    user_id = current_user["id"] if current_user else None
    return {"items": _history_for_context(session_id, user_id)}


@app.get("/api/metrics")
def api_metrics():
    return get_metrics()


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    return templates.TemplateResponse("about.html", {"request": request, "current_user": get_current_user(request)})


@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request, "current_user": get_current_user(request)})


@app.get("/terms", response_class=HTMLResponse)
def terms(request: Request):
    return templates.TemplateResponse("terms.html", {"request": request, "current_user": get_current_user(request)})


@app.get("/health")
def health():
    return JSONResponse({"status": "ok"})
