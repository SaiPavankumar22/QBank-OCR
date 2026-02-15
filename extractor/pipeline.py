"""
extractor/pipeline.py
──────────────────────
Main pipeline: PDF → images → LLM → merge → clean.
"""
from extractor.pdf_engine     import pdf_to_images
from extractor.diagram_engine import extract_diagrams
from extractor.llm_parser     import call_llm
from extractor.merger         import merge_sections, validate_and_clean_questions

SEP = "─" * 55


def _attach_diagrams(questions: list, diagrams: list) -> None:
    need = [q for q in questions if not q.get("diagram")]
    for i, q in enumerate(need):
        q["diagram"] = diagrams[i]["path"] if i < len(diagrams) else None
    for q in questions:
        q.setdefault("diagram", None)


def process_pdf(pdf_path: str) -> dict:
    print(f"\n{'═'*55}")
    print(f"  PDF: {pdf_path}")
    print(f"{'═'*55}")

    pages = pdf_to_images(pdf_path, dpi=200)
    print(f"\n✓ {len(pages)} page-section(s) rendered:")
    for p in pages:
        print(f"   [{p['index']:>6}]  layout = {p['layout']}")

    sections = []

    for p in pages:
        idx    = p["index"]
        img    = p["image_path"]
        pg_no  = p["page_no"]
        clip   = p["clip"]
        layout = p["layout"]

        print(f"\n{SEP}")
        print(f"  Section {idx}   (layout={layout})")
        print(SEP)

        diagrams = extract_diagrams(pdf_path, idx, pg_no, clip)
        if diagrams:
            print(f"  ✓ {len(diagrams)} diagram(s) found")

        data  = call_llm(img, layout_hint=layout)
        n_q   = len(data.get("questions", []))
        n_a   = len(data.get("answers", []))
        n_o   = len(data.get("orphan_answers", []))
        n_c   = sum(1 for q in data.get("questions", []) if q.get("continuation_to_next"))
        has_ppc = data.get("prev_page_continuation") is not None
        dq    = data.get("dangling_qno")

        print(f"  ✓ questions={n_q}  answers={n_a}  orphans={n_o}")
        if n_c:   print(f"  ⚠ {n_c} question(s) continue to next page")
        if has_ppc: print(f"  ✓ prev_page_continuation found")
        if dq:    print(f"  ⚠ dangling_qno={dq}")

        if diagrams and data.get("questions"):
            _attach_diagrams(data["questions"], diagrams)

        sections.append(data)

    print(f"\n{SEP}")
    print("  Merging & cleaning …")
    print(SEP)

    result = merge_sections(sections)
    result = validate_and_clean_questions(result)

    total    = len(result["questions"])
    answered = sum(1 for q in result["questions"] if q.get("answer"))
    diag     = sum(1 for q in result["questions"] if q.get("diagram"))
    text_qs  = sum(1 for q in result["questions"] if q.get("type") == "text")

    print(f"\n  ✓ total={total}  answered={answered}  diagrams={diag}  text_type={text_qs}")
    print(f"{'═'*55}\n")

    return result