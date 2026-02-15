"""
db/mongo.py
───────────
MongoDB persistence layer.

Collections
───────────
  questions  – one document per MCQ question
  uploads    – metadata about each processed PDF
"""
import os
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import MongoClient, ASCENDING
from pymongo.errors import ConnectionFailure, DuplicateKeyError

# Import config; fall back gracefully if run standalone
try:
    from config import MONGO_URI, DB_NAME
except ImportError:
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    DB_NAME   = os.getenv("DB_NAME",   "examdb")


# ── Connection ────────────────────────────────────────────────────────────────
_client = None
_db     = None


def _get_db():
    """Return (and lazily create) the MongoDB database handle."""
    global _client, _db
    if _db is None:
        try:
            _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            # Ping to confirm connection
            _client.admin.command("ping")
            _db = _client[DB_NAME]
            # Ensure indexes
            _db.questions.create_index([("qno", ASCENDING)], unique=False)
            _db.questions.create_index([("upload_id", ASCENDING)])
            _db.uploads.create_index([("created_at", ASCENDING)])
            print(f"[db] Connected to MongoDB → {DB_NAME}")
        except ConnectionFailure as e:
            print(f"[db] WARNING: MongoDB not reachable ({e}). Running without persistence.")
            _db = None
    return _db


# ── Questions ─────────────────────────────────────────────────────────────────

def save_questions(result: dict, upload_id: str = None) -> int:
    """
    Save extracted questions to MongoDB.

    Parameters
    ----------
    result      : dict with key "questions" (list of question dicts)
    upload_id   : optional string to tag questions with their source upload

    Returns
    -------
    Number of documents inserted (0 if DB unavailable).
    """
    db = _get_db()
    if db is None:
        return 0

    questions = result.get("questions", [])
    if not questions:
        return 0

    docs = []
    now  = datetime.now(timezone.utc)

    for q in questions:
        doc = {
            "qno":       q.get("qno"),
            "type":      q.get("type", "mcq"),
            "question":  q.get("question", ""),
            "list1":     q.get("list1", []),
            "list2":     q.get("list2", []),
            "options":   q.get("options", {}),
            "answer":    q.get("answer"),
            "diagram":   q.get("diagram"),
            "upload_id": upload_id,
            "created_at": now,
        }
        docs.append(doc)

    try:
        res = db.questions.insert_many(docs, ordered=False)
        return len(res.inserted_ids)
    except Exception as e:
        print(f"[db] insert_many error: {e}")
        return 0


def _to_json_serializable(obj):
    """Convert datetime and ObjectId to JSON-serializable types."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _to_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_json_serializable(v) for v in obj]
    return obj


def get_all_questions(upload_id: str = None) -> list:
    """
    Retrieve all questions.
    Optionally filter by upload_id.
    Returns JSON-serialisable list (ObjectId → str, datetime → ISO str).
    """
    db = _get_db()
    if db is None:
        return []

    query = {}
    if upload_id:
        query["upload_id"] = upload_id

    cursor = db.questions.find(query, {"_id": 0}).sort("qno", ASCENDING)
    return _to_json_serializable(list(cursor))


def get_question_by_qno(qno: int, upload_id: str = None) -> dict | None:
    """Return a single question by its number (optionally scoped to upload)."""
    db = _get_db()
    if db is None:
        return None

    query = {"qno": qno}
    if upload_id:
        query["upload_id"] = upload_id

    doc = db.questions.find_one(query, {"_id": 0})
    return _to_json_serializable(doc) if doc else None


def clear_questions(upload_id: str = None) -> int:
    """
    Delete questions from DB.
    If upload_id given, delete only that upload's questions.
    Otherwise delete ALL questions.
    """
    db = _get_db()
    if db is None:
        return 0

    query = {"upload_id": upload_id} if upload_id else {}
    res   = db.questions.delete_many(query)
    return res.deleted_count


# ── Uploads ───────────────────────────────────────────────────────────────────

def save_upload_metadata(filename: str, metadata: dict) -> str:
    """
    Save upload metadata and return the generated upload_id (str).
    """
    db = _get_db()
    if db is None:
        return "no-db"

    doc = {
        "filename":    filename,
        "created_at":  datetime.now(timezone.utc),
        "total":       metadata.get("total_questions", 0),
        "with_answers": metadata.get("questions_with_answers", 0),
        "with_diagrams": metadata.get("questions_with_diagrams", 0),
    }
    res = db.uploads.insert_one(doc)
    return str(res.inserted_id)


def get_all_uploads() -> list:
    """Return all upload records (most recent first)."""
    db = _get_db()
    if db is None:
        return []

    cursor = db.uploads.find({}, {"_id": 1, "filename": 1, "created_at": 1,
                                   "total": 1, "with_answers": 1})
    results = []
    for doc in cursor.sort("created_at", -1):
        doc["_id"] = str(doc["_id"])
        results.append(_to_json_serializable(doc))
    return results
