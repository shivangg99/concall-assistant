"""Streamlit chat UI for the concall RAG assistant. Run with: streamlit run app.py"""
import os

import streamlit as st

st.set_page_config(page_title="Concall Assistant", page_icon="📞", layout="centered")

# On Streamlit Community Cloud, keys live in st.secrets (set via the
# dashboard), not a .env file - copy them into os.environ so the rest of
# the codebase (which reads via os.environ, for local .env compatibility)
# works unchanged in both places. Running locally with no secrets.toml,
# st.secrets raises on access, which just means .env already has what's
# needed.
try:
    for _k, _v in st.secrets.items():
        os.environ.setdefault(_k, str(_v))
except Exception:
    pass

from src.store import PERSIST_DIR  # noqa: E402

# A freshly deployed instance starts with an empty disk - data/chroma/
# only exists on whichever machine last ran ingestion. Pull down the last
# snapshot published via `python -m src.db_sync upload` before anything
# tries to read the store. No-op if data/chroma/ already has content
# (i.e. running locally against your own ingested data).
if not os.path.isdir(PERSIST_DIR) or not os.listdir(PERSIST_DIR):
    with st.spinner("Loading transcript data..."):
        try:
            from src.db_sync import download_snapshot
            download_snapshot()
        except Exception as e:
            st.warning(f"Couldn't load the transcript data snapshot from R2: {e}")

from src.query import answer as run_query  # noqa: E402
from src.store import stats as store_stats, ticker_display_info  # noqa: E402

st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
    /* Shared design tokens with the partner-pitch mockup (docs/pitch-mockup.html) -
    same teal, same type pairing, so the standalone app and the "embedded in
    someone else's site" concept read as one product family. */
    :root {
        --ink: #14181F; --ink-soft: #5B6472; --line: #E2E5E1;
        --feature: #0F6B63; --feature-ink: #0B4F49;
        --feature-tint: #E3EEEC; --feature-line: #C7DEDB;
    }
    .stApp, .stApp p, .stApp span, .stApp div, .stApp button, .stApp input,
    .stApp textarea, .stApp h1, .stApp h2, .stApp h3, .stApp label, .stApp li {
        font-family: 'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif;
    }
    /* Streamlit's own chevrons/icons (sidebar toggle, expander arrows) are a
    ligature-text icon font, not a symbol image - the blanket rule above
    was overriding it too, so every icon rendered as literal text like
    "keyboard_arrow_right". Restore the icon font specifically, after the
    blanket rule so it wins on specificity. */
    .stApp [data-testid="stIconMaterial"] { font-family: 'Material Symbols Rounded' !important; }
    .mono { font-family: 'IBM Plex Mono', ui-monospace, monospace !important; font-variant-numeric: tabular-nums; }

    /* Hide Streamlit's own branding, but NOT stExpandSidebarButton - that's
    the only way to reopen a collapsed sidebar on mobile, and it lives in
    the same header region as the buttons we do want gone. */
    #MainMenu, footer, [data-testid="stAppDeployButton"] { visibility: hidden; height: 0; }
    .block-container { max-width: 720px; padding-top: 3rem; }

    /* st.chat_input renders with a runaway height on first load in a short
    page (no messages yet) - cap it so it reads as a normal input, not a
    broken textarea. It can still grow a little for a long question. */
    [data-testid="stChatInput"] textarea { max-height: 5.5rem !important; }

    h1 { font-weight: 700; letter-spacing: -0.01em; }
    p.subtitle { color: var(--ink-soft); font-size: 1.02rem; margin-top: -0.6rem; margin-bottom: 1.8rem; }

    .ticker-row { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.3rem 0 0.2rem; }
    .ticker-pill {
        font-family: 'IBM Plex Mono', ui-monospace, monospace !important;
        background: var(--feature-tint); color: var(--feature-ink); border: 1px solid var(--feature-line);
        border-radius: 999px; padding: 0.15rem 0.7rem; font-size: 0.82rem; font-weight: 600;
        cursor: default;
    }
    .sidebar-label {
        font-size: 0.78rem; font-weight: 600; letter-spacing: 0.03em; text-transform: uppercase;
        color: var(--ink-soft); margin-bottom: 0.3rem;
    }
    [data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] p { color: var(--ink-soft); }

    .source-card {
        border: 1px solid var(--line); border-radius: 8px; padding: 0.7rem 0.9rem;
        margin-bottom: 0.6rem; background: #FBFBFA;
    }
    .source-meta { font-size: 0.83rem; font-weight: 600; color: var(--feature-ink); margin-bottom: 0.25rem; }
    .source-text { font-size: 0.85rem; color: #3A414B; }

    /* Example-question chips: compact, rounded, teal-on-tint - matching the
    pitch mockup's qa-chip treatment, instead of full-width default buttons. */
    div[data-testid="stButton"] button {
        border-radius: 999px; border: 1px solid var(--feature-line); background: #FFFFFF;
        color: var(--feature-ink); font-size: 0.83rem; padding: 0.4rem 0.9rem;
    }
    div[data-testid="stButton"] button:hover { background: var(--feature-tint); border-color: var(--feature-line); }
    div[data-testid="stButton"] button p { text-align: left; font-size: 0.83rem; }
</style>
""", unsafe_allow_html=True)

st.title("📞 Concall Assistant")
st.markdown('<p class="subtitle">Ask about a company\'s earnings calls — every answer is based only on the actual call transcripts, with citations.</p>', unsafe_allow_html=True)

try:
    db_stats = store_stats()
    display_info = ticker_display_info()
except Exception:
    db_stats = {"total_chunks": 0, "by_ticker_quarter": {}}
    display_info = {}

tickers = sorted({k[0] for k in db_stats["by_ticker_quarter"].keys()})

with st.sidebar:
    st.markdown('<div class="sidebar-label">Companies covered</div>', unsafe_allow_html=True)
    if not tickers:
        st.caption("None yet.")
    else:
        pills = "".join(
            f'<span class="ticker-pill" title="{display_info[t]["company_name"]} · '
            f'{display_info[t]["quarter_range"][0]}–{display_info[t]["quarter_range"][1]}">{t}</span>'
            for t in tickers
        )
        st.markdown(f'<div class="ticker-row">{pills}</div>', unsafe_allow_html=True)

    st.divider()
    st.markdown('<div class="sidebar-label">Narrow your question</div>', unsafe_allow_html=True)
    ticker_filter = st.selectbox("Company", ["All"] + tickers)
    quarter_options = ["All"] + sorted({
        q for (t, q) in db_stats["by_ticker_quarter"].keys()
        if ticker_filter == "All" or t == ticker_filter
    })
    quarter_filter = st.selectbox("Quarter", quarter_options)

    with st.expander("Advanced"):
        top_k = st.slider("Sources per answer", 3, 20, 8)

    st.divider()
    st.caption("Answers are based only on the actual call transcripts — never outside knowledge or estimates.")

MAX_QUESTIONS_PER_SESSION = 20

if "messages" not in st.session_state:
    st.session_state.messages = []
if "filter_key" not in st.session_state:
    st.session_state.filter_key = None
if "question_count" not in st.session_state:
    st.session_state.question_count = 0

# Switching company/quarter mid-conversation changes what's actually being
# asked about, so treat it as a new conversation rather than let a follow-up
# silently carry stale context from before the switch.
current_filter_key = (ticker_filter, quarter_filter)
if st.session_state.filter_key is not None and st.session_state.filter_key != current_filter_key:
    st.session_state.messages = []
st.session_state.filter_key = current_filter_key


def render_sources(sources):
    with st.expander(f"Sources ({len(sources)})"):
        for s in sources:
            st.markdown(
                f"""<div class="source-card">
                <div class="source-meta"><span class="mono">{s['quarter']}</span> · {s['speaker']} ({s['speaker_role']}) · {s['section']}</div>
                <div class="source-text">{s['text'][:500]}{"..." if len(s['text']) > 500 else ""}</div>
                </div>""",
                unsafe_allow_html=True,
            )


EXAMPLE_QUESTIONS = [
    "How has management's commentary on margins changed over the last few quarters?",
    "What guidance has management given for the coming year?",
    "What risks or challenges does management keep bringing up?",
]

if not st.session_state.messages:
    if not tickers:
        st.info("No companies are available to ask about yet.")
    else:
        st.caption("Try asking something like:")
        cols = st.columns(len(EXAMPLE_QUESTIONS))
        for col, q in zip(cols, EXAMPLE_QUESTIONS):
            with col:
                if st.button(q, key=f"ex_{q}", use_container_width=True):
                    st.session_state.pending_question = q

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            render_sources(msg["sources"])

at_limit = st.session_state.question_count >= MAX_QUESTIONS_PER_SESSION
typed_question = st.chat_input(
    "Ask about the transcripts..." if not at_limit else "Session limit reached - refresh the page to continue",
    disabled=not tickers or at_limit,
)
question = typed_question or st.session_state.pop("pending_question", None)

if question and at_limit:
    st.warning(f"You've reached the {MAX_QUESTIONS_PER_SESSION}-question limit for this session. Refresh the page to start a new one.")
    question = None

if question:
    st.session_state.question_count += 1
    history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Retrieving and thinking..."):
            try:
                result = run_query(
                    question,
                    top_k=top_k,
                    ticker=None if ticker_filter == "All" else ticker_filter,
                    quarter=None if quarter_filter == "All" else quarter_filter,
                    history=history,
                )
                st.markdown(result["answer"])
                if result["sources"]:
                    render_sources(result["sources"])
                st.session_state.messages.append({
                    "role": "assistant", "content": result["answer"], "sources": result["sources"],
                })
            except RuntimeError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Something went wrong: {e}")
