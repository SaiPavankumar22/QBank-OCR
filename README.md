# MCQ Extractor

Extract MCQ questions and answers from **any** exam PDF automatically using AI vision.

Supports:
- Coaching institute PDFs (inline Q + Answer style)
- UPSC / SSC / RRB / State PSC two-column papers
- Scanned books and handwritten-option PDFs
- PDFs with a separate answer key page

---

## Table of Contents

- [System Architecture](#system-architecture)
- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [Question Schema](#question-schema)
- [Setup](#setup)
- [Running](#running)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [PDF Types Handled](#pdf-types-handled)
- [Troubleshooting](#troubleshooting)

---

## System Architecture

The system has four main layers:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           WEB LAYER (FastAPI)                               │
│  main.py — REST API, file upload, CORS, static serving                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        EXTRACTION PIPELINE                                  │
│  pipeline.py — orchestrates: PDF → images → LLM → diagrams → merge → clean  │
└─────────────────────────────────────────────────────────────────────────────┘
          │                │                │                │
          ▼                ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  pdf_engine  │  │  llm_parser  │  │ diagram_     │  │    merger    │
│  • Layout    │  │  • Vision    │  │  engine      │  │ • Cross-page │
│    detect    │  │  • JSON out  │  │ • Extract    │  │   continuations│
│  • Page→IMG  │  │  • Normalize │  │   figures    │  │ • Answer key │
│  • Split     │  │              │  │              │  │   resolution │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PERSISTENCE LAYER                                    │
│  db/mongo.py — MongoDB: questions collection, uploads metadata              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## How It Works

### 1. PDF Upload & Routing

1. User uploads a PDF via the web UI or `POST /upload`.
2. File is saved temporarily under `temp/input_<uuid>.pdf`.
3. `process_pdf()` is invoked with the path.

### 2. PDF Engine (`extractor/pdf_engine.py`)

**Layout detection per page:**

- **`single`** — Single-column or inline-answer style (coaching PDFs, books). Full page rendered as one image.
- **`two_column`** — Classic two-column exam paper. Page is split into left half (`page_N_L.png`) and right half (`page_N_R.png`), each sent separately to the LLM.
- **`answer_key`** — Detected when page text contains signals like "answer key", "ans key", "q. no.", "provisional answer". Treated as a Q.NO → ANS lookup table.

**Heuristics:**
- Answer key: 2+ signal phrases in page text.
- Two-column: Text blocks distributed on both sides of midline (≥3 blocks each side, balanced ratio).
- Default: Single column.

**Output:** List of dicts with `index`, `image_path`, `page_no`, `clip`, `layout`.

### 3. LLM Parser (`extractor/llm_parser.py`)

Each page image is sent to a vision-capable LLM (Nebius / OpenAI-compatible). The model:

1. Receives a system prompt defining output format and edge cases.
2. Receives a layout hint (`single`, `two_column`, `answer_key`).
3. Returns structured JSON with:
   - `questions` — list of question objects
   - `answers` — Q.NO → ANS pairs (from answer key pages)
   - `prev_page_continuation` — options/answer at top belonging to previous page’s last question
   - `dangling_qno` — question number alone at bottom (text on next page)
   - `orphan_answers` — standalone answer lines with no question visible
   - `continuation_to_next` — question text on this page, options on next page

**Question types:** `mcq`, `match`, `statement`, `text`, `image`, `fill`.

**Special handling:**
- Cross-page continuations: options/answer at top of page → previous question.
- Cut-off questions: last question with no options → `continuation_to_next: true`.
- Text-type: No A/B/C/D options; answer is raw value (e.g. `"60%"`, `"35:45:21"`).
- Match-type: `list1`, `list2` arrays for List-I / List-II.

### 4. Diagram Engine (`extractor/diagram_engine.py`)

- Uses PyMuPDF to find image blocks in each page/clip region.
- Filters by size (≥80×80 px), aspect ratio, and position (skips header/footer bands).
- Skips nearly blank images (low variance).
- Saves diagrams to `temp/diagrams/` and attaches them to questions without diagrams in order.

### 5. Merger (`extractor/merger.py`)

**Answer resolution priority:** answer_key page > inline answers > orphan answers.

**Cross-page logic:**
1. **`prev_page_continuation`** — Options/answer at top of page N fill the last question from page N-1 that had `continuation_to_next`.
2. **`dangling_qno`** — If page N ends with only "Q15.", and page N+1 starts with options + answer, a new question Q15 is created.
3. **`orphan_answers`** — Standalone answer lines without qno are assigned to the most recent question missing an answer.
4. **`continuation_to_next`** — Question on page N, options on page N+1: merger links them via `prev_page_continuation`.

**`validate_and_clean_questions()`** — Drops incomplete questions (no qno, no question text, no options).

### 6. Persistence (`db/mongo.py`)

**Collections:**
- **`questions`** — One document per MCQ. Fields: `qno`, `type`, `question`, `list1`, `list2`, `options`, `answer`, `diagram`, `upload_id`, `created_at`.
- **`uploads`** — Metadata per processed PDF: `filename`, `created_at`, `total`, `with_answers`, `with_diagrams`.

**JSON serialization:** MongoDB `datetime` and `ObjectId` are converted to ISO strings and strings via `_to_json_serializable()` before API responses.

### 7. Web Flow

1. **Upload** → `POST /upload` → extract → return questions (no save).
2. **Review** → User edits questions in the UI (search, filter, expand, edit).
3. **Save** → `POST /save` → persist to MongoDB with new `upload_id`.
4. **View DB** → `GET /questions` → load from MongoDB for review or export.

---

## Project Structure

```
Question Bank Extractor/
├── main.py                   ← FastAPI app (all API routes)
├── config.py                 ← API keys, model, DB config
├── requirements.txt
├── .env.example              ← copy to .env and fill in secrets
├── test_pipeline.py          ← standalone test (no server needed)
│
├── extractor/
│   ├── __init__.py
│   ├── pdf_engine.py        ← PDF → images, layout detection
│   ├── llm_parser.py        ← image → structured JSON via LLM vision
│   ├── diagram_engine.py    ← extract diagrams from pages
│   ├── merger.py            ← combine all pages, fill answers, cross-page logic
│   └── pipeline.py          ← orchestrates the above
│
├── db/
│   └── mongo.py             ← MongoDB CRUD, JSON serialization
│
├── templates/
│   └── index.html           ← Web UI (upload, review, edit, save)
│
├── static/                  ← CSS/JS assets (if any)
└── temp/                    ← auto-created at runtime
    ├── page_images/         ← rendered page PNGs
    └── diagrams/            ← extracted diagram images
```

---

## Question Schema

Each question object has:

| Field | Type | Description |
|-------|------|-------------|
| `qno` | int | Question number (Q1, Q2, …) |
| `type` | str | `mcq` \| `match` \| `statement` \| `text` \| `image` \| `fill` |
| `question` | str | Full question text |
| `list1` | list | List-I items (match type only) |
| `list2` | list | List-II items (match type only) |
| `options` | dict | `{"A": "...", "B": "...", "C": "...", "D": "..."}` |
| `answer` | str \| null | Letter (A/B/C/D) for mcq; raw value for text/fill |
| `diagram` | str \| null | Path to extracted diagram image |
| `continuation_to_next` | bool | Internal; true if options on next page |

---

## Setup

### 1. Clone or copy the project

```bash
cd "Question Bank Extractor"
```

### 2. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # Linux / Mac
venv\Scripts\activate           # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in:
#   NEBIUS_KEY   → your Nebius AI API key
#   MONGO_URI    → your MongoDB connection string (optional)
```

**Get a free Nebius API key:** https://studio.nebius.com  

**MongoDB:** Install locally or use [MongoDB Atlas](https://www.mongodb.com/atlas) (free tier). The app runs without MongoDB — questions are returned from the API but not persisted.

---

## Running

### Option A — Web server

```bash
python main.py
# OR
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 in your browser.

### Option B — Standalone test (no server)

```bash
python test_pipeline.py path/to/your.pdf
```

Runs the full extraction pipeline, prints results to the terminal, and saves `test_output.json`.

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Web UI (HTML) |
| POST | `/upload` | Upload PDF → extract questions (returns JSON, does not save) |
| POST | `/save` | Save questions to MongoDB (body: `{filename, questions}`) |
| GET | `/questions` | List all questions. Query: `?upload_id=` to filter by upload |
| GET | `/questions/{qno}` | Get question by number. Query: `?upload_id=` to scope |
| DELETE | `/questions` | Clear questions. Query: `?upload_id=` to delete one upload only |
| GET | `/uploads` | List all processed uploads (metadata) |
| GET | `/health` | Health check |

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `NEBIUS_KEY` | (required) | Nebius AI API key |
| `MODEL` | `google/gemma-3-27b-it` | Vision model for parsing |
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `DB_NAME` | `examdb` | MongoDB database name |
| `APP_HOST` | `0.0.0.0` | Server bind host |
| `APP_PORT` | `8000` | Server port |

---

## PDF Types Handled

| PDF Type | Layout Detection | Answer Source |
|----------|-----------------|---------------|
| Coaching PDFs (CodeBashers, etc.) | `single` | Inline after each question |
| UPSC / PSC two-column papers | `two_column` | Separate answer key page |
| SSC / RRB single-column papers | `single` | Inline or separate |
| Answer key only page | `answer_key` | Parsed from table |
| Scanned books | `single` | Inline |

---

## Troubleshooting

**`NEBIUS_KEY` not set** → Copy `.env.example` to `.env` and add your key.

**MongoDB not running** → The app continues without DB; questions appear in the API response but are not persisted.

**`TypeError: Object of type datetime is not JSON serializable`** → Ensure `db/mongo.py` uses `_to_json_serializable()` for all DB responses. This is already implemented.

**LLM returns empty or wrong answers** → Try a higher-quality model. In `config.py` or `.env`, set `MODEL` to e.g. `meta-llama/Meta-Llama-3.1-70B-Instruct` or `mistralai/Mixtral-8x7B-Instruct-v0.1`.

**Pages not splitting correctly** → Layout detection is heuristic. For unusual PDFs, the LLM often still parses content correctly even if layout detection is off.
