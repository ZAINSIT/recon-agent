"""
app.py — Streamlit UI for the reconciliation flow visualiser.

Shows the Sankey, a stage summary, and a drill-down: pick a stage, see the
settlements in it; pick a settlement, see its full ledger row (including the
LLM proposal and the validator's reason for rejected rows).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from pathlib import Path

ROOT = Path(__file__).parent
LEDGER = ROOT / "matched_ledger_stage3.csv"
FLOW_JSON = ROOT / "flow_detail.json"

st.set_page_config(page_title="Recon · flow", layout="wide")


@st.cache_data
def load():
    ledger = pd.read_csv(LEDGER)
    detail = json.loads(FLOW_JSON.read_text()) if FLOW_JSON.exists() else {}
    return ledger, detail


def classify(row) -> str:
    if row["stage"] == "exact": return "Resolved (exact)"
    if row["stage"] == "fuzzy": return "Resolved (fuzzy)"
    if row["stage"] == "llm": return "Resolved (LLM)"
    m = str(row["method_detail"])
    if m == "llm_rejected": return "Rejected by validator"
    if m == "llm_no_match": return "Declined by model"
    if m == "llm_error": return "API error"
    return "Unresolved"


@st.cache_data
def build_sankey(ledger: pd.DataFrame):
    total = len(ledger)
    s1 = int((ledger["stage"] == "exact").sum())
    s2 = int((ledger["stage"] == "fuzzy").sum())

    def classify(r):
        if r["stage"] == "exact": return "Resolved (exact)"
        if r["stage"] == "fuzzy": return "Resolved (fuzzy)"
        if r["stage"] == "llm": return "Resolved (LLM)"
        m = str(r["method_detail"])
        if m == "llm_rejected": return "Rejected by validator"
        if m == "llm_no_match": return "Declined by model"
        if m == "llm_error": return "API error"
        return "Unresolved"

    outcomes = ledger.apply(classify, axis=1).value_counts()

    order = [
        "Resolved (exact)", "Resolved (fuzzy)", "Resolved (LLM)",
        "Rejected by validator", "Declined by model", "API error", "Unresolved",
    ]

    labels = ["Settlements", "Stage 1: Exact", "Stage 2: Fuzzy", "Stage 3: LLM"]
    labels += [o for o in order if outcomes.get(o, 0) > 0]
    idx = {l: i for i, l in enumerate(labels)}

    src, tgt, val = [], [], []
    def link(a, b, v):
        if v > 0:
            src.append(idx[a]); tgt.append(idx[b]); val.append(int(v))

    link("Settlements", "Stage 1: Exact", total)
    link("Stage 1: Exact", "Resolved (exact)", s1)
    link("Stage 1: Exact", "Stage 2: Fuzzy", total - s1)
    link("Stage 2: Fuzzy", "Resolved (fuzzy)", s2)
    link("Stage 2: Fuzzy", "Stage 3: LLM", total - s1 - s2)
    for o in order:
        link("Stage 3: LLM", o, int(outcomes.get(o, 0)))

    colour = {
        "Settlements": "#6366f1", "Stage 1: Exact": "#3b82f6",
        "Stage 2: Fuzzy": "#0ea5e9", "Stage 3: LLM": "#8b5cf6",
        "Resolved (exact)": "#10b981", "Resolved (fuzzy)": "#34d399",
        "Resolved (LLM)": "#6ee7b7", "Rejected by validator": "#f59e0b",
        "Declined by model": "#fbbf24", "API error": "#ef4444", "Unresolved": "#9ca3af",
    }

    fig = go.Figure(go.Sankey(
        node=dict(
            label=labels,
            pad=35,              # Enough space for labels
            thickness=20,        # Clean, thin bars
            color=[colour.get(l, "#94a3b8") for l in labels],
            line=dict(color="white", width=0.5),
        ),
        link=dict(source=src, target=tgt, value=val, color="rgba(148,163,184,0.35)"),
    ))
    
    fig.update_layout(
        height=550,              # Taller to match the HTML look
        margin=dict(l=10, r=10, t=10, b=10),
        font=dict(family="Inter, system-ui, sans-serif", size=13),
        paper_bgcolor="rgba(0,0,0,0)",  # Ensures background looks clean in Streamlit
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig
def main():
    st.title("Recon · settlement flow")
    st.caption("How 509 settlements moved through the pipeline, and where they ended up.")

    ledger, detail = load()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Settlements", len(ledger))
    col2.metric("Resolved", int((ledger["stage"].isin(["exact", "fuzzy", "llm"])).sum()))
    col3.metric("Validator rejected", int((ledger["method_detail"] == "llm_rejected").sum()))
    col4.metric("Unresolved", int((ledger["stage"] == "unresolved").sum()))

    st.plotly_chart(build_sankey(ledger), use_container_width=True)

    st.subheader("Drill down")
    stages = [l for l in detail if l != "Settlements" and detail[l]]
    stage = st.selectbox("Pick a stage or outcome", stages)
    ids = detail.get(stage, [])
    st.write(f"**{len(ids)}** settlements in **{stage}**")

    if ids:
        pick = st.selectbox("Pick a settlement", ids)
        row = ledger[ledger["settlement_id"] == pick].iloc[0].to_dict()
        clean = {k: (None if pd.isna(v) else v) for k, v in row.items()}
        st.json(clean)


if __name__ == "__main__":
    main()