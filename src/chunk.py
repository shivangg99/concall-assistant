"""Speaker-turn / Q&A-pair chunking, per PRD 8.2 (not fixed token windows)."""
import re

from .parse import find_qa_start, speaker_role, DISCONNECT_KEYWORDS, BOUNDARY_RE

# PRD 8.2 targets ~150-400 tokens/chunk (~600-1600 chars). A single speaker
# turn can run to a multi-thousand-word monologue (e.g. the CEO's full
# opening remarks with no interruption), so long turns/exchanges get
# re-split on sentence boundaries into this range rather than left as one
# oversized chunk - both for retrieval precision and to stay under
# embedding-provider per-request token limits.
MAX_CHUNK_CHARS = 1600
SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')


def _pack_sentences(text: str, max_chars: int):
    sentences = SENTENCE_SPLIT_RE.split(text)
    parts, current = [], ""
    for sent in sentences:
        if current and len(current) + 1 + len(sent) > max_chars:
            parts.append(current)
            current = sent
        else:
            current = f"{current} {sent}".strip()
    if current:
        parts.append(current)
    return parts


def _emit(chunks: list, base: dict):
    """Append `base` to chunks, splitting base['text'] into multiple
    sub-chunks (sharing all other metadata) if it exceeds MAX_CHUNK_CHARS."""
    text = base["text"]
    if len(text) <= MAX_CHUNK_CHARS:
        chunks.append(base)
        return
    parts = _pack_sentences(text, MAX_CHUNK_CHARS)
    for k, part in enumerate(parts):
        sub = dict(base)
        sub["chunk_id"] = f"{base['chunk_id']}_{k}"
        sub["text"] = part
        chunks.append(sub)


def _is_operator_noise(speaker: str, content: str) -> bool:
    low = content.lower()
    return speaker.lower() == "moderator" and any(kw in low for kw in DISCONNECT_KEYWORDS)


def chunk_turns(turns, ticker, quarter, fiscal_year, call_date, management_names, company_name=""):
    qa_start = find_qa_start(turns)
    chunks = []

    for i in range(qa_start):
        speaker, content = turns[i]
        if len(content) < 20 or _is_operator_noise(speaker, content):
            continue
        _emit(chunks, {
            "chunk_id": f"{ticker}_{quarter}_PR{i:03d}",
            "ticker": ticker, "company_name": company_name, "quarter": quarter, "fiscal_year": fiscal_year,
            "call_date": call_date, "speaker": speaker,
            "speaker_role": speaker_role(speaker, management_names),
            "section": "Prepared Remarks", "text": content,
        })

    segments, segment = [], []
    for i in range(qa_start, len(turns)):
        speaker, content = turns[i]
        if speaker.lower() == "moderator" and BOUNDARY_RE.search(content):
            if segment:
                segments.append(segment)
            segment = []
            continue
        if _is_operator_noise(speaker, content) or len(content) < 5:
            continue
        segment.append((speaker, content))
    if segment:
        segments.append(segment)

    for j, seg in enumerate(segments):
        asker = next((s for s, _ in seg if s.lower() != "moderator"), "Unknown")
        merged_text = "\n".join(f"{s}: {c}" for s, c in seg)
        if len(merged_text) < 20:
            continue
        _emit(chunks, {
            "chunk_id": f"{ticker}_{quarter}_QA{j:03d}",
            "ticker": ticker, "company_name": company_name, "quarter": quarter, "fiscal_year": fiscal_year,
            "call_date": call_date, "speaker": asker,
            "speaker_role": speaker_role(asker, management_names),
            "section": "Q&A", "text": merged_text,
        })

    return chunks
