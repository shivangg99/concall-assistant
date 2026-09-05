# Concall Assistant

A RAG chatbot for long-term investors: ask natural-language questions about a company's
earnings-call transcripts and get answers grounded in the actual transcript text, with
inline citations to quarter and speaker. See [PRD_ConCall_RAG_Chatbot.docx](PRD_ConCall_RAG_Chatbot.docx)
for the full product spec.

Pipeline: PDF transcript (in Cloudflare R2) -> parse & chunk (by speaker turn / Q&A pair)
-> embed (Voyage AI) -> store (Chroma, local) -> retrieve + generate (Claude) -> Streamlit chat UI.

For a function-by-function walkthrough of how the pipeline actually runs (with a diagram),
see [`docs/internals.html`](docs/internals.html) — download it and open in a browser, or view it
live at [claude.ai/code/artifact/fa72f88a-ecfb-4f79-975f-0bc0cdfd204c](https://claude.ai/code/artifact/fa72f88a-ecfb-4f79-975f-0bc0cdfd204c)
(private artifact link — visible only to the account that created it).

[`docs/pitch-mockup.html`](docs/pitch-mockup.html) is a concept mockup for pitching this as an
embedded feature on someone else's stock-research site — a generic "your platform" page with the
Q&A widget dropped in, using real cited answers from the JINDALSAW data already ingested here.

## Prerequisites

- Python 3.9+
- An [Anthropic API key](https://console.anthropic.com) (Settings -> API Keys)
- A [Voyage AI API key](https://dash.voyageai.com) (free tier: 200M tokens, plenty for this project)
- A [Cloudflare R2](https://dash.cloudflare.com) bucket (free tier: 10GB storage, zero egress fees)
  for storing source transcript PDFs — R2 speaks the S3 API, so it's just `boto3` under the hood,
  no AWS account needed. Create a bucket, then create an API token scoped to it under
  **R2 -> Manage API tokens** with **Object Read & Write** permission.

## Setup

```bash
# from the project root
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# open .env and fill in ANTHROPIC_API_KEY, VOYAGE_API_KEY, and the R2_* fields
```

The easiest R2 field to grab is `R2_ENDPOINT_URL` — open your bucket -> **Settings -> S3 API**
and copy the endpoint shown there directly. `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` come from
the API token (shown once at creation — copy them immediately).

> Voyage's free tier is rate-limited (3 requests/min) until you add a payment method on the
> [Voyage dashboard](https://dashboard.voyageai.com/) — the 200M free tokens still apply after
> that, it just removes the throttle. Ingestion works either way, just slower without a card on file.

## Upload and ingest transcripts

Source PDFs live in the R2 bucket under `<TICKER>/<filename>.pdf`, not in this repo. To add a new
company: upload its PDFs, then ingest — no code changes needed as long as the transcripts follow
the same SEBI Regulation-30 filing format (cover letter + title page with quarter/date/management
names, cleaned by `src/parse.py`).

```bash
source .venv/bin/activate

python -m src.upload_transcripts path/to/local/pdfs TICKER   # one-off: push local PDFs to R2
python -m src.ingest                                         # ingest every ticker in the bucket
python -m src.ingest TICKER                                  # ingest just one ticker
```

Ingestion downloads each PDF from R2 straight into memory (no local disk writes) and is
idempotent — chunk IDs are stable, so re-running overwrites in place rather than duplicating.
Chunks are embedded and stored in a local Chroma DB at `data/chroma/`.

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

## Deploying it as a public site

The app is stateless w.r.t. its vector data at runtime, but Chroma itself is just local files
(`data/chroma/`) — a deployed instance runs on a different machine with an empty disk, so that
data has to get there somehow. The bridge is a DB snapshot in R2:

```bash
source .venv/bin/activate
python -m src.db_sync upload     # run locally after ingesting new data, to publish it
```

`app.py` calls the matching `download_snapshot()` automatically on startup if `data/chroma/` is
empty — so a fresh deployment bootstraps itself from whatever you last published. Running
locally against your own already-ingested data is unaffected (it skips the download entirely
since local data already exists).

To deploy on **[Streamlit Community Cloud](https://share.streamlit.io)** (free):
1. Push this repo to GitHub (already done if you're reading this from there).
2. On share.streamlit.io, connect your GitHub account, pick this repo/branch and `app.py`.
3. In the app's **Settings -> Secrets**, paste the same key/value pairs from your local `.env`
   in TOML format (`ANTHROPIC_API_KEY = "..."`, `VOYAGE_API_KEY = "..."`, the `R2_*` fields) —
   `.env` itself never gets deployed since it's gitignored.
4. Deploy. First load will show "Loading transcript data..." while it pulls the R2 snapshot,
   then behaves identically to running it locally.

Whenever you ingest new tickers or quarters locally, re-run `python -m src.db_sync upload` and
the next visit to the deployed app (or a manual reboot from the Streamlit Cloud dashboard) picks
it up — there's no automatic re-sync, this is a manual "publish" step by design for now.

A public, unauthenticated deployment means API cost scales with anyone's usage, not just yours -
`app.py` caps each browser session to 20 questions as a lightweight guardrail against a bot or a
single heavy visitor running up spend; there's no other access control by default.

## Project layout

```
src/cloud.py                     Cloudflare R2 client (list/download/upload transcript PDFs)
src/upload_transcripts.py        one-off script: push local PDFs to R2 under <ticker>/
src/parse.py                     PDF -> cleaned speaker turns + metadata (quarter, date, management roster)
src/chunk.py                     speaker-turn / Q&A-pair chunking, capped to ~400 tokens/chunk
src/embeddings.py                Voyage AI embedding calls, with rate-limit retry
src/store.py                     Chroma persistent vector store wrapper
src/ingest.py                    ingestion orchestrator: R2 -> parse -> chunk -> embed -> Chroma
src/query.py                     retrieval + Claude generation with citations
src/db_sync.py                   publish/bootstrap the Chroma DB to/from R2, for deployment
app.py                           Streamlit chat UI
data/chroma/                     local vector DB (gitignored, rebuilt by ingestion)
docs/internals.html              function-by-function pipeline walkthrough, with diagram
files/                           earlier TF-IDF prototype, superseded by src/
```

Source transcript PDFs are no longer stored in this repo or required to sit on any one machine's
disk — `cocnall-scripts/` (gitignored) is only used as a local staging folder before running
`upload_transcripts.py`; the R2 bucket is the actual source of truth.
