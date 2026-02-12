from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from app.scraper import extract_article_text, detect_source
from app.bias_model import full_bias_analysis

app = FastAPI()

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
templates = Jinja2Templates(directory="frontend/templates")


def to_percent(value):
    try:
        v = float(value) * 100
        return max(0, min(round(v, 1), 100))
    except Exception:
        return 0.0


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )


@app.post("/analyze", response_class=HTMLResponse)
def analyze(request: Request, url: str = Form(...)):
    try:
        article_text = extract_article_text(url)
        source = detect_source(url)

        analysis = full_bias_analysis(article_text, source)
        scores = analysis["bias_scores"]

        # 🔒 PRE-COMPUTED, SAFE VALUES
        percent_scores = {
            "Left": to_percent(scores.get("Left")),
            "Center": to_percent(scores.get("Center")),
            "Right": to_percent(scores.get("Right")),
        }

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "summary": analysis["summary"],
                "essay": analysis["essay"],
                "top_signal": analysis["top_signal"],

                # Send ONLY safe values to frontend
                "left_pct": percent_scores["Left"],
                "center_pct": percent_scores["Center"],
                "right_pct": percent_scores["Right"],
            }
        )

    except Exception as e:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "error": str(e)
            }
        )
