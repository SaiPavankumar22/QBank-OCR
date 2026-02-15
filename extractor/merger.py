"""
extractor/merger.py
────────────────────
Merges all page sections handling:
- Cross-page question continuations (options on next page)
- Dangling question numbers (question text on next page)
- Text-based answers (no options)
- Separate answer key pages
- Orphan answers
"""


def _build_answer_map(sections: list) -> dict:
    """
    Build {qno: answer} from ALL sections.
    Priority: answer_key page > inline > orphan.
    """
    answer_map: dict = {}

    for sec in sections:
        for q in sec.get("questions", []):
            qno = q.get("qno")
            ans = q.get("answer")
            if qno and ans:
                answer_map[qno] = ans

        for rec in sec.get("answers", []):
            qno = rec.get("qno")
            ans = rec.get("answer")
            if qno and ans:
                answer_map[qno] = ans

        for rec in sec.get("orphan_answers", []):
            qno = rec.get("qno")
            ans = rec.get("answer")
            if qno and ans:
                answer_map[qno] = ans

    # Answer key pages override everything
    for sec in sections:
        if sec.get("page_type") == "answers":
            for rec in sec.get("answers", []):
                qno = rec.get("qno")
                ans = rec.get("answer")
                if qno and ans:
                    answer_map[qno] = ans

    return answer_map


def _score(q: dict) -> int:
    return (
        len(q.get("question", "")) * 1
        + len(q.get("options", {})) * 10
        + len(q.get("list1", [])) * 5
        + len(q.get("list2", [])) * 5
        + (3 if q.get("answer") else 0)
    )


def merge_sections(sections: list) -> dict:
    """
    Merge all page sections into one question list.
    Handles cross-page continuations via prev_page_continuation and continuation_to_next.
    """
    answer_map = _build_answer_map(sections)

    # ── Pass 1: resolve cross-page continuations ──────────────────────────────
    # Track the last question that had continuation_to_next=True
    pending_continuation_qno = None   # qno of question waiting for its options
    pending_dangling_qno = None        # qno of a dangling question number

    by_qno: dict = {}

    for i, sec in enumerate(sections):
        if sec.get("page_type") == "answers":
            # Pure answer key — no questions
            pending_continuation_qno = None
            pending_dangling_qno = None
            continue

        cont = sec.get("prev_page_continuation")

        # ── Apply continuation from previous page ─────────────────────────────
        if cont and pending_continuation_qno is not None:
            qno = pending_continuation_qno
            if qno in by_qno:
                q = by_qno[qno]
                # Fill in missing options and answer
                if cont.get("options") and not q.get("options"):
                    q["options"] = cont["options"]
                if cont.get("answer") and not q.get("answer"):
                    q["answer"] = cont["answer"]
            pending_continuation_qno = None

        # ── Apply dangling qno: next page starts with options for that number ─
        if pending_dangling_qno is not None and cont:
            qno = pending_dangling_qno
            # The continuation IS the whole question content
            if qno not in by_qno:
                by_qno[qno] = {
                    "qno": qno,
                    "type": "mcq",
                    "question": "",
                    "list1": [],
                    "list2": [],
                    "options": cont.get("options", {}),
                    "answer": cont.get("answer"),
                    "continuation_to_next": False,
                    "diagram": None,
                }
            pending_dangling_qno = None

        # ── Also handle orphan answers without qno ────────────────────────────
        # Try to figure out which question they belong to by looking at
        # the last processed qno before this page
        orphans_no_qno = [r for r in sec.get("orphan_answers", []) if not r.get("qno")]
        if orphans_no_qno and by_qno:
            last_qno = max(by_qno.keys())
            for r in orphans_no_qno:
                if not by_qno[last_qno].get("answer"):
                    by_qno[last_qno]["answer"] = r["answer"]

        # ── Collect questions from this section ───────────────────────────────
        for q in sec.get("questions", []):
            qno = q.get("qno")
            if not qno:
                continue

            if qno not in by_qno or _score(q) > _score(by_qno[qno]):
                by_qno[qno] = q

            if q.get("continuation_to_next"):
                pending_continuation_qno = qno

        # ── Check for dangling qno at bottom of this page ────────────────────
        dq = sec.get("dangling_qno")
        if dq:
            pending_dangling_qno = int(dq)

    # ── Pass 2: attach final answers ──────────────────────────────────────────
    for qno, q in by_qno.items():
        if answer_map.get(qno) and not q.get("answer"):
            q["answer"] = answer_map[qno]
        elif answer_map.get(qno):
            # answer_key page overrides inline (already highest priority in answer_map)
            pass

    questions = sorted(by_qno.values(), key=lambda x: x.get("qno", 0))
    return {"questions": questions}


def validate_and_clean_questions(result: dict) -> dict:
    cleaned = []
    for q in result.get("questions", []):
        if not q.get("qno"):
            continue
        if not q.get("question") and not q.get("options"):
            continue

        cleaned.append({
            "qno":                  q["qno"],
            "type":                 q.get("type", "mcq"),
            "question":             (q.get("question") or "").strip(),
            "list1":                q.get("list1", []),
            "list2":                q.get("list2", []),
            "options":              q.get("options", {}),
            "diagram":              q.get("diagram"),
            "answer":               q.get("answer"),
            "continuation_to_next": q.get("continuation_to_next", False),
        })

    return {"questions": cleaned}