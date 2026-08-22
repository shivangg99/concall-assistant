"""Streamlit chat UI for the concall RAG assistant. Run with: streamlit run app.py"""
import streamlit as st

from src.query import answer as run_query
from src.store import stats as store_stats

st.set_page_config(page_title="Concall Assistant", page_icon="📞", layout="wide")

st.title("📞 Concall Assistant")
st.caption("Ask questions grounded in your ingested earnings-call transcripts.")

try:
    db_stats = store_stats()
except Exception as e:
    db_stats = {"total_chunks": 0, "by_ticker_quarter": {}}

tickers = sorted({k[0] for k in db_stats["by_ticker_quarter"].keys()})

with st.sidebar:
    st.header("Filters")
    if db_stats["total_chunks"] == 0:
        st.warning("No data ingested yet. Run:\n\n`python -m src.ingest`\n\nfrom the project root first.")
    else:
        st.metric("Chunks indexed", db_stats["total_chunks"])
        for (t, q), n in sorted(db_stats["by_ticker_quarter"].items()):
            st.caption(f"{t} · {q} · {n} chunks")

    ticker_filter = st.selectbox("Ticker", ["All"] + tickers)
    quarter_options = ["All"] + sorted({
        q for (t, q) in db_stats["by_ticker_quarter"].keys()
        if ticker_filter == "All" or t == ticker_filter
    })
    quarter_filter = st.selectbox("Quarter", quarter_options)
    top_k = st.slider("Chunks to retrieve", 3, 20, 8)

    st.divider()
    st.caption("Answers are grounded only in retrieved transcript excerpts, with inline citations to quarter and speaker.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            with st.expander(f"Sources ({len(msg['sources'])})"):
                for s in msg["sources"]:
                    st.markdown(
                        f"**{s['quarter']} · {s['speaker']} ({s['speaker_role']}) · {s['section']}** "
                        f"· relevance {s['score']}"
                    )
                    st.text(s["text"][:500] + ("..." if len(s["text"]) > 500 else ""))
                    st.divider()

if question := st.chat_input("Ask about the transcripts..."):
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
                )
                st.markdown(result["answer"])
                if result["sources"]:
                    with st.expander(f"Sources ({len(result['sources'])})"):
                        for s in result["sources"]:
                            st.markdown(
                                f"**{s['quarter']} · {s['speaker']} ({s['speaker_role']}) · {s['section']}** "
                                f"· relevance {s['score']}"
                            )
                            st.text(s["text"][:500] + ("..." if len(s["text"]) > 500 else ""))
                            st.divider()
                st.session_state.messages.append({
                    "role": "assistant", "content": result["answer"], "sources": result["sources"],
                })
            except RuntimeError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Something went wrong: {e}")
