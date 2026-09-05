"""
PDF -> cleaned speaker turns.

Handles the SEBI Regulation-30 transcript format used for Indian-listed
companies (cover letter page + management/moderator title page + dialogue).
Designed to work unmodified for any ticker that follows this same filing
format, not just JINDALSAW - drop a new ticker's PDFs in
cocnall-scripts/<TICKER>/ and it parses the same way.
"""
import re
import pdfplumber

# Between "Q<digit>" and "FY<year>" some companies insert extra text, e.g.
# "Q3 & 9M FY23" (a cumulative-nine-months figure tacked on) - the .{0,20}?
# gap tolerates that (and the plain "Q2FY26" / "Q4 FY'24" cases) without
# spanning far enough to risk matching an unrelated quarter mention.
QUARTER_RE = re.compile(r"Q(\d).{0,20}?FY\s*['’\-]?\s*(\d{2,4})", re.I)
DATE_RE = re.compile(r'([A-Z][a-z]+ \d{1,2},\s*20\d\d)')
SPEAKER_RE = re.compile(r"^([A-Z][A-Za-z\.\'\-\s]{2,40}):\s+(.*)$")
COVER_PAGE_MARKERS = ("SEBI (Listing Obligations", "MANAGEMENT:")
BOUNDARY_RE = re.compile(r'next question|last question|first question', re.I)
DISCONNECT_KEYWORDS = ("disconnect", "reconnect", "stay connected", "rejoin")


def extract_pages(pdf_source):
    """pdf_source: a file path, or a file-like object (e.g. the BytesIO
    src/cloud.py returns when a transcript is downloaded from R2 in memory)."""
    with pdfplumber.open(pdf_source) as pdf:
        return [p.extract_text() or "" for p in pdf.pages]


def split_cover_and_body(pages):
    """Cover/title pages carry quarter+date+management metadata but aren't
    dialogue; body pages are the actual transcript."""
    cover_text, body_pages = "", []
    for page in pages:
        if any(marker in page for marker in COVER_PAGE_MARKERS):
            cover_text += "\n" + page
        else:
            body_pages.append(page)
    return cover_text, body_pages


COMPANY_NAME_RE = re.compile(r'[“"]([A-Z][A-Za-z&\.\s]+?(?:Limited|Ltd\.?))', re.I)


def extract_company_name(cover_text: str) -> str:
    m = COMPANY_NAME_RE.search(cover_text)
    return m.group(1).strip() if m else ""


def extract_metadata(cover_text: str):
    qm = QUARTER_RE.search(cover_text)
    quarter = f"Q{qm.group(1)}FY{qm.group(2)[-2:]}" if qm else None
    fiscal_year = f"FY{qm.group(2)[-2:]}" if qm else None

    call_date = None
    # Companies phrase the filing date differently - "on Wednesday, July 15,
    # 2026" (with weekday) vs "conducted on April 29, 2024" (without). Try
    # the more specific pattern first, fall back to the looser one.
    call_date_m = (
        re.search(r'on\s+\w+day,\s+([A-Z][a-z]+ \d{1,2},\s*20\d\d)', cover_text)
        or re.search(r'(?:conducted|held)\s+on\s+([A-Z][a-z]+ \d{1,2},\s*20\d\d)', cover_text)
    )
    if call_date_m:
        from datetime import datetime
        try:
            call_date = datetime.strptime(call_date_m.group(1), "%B %d, %Y").strftime("%Y-%m-%d")
        except ValueError:
            call_date = None

    mgmt_block = re.search(r'MANAGEMENT(?:\s+TEAM)?:(.*?)MODERATORS?:', cover_text, re.S)
    management_names = set()
    if mgmt_block:
        for line in mgmt_block.group(1).split("\n"):
            m = re.search(r'MR\.|MS\.|MRS\.', line)
            name_m = re.search(r'(?:MR\.|MS\.|MRS\.)\s+([A-Z][A-Za-z\.\s]+?)(?:\s*[-–]|$)', line)
            if name_m:
                last_token = name_m.group(1).strip().split()[-1]
                management_names.add(last_token.upper())

    return {
        "quarter": quarter,
        "fiscal_year": fiscal_year,
        "call_date": call_date,
        "management_names": management_names,
        "company_name": extract_company_name(cover_text),
    }


def clean_body(pages, company_hint: str):
    lines = []
    for page in pages:
        for raw in page.split("\n"):
            s = raw.strip()
            if not s:
                continue
            if re.match(r'^Page \d+ of \d+$', s):
                continue
            if company_hint and s.lower() == company_hint.lower():
                continue
            if DATE_RE.fullmatch(s):
                continue
            lines.append(s)
    return "\n".join(lines)


def parse_speaker_turns(text: str):
    lines = text.split("\n")
    turns = []
    current_speaker, current_text = None, []
    for ln in lines:
        m = SPEAKER_RE.match(ln)
        if m and len(m.group(1).split()) <= 6:
            if current_speaker:
                turns.append((current_speaker.strip(), " ".join(current_text).strip()))
            current_speaker = m.group(1).strip()
            current_text = [m.group(2).strip()]
        elif current_speaker:
            current_text.append(ln.strip())
    if current_speaker:
        turns.append((current_speaker.strip(), " ".join(current_text).strip()))
    return turns


def find_qa_start(turns):
    """First Moderator turn that hands off to the first question. Transcripts
    phrase this inconsistently ("question-and-answer session" vs "The first
    question is from..."), so match on the same boundary phrases used to
    split individual Q&A exchanges."""
    for i, (spk, txt) in enumerate(turns):
        if spk.lower() == "moderator" and BOUNDARY_RE.search(txt):
            return i
    return len(turns)


def speaker_role(speaker: str, management_names: set) -> str:
    low = speaker.lower()
    if low == "moderator":
        return "Moderator"
    last_token = speaker.strip().split()[-1].upper() if speaker.strip() else ""
    if last_token in management_names:
        return "Management"
    return "Analyst"


def parse_transcript(pdf_source):
    """pdf_source: path or file-like object. Returns (turns, metadata) where
    turns = [(speaker, text), ...]."""
    pages = extract_pages(pdf_source)

    # Quarter/date/management always live in the filing letter + title page,
    # which are consistently the first couple of pages - but not every
    # company's title page trips the COVER_PAGE_MARKERS check (e.g. one
    # writes "NH MANAGEMENT TEAM:" instead of "MANAGEMENT:", which
    # split_cover_and_body's substring match misses entirely, leaving it
    # with no cover text to search at all). Search the raw first pages
    # directly so metadata extraction doesn't depend on that detection.
    header_text = "\n".join(pages[:2])
    metadata = extract_metadata(header_text)

    _, body_pages = split_cover_and_body(pages)
    cleaned = clean_body(body_pages, metadata["company_name"])
    turns = parse_speaker_turns(cleaned)
    return turns, metadata
