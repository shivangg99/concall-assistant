"""
Phase 1 ingestion pipeline (prototype).
Parses transcript .txt (already extracted from PDF via pdftotext -layout),
splits into speaker-turn chunks, tags metadata, and writes a JSON chunk store.

NOTE ON EMBEDDINGS: this sandbox has no network access to embedding providers
(Voyage/OpenAI etc - only pypi/npm/github domains are reachable). For this live
prototype we use TF-IDF vectors (scikit-learn) as a stand-in for semantic
embeddings so the retrieval step is fully runnable end-to-end. In production
(per the PRD) this would be swapped for real embeddings with no change to the
chunking/metadata/retrieval interface.
"""
import re
import json
import sys

SPEAKER_RE = re.compile(r'^([A-Z][A-Za-z\.\'\-\s]{2,40}):\s+(.*)$')

MODERATOR_NAMES = {"moderator"}

def clean_text(raw: str) -> str:
    # drop form-feed page breaks and footer/header noise
    lines = raw.split("\n")
    out = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("\x0c"):
            s = s.lstrip("\x0c").strip()
        if re.match(r'^Page \d+ of \d+$', s):
            continue
        if s in ("Jindal Saw Limited", "Jindal SAW Limited"):
            continue
        if re.match(r'^(July|October|January|April) \d{1,2}, 20\d\d$', s):
            continue
        out.append(s)
    return "\n".join(out)

def parse_speaker_turns(text: str):
    """Merge wrapped lines back into one line per speaker turn, then split."""
    lines = text.split("\n")
    turns = []
    current_speaker = None
    current_text = []

    for ln in lines:
        m = SPEAKER_RE.match(ln)
        if m and len(m.group(1).split()) <= 6:  # avoid false positives on prose with colons
            if current_speaker:
                turns.append((current_speaker, " ".join(current_text).strip()))
            current_speaker = m.group(1).strip()
            current_text = [m.group(2).strip()]
        else:
            if current_speaker:
                current_text.append(ln.strip())
    if current_speaker:
        turns.append((current_speaker, " ".join(current_text).strip()))
    return turns

def tag_section(speaker: str, idx: int, qa_start_idx: int) -> str:
    return "Q&A" if idx >= qa_start_idx else "Prepared Remarks"

def find_qa_start(turns):
    for i, (spk, txt) in enumerate(turns):
        if spk.lower() == "moderator" and "question-and-answer" in txt.lower():
            return i
    return len(turns)

def chunk_transcript(path: str, ticker: str, quarter: str, fiscal_year: str, call_date: str):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        raw = f.read()
    text = clean_text(raw)
    turns = parse_speaker_turns(text)
    qa_start = find_qa_start(turns)

    chunks = []

    # --- Prepared remarks: keep as single-speaker turns (management monologue) ---
    for i in range(qa_start):
        speaker, content = turns[i]
        if len(content) < 20:
            continue
        low = content.lower()
        if speaker.lower() == "moderator" and any(
            kw in low for kw in ["disconnect", "reconnect", "stay connected", "rejoin"]
        ):
            continue
        chunks.append({
            "chunk_id": f"{ticker}_{quarter}_{i:03d}",
            "ticker": ticker, "quarter": quarter, "fiscal_year": fiscal_year,
            "call_date": call_date, "speaker": speaker,
            "section": "Prepared Remarks", "text": content,
        })

    # --- Q&A: merge each full exchange (question + full management answer,
    # including any cross-talk) into ONE chunk, bounded by moderator's
    # "next question" transitions. This preserves the Q<->A context that
    # single-turn chunking would otherwise split apart. ---
    boundary_re = re.compile(r'next question|last question|first question', re.I)
    segment = []
    segments = []
    for i in range(qa_start, len(turns)):
        speaker, content = turns[i]
        if speaker.lower() == "moderator" and boundary_re.search(content):
            if segment:
                segments.append(segment)
            segment = []
            continue
        low = content.lower()
        if speaker.lower() == "moderator" and any(
            kw in low for kw in ["disconnect", "reconnect", "stay connected", "rejoin"]
        ):
            continue
        if len(content) < 5:
            continue
        segment.append((speaker, content))
    if segment:
        segments.append(segment)

    for j, seg in enumerate(segments):
        asker = next((s for s, _ in seg if s.lower() not in ("moderator",)), "Unknown")
        merged_text = "\n".join(f"{s}: {c}" for s, c in seg)
        if len(merged_text) < 20:
            continue
        chunks.append({
            "chunk_id": f"{ticker}_{quarter}_QA{j:03d}",
            "ticker": ticker, "quarter": quarter, "fiscal_year": fiscal_year,
            "call_date": call_date, "speaker": asker,
            "section": "Q&A", "text": merged_text,
        })

    return chunks

if __name__ == "__main__":
    all_chunks = []
    all_chunks += chunk_transcript("jindal_q1fy27.txt", "JINDALSAW", "Q1FY27", "FY27", "2026-07-15")
    all_chunks += chunk_transcript("jindal_q2fy26.txt", "JINDALSAW", "Q2FY26", "FY26", "2025-10-23")

    with open("chunks.json", "w") as f:
        json.dump(all_chunks, f, indent=2)

    print(f"Total chunks: {len(all_chunks)}")
    by_q = {}
    for c in all_chunks:
        by_q.setdefault(c["quarter"], 0)
        by_q[c["quarter"]] += 1
    print("By quarter:", by_q)
    print("\nSample chunk:")
    print(json.dumps(all_chunks[5], indent=2))
