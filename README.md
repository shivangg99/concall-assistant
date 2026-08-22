# Concall Assistant

A RAG chatbot for long-term investors: ask natural-language questions about a company's
earnings-call transcripts and get answers grounded in the actual transcript text, with
inline citations to quarter and speaker. See [PRD_ConCall_RAG_Chatbot.docx](PRD_ConCall_RAG_Chatbot.docx)
for the full product spec.

Pipeline: PDF transcript -> parse & chunk (by speaker turn / Q&A pair) -> embed (Voyage AI)
-> store (Chroma, local) -> retrieve + generate (Claude) -> Streamlit chat UI.

## Prerequisites

- Python 3.9+
- An [Anthropic API key](https://console.anthropic.com) (Settings -> API Keys)
- A [Voyage AI API key](https://dash.voyageai.com) (free tier: 200M tokens, plenty for this project)

## Setup

```bash
# from the project root
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# open .env and paste in your ANTHROPIC_API_KEY and VOYAGE_API_KEY
```

> Voyage's free tier is rate-limited (3 requests/min) until you add a payment method on the
> [Voyage dashboard](https://dashboard.voyageai.com/) — the 200M free tokens still apply after
> that, it just removes the throttle. Ingestion works either way, just slower without a card on file.

## Ingest transcripts

Transcripts live under `cocnall-scripts/<TICKER>/*.pdf` — one folder per ticker. To add a new
company, drop its PDFs into a new `cocnall-scripts/<TICKER>/` folder; no code changes needed as
long as the transcripts follow the same SEBI Regulation-30 filing format (cover letter + title
page with quarter/date/management names, cleaned by `src/parse.py`).

```bash
source .venv/bin/activate

python -m src.ingest            # ingest every ticker under cocnall-scripts/
python -m src.ingest JINDALSAW  # ingest just one ticker
```

This is idempotent — chunk IDs are stable, so re-running overwrites in place rather than
duplicating. Chunks are embedded and stored in a local Chroma DB at `data/chroma/`.

## Run the chat app

```bash
source .venv/bin/activate
streamlit run app.py
```

Opens at `http://localhost:8501`. Filter by ticker/quarter in the sidebar, ask a question, and
expand "Sources" under any answer to see the retrieved chunks (quarter, speaker, role, section,
relevance score) it was grounded in.

## Query from the command line

```bash
source .venv/bin/activate
python -m src.query "How has management's commentary on debt reduction evolved across recent quarters?"
```

## Project layout

```
cocnall-scripts/<TICKER>/*.pdf   raw transcript PDFs, one folder per company
src/parse.py                     PDF -> cleaned speaker turns + metadata (quarter, date, management roster)
src/chunk.py                     speaker-turn / Q&A-pair chunking, capped to ~400 tokens/chunk
src/embeddings.py                Voyage AI embedding calls, with rate-limit retry
src/store.py                     Chroma persistent vector store wrapper
src/ingest.py                    ingestion orchestrator (run as a script)
src/query.py                     retrieval + Claude generation with citations
app.py                           Streamlit chat UI
data/chroma/                     local vector DB (gitignored, rebuilt by ingestion)
files/                           earlier TF-IDF prototype, superseded by src/
```
