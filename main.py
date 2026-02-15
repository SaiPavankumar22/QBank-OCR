"""
main.py — MCQ Extractor API
"""
import os
import uuid

from fastapi import FastAPI, UploadFile, File, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any

from extractor.pipeline import process_pdf
from db.mongo import (
    save_questions,
    get_all_questions,
    get_question_by_qno,
    clear_questions,
    save_upload_metadata,
    get_all_uploads,
)

for d in ("temp", "temp/page_images", "temp/diagrams", "static", "templates"):
    os.makedirs(d, exist_ok=True)

app = FastAPI(title="MCQ Extractor API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """
    Upload and process PDF.
    Returns extracted questions WITHOUT saving to DB yet.
    The user reviews/edits in the frontend, then calls /save.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    try:
        contents  = await file.read()
        temp_path = f"temp/input_{uuid.uuid4().hex[:8]}.pdf"
        with open(temp_path, "wb") as f:
            f.write(contents)

        result = process_pdf(temp_path)

        metadata = {
            "filename":                file.filename,
            "total_questions":         len(result["questions"]),
            "questions_with_answers":  sum(1 for q in result["questions"] if q.get("answer")),
            "questions_with_diagrams": sum(1 for q in result["questions"] if q.get("diagram")),
            "text_type_questions":     sum(1 for q in result["questions"] if q.get("type") == "text"),
        }

        result["metadata"] = metadata

        try:
            os.remove(temp_path)
        except OSError:
            pass

        return JSONResponse(content=result)

    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class SaveRequest(BaseModel):
    filename: str
    questions: list[dict[str, Any]]


@app.post("/save")
async def save_to_db(body: SaveRequest):
    """
    Save the (possibly user-edited) questions to MongoDB.
    Called after the user reviews and edits the extracted content.
    """
    result = {"questions": body.questions}

    metadata = {
        "total_questions":         len(body.questions),
        "questions_with_answers":  sum(1 for q in body.questions if q.get("answer")),
        "questions_with_diagrams": sum(1 for q in body.questions if q.get("diagram")),
    }

    upload_id   = save_upload_metadata(body.filename, metadata)
    saved_count = save_questions(result, upload_id=upload_id)

    return JSONResponse(content={
        "upload_id":   upload_id,
        "saved":       saved_count,
        "message":     f"Saved {saved_count} questions successfully.",
    })


@app.get("/questions")
async def list_questions(upload_id: str = Query(default=None)):
    questions = get_all_questions(upload_id=upload_id)
    return JSONResponse(content={"questions": questions, "total": len(questions)})


@app.get("/questions/{qno}")
async def get_question(qno: int, upload_id: str = Query(default=None)):
    question = get_question_by_qno(qno, upload_id=upload_id)
    if question:
        return JSONResponse(content=question)
    raise HTTPException(status_code=404, detail=f"Question {qno} not found.")


@app.delete("/questions")
async def delete_questions(upload_id: str = Query(default=None)):
    deleted = clear_questions(upload_id=upload_id)
    return JSONResponse(content={"deleted": deleted})


@app.get("/uploads")
async def list_uploads():
    uploads = get_all_uploads()
    return JSONResponse(content={"uploads": uploads, "total": len(uploads)})


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    from config import APP_HOST, APP_PORT
    uvicorn.run("main:app", host=APP_HOST, port=APP_PORT, reload=True)