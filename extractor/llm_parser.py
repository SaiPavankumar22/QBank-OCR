"""
extractor/llm_parser.py
────────────────────────
LLM parser - handles cross-page continuations, text-based answers, all MCQ formats.
"""
import base64
import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import client, MODEL


SYSTEM_PROMPT = """You are an expert exam-paper parser.
Extract every question and every answer from the image you receive.

╔══════════════════════════════════════════════════════════════════╗
║  CRITICAL: CROSS-PAGE CONTINUATION — READ THIS CAREFULLY         ║
╚══════════════════════════════════════════════════════════════════╝

Pages do NOT always contain complete questions. You MUST handle all these cases:

CASE A — OPTIONS + ANSWER appear at TOP of page (belong to PREVIOUS page's last question)
  The page starts with option letters or an answer line BEFORE any question number.
  Example:
    "A. 140    B. 150    C. 160    D. 170
     Answer :C
     Q6. What is the next number..."
  → Extract those options+answer into "prev_page_continuation".
  → Then parse Q6 normally.

CASE B — Question starts on this page but OPTIONS are CUT OFF (will appear on next page)
  A question number and question text appear, but no options follow before the page ends.
  Example (bottom of page):
    "Q15.
     The salaries of A, B and C are in the ratio 1:3:4. If the salaries are
     increased by 5%, 10% and 15% respectively..."
     [page ends here]
  → Extract the question with options: {} and answer: null
  → Set "continuation_to_next": true on that question

CASE C — ONLY a question number at the very bottom, nothing else
  Example: "Q15." appears alone at the bottom.
  → Do NOT create a question record.
  → Put the number in "dangling_qno": 15

CASE D — ONLY "Answer :X" at the very top, no associated question visible on this page
  → Put it in "orphan_answers": [{"qno": null, "answer": "X"}]
  → If you can infer the qno from context, use it; otherwise null.

╔══════════════════════════════════════════════════════════════════╗
║  QUESTION TYPES                                                  ║
╚══════════════════════════════════════════════════════════════════╝

mcq        Standard A/B/C/D options, answer is one letter.
match      Match List-I with List-II. Has list1[], list2[], options{}.
statement  "Consider the following statements..." with A/B/C/D options.
text       DIRECT ANSWER question — NO A/B/C/D options at all.
           Answer is the actual value: "60%", "35:45:21", "9.1%", etc.
image      Question references a diagram/figure.
fill       Fill in the blank.

HOW TO DETECT text TYPE:
  - No A/B/C/D options visible after the question
  - Answer is a number, ratio, percentage, or text value (not a single letter)
  - Examples: "Answer :60%"  "Answer :35:45:21"  "Answer :9.1%"

╔══════════════════════════════════════════════════════════════════╗
║  PAGE KINDS                                                      ║
╚══════════════════════════════════════════════════════════════════╝

KIND 1 - INLINE (coaching PDFs): Question → options A/B/C/D → "Answer: X"  →  page_type="mixed"
KIND 2 - TEXT ANSWER: Question → "Answer: 60%"  (no options)  →  page_type="mixed", type="text"
KIND 3 - TWO-COLUMN EXAM: No inline answers  →  page_type="questions"
KIND 4 - ANSWER KEY TABLE  →  page_type="answers"

╔══════════════════════════════════════════════════════════════════╗
║  OUTPUT FORMAT — return ONLY valid JSON, NO markdown             ║
╚══════════════════════════════════════════════════════════════════╝

{
  "page_type": "mixed",

  "prev_page_continuation": {
    "options": {"A": "140", "B": "150", "C": "160", "D": "170"},
    "answer": "C"
  },

  "dangling_qno": null,

  "questions": [
    {
      "qno": 11,
      "type": "mcq",
      "question": "If P's salary is 25% more than Q's salary, then by what percent Q's salary less than P's salary?",
      "list1": [],
      "list2": [],
      "options": {"A": "30%", "B": "20%", "C": "50%", "D": "17%"},
      "answer": "B",
      "continuation_to_next": false
    },
    {
      "qno": 12,
      "type": "text",
      "question": "Doctor Khanna's salary is 37.5% less than Dr. Sunita salary, then Dr. Sunita's salary is how much % more than dr. Khanna's salary?",
      "list1": [],
      "list2": [],
      "options": {},
      "answer": "60%",
      "continuation_to_next": false
    },
    {
      "qno": 13,
      "type": "text",
      "question": "If a:b= 7:9 and b:c=15:7, then what is a:b:c",
      "list1": [],
      "list2": [],
      "options": {},
      "answer": "35:45:21",
      "continuation_to_next": false
    },
    {
      "qno": 15,
      "type": "mcq",
      "question": "The salaries of A, B and C are in the ratio 1:3:4. If the salaries are increased by 5%, 10% and 15% respectively, then the increased salaries will be in the ratio",
      "list1": [],
      "list2": [],
      "options": {},
      "answer": null,
      "continuation_to_next": true
    }
  ],

  "answers": [],

  "orphan_answers": [
    {"qno": null, "answer": "B"}
  ]
}

FIELD RULES
───────────
qno                   Parse "Q11.", "Q.11", "11.", "Q 11" → integer 11
type                  mcq | match | statement | text | image | fill
question              Full text including all sub-statements (i)(ii)(iii)
list1 / list2         Only for match; empty [] otherwise
options               UPPERCASE keys A/B/C/D. Empty {} for text/fill/cut-off questions.
answer                mcq/match/statement: uppercase letter or null.
                      text/fill: raw answer string e.g. "60%" or "35:45:21".
continuation_to_next  true if options/answer will appear on the NEXT page
prev_page_continuation  options+answer at TOP of page for PREVIOUS page's question (or null)
dangling_qno          integer if only a question number appears at bottom (no text), else null
orphan_answers        standalone answer lines with no question on this page

RULES
─────
1. Options at the very TOP before any question number = prev_page_continuation.
2. "Answer :X" alone at top with no question = orphan_answers (qno=null if unknown).
3. text type: answer field contains the actual value, NOT a letter.
4. Never invent A/B/C/D options for text-type questions.
5. If the last question has no options/answer at all, set continuation_to_next=true.
6. Ignore watermarks, logos, page numbers, headers, footers.
7. For checkbox options □A) □B) → map to keys A, B, C, D normally.
"""


def _encode(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"No JSON found:\n{text[:400]}")
    return json.loads(m.group(0))


def _empty() -> dict:
    return {
        "page_type": "questions",
        "prev_page_continuation": None,
        "dangling_qno": None,
        "questions": [],
        "answers": [],
        "orphan_answers": [],
    }


def _normalise(data: dict) -> dict:
    data.setdefault("page_type", "questions")
    data.setdefault("prev_page_continuation", None)
    data.setdefault("dangling_qno", None)
    data.setdefault("questions", [])
    data.setdefault("answers", [])
    data.setdefault("orphan_answers", [])

    for q in data["questions"]:
        q.setdefault("qno", 0)
        q.setdefault("type", "mcq")
        q.setdefault("question", "")
        q.setdefault("list1", [])
        q.setdefault("list2", [])
        q.setdefault("options", {})
        q.setdefault("answer", None)
        q.setdefault("continuation_to_next", False)

        q["options"] = {k.upper(): v for k, v in q["options"].items()}

        if q["answer"] is not None:
            if q["type"] in ("mcq", "match", "statement", "image"):
                q["answer"] = str(q["answer"]).strip().upper() or None
            else:
                q["answer"] = str(q["answer"]).strip() or None

    for rec in data.get("answers", []) + data.get("orphan_answers", []):
        if rec.get("answer"):
            ans = str(rec["answer"]).strip()
            # Only uppercase if it looks like a letter (A/B/C/D)
            if len(ans) == 1 and ans.isalpha():
                rec["answer"] = ans.upper()
            else:
                rec["answer"] = ans

    cont = data.get("prev_page_continuation")
    if cont and isinstance(cont, dict):
        cont["options"] = {k.upper(): v for k, v in cont.get("options", {}).items()}
        if cont.get("answer"):
            cont["answer"] = str(cont["answer"]).strip().upper()
    else:
        data["prev_page_continuation"] = None

    return data


_HINT = {
    "single": (
        "Single-column page. May have inline answers (KIND 1), text-based answers (KIND 2), "
        "or no answers (KIND 3). "
        "IMPORTANT: If options/answer appear at the very TOP before any question number, "
        "they are prev_page_continuation. "
        "If the last question has no options, set continuation_to_next=true. "
        "If only a question number appears at the very bottom, use dangling_qno."
    ),
    "two_column": (
        "ONE COLUMN of a two-column exam paper. No inline answers expected. "
        "Watch for cross-page continuations at top and bottom."
    ),
    "answer_key": (
        "Answer key table. Extract every Q.NO → ANS pair from ALL rows and columns."
    ),
}


def call_llm(image_path: str, layout_hint: str = "single") -> dict:
    b64 = _encode(image_path)
    hint = _HINT.get(layout_hint, _HINT["single"])

    try:
        response = client.chat.completions.create(
            model=MODEL,
            temperature=0,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"{hint}\n\n"
                                "Parse this exam page. "
                                "Return ONLY a single valid JSON object — no markdown, no preamble."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                    ],
                },
            ],
        )

        raw = response.choices[0].message.content
        print(f"\n  [LLM] raw (first 400 chars): {raw[:400]}")
        parsed = _extract_json(raw)
        return _normalise(parsed)

    except Exception as e:
        print(f"  [LLM] ERROR: {e}")
        return _empty()