"""
visualize_flow.py — render the reconciliation pipeline as a Sankey diagram.

Reads matched_ledger_stage3.csv and produces eval/flow.html: a flow diagram
showing how settlements distributed across the three stages and their final
outcomes. Band widths are proportional to the number of settlements.

Also writes eval/flow_detail.json: per-node settlement ID lists, so the
Streamlit app can look up what's in each band.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

BATCH = Path("data/batch_001")
LEDGER = BATCH / "matched_ledger_stage3.csv"
OUT_HTML = Path("eval/flow.html")
OUT_JSON = Path("eval/flow_detail.json")


def classify(row: pd.Series) -> str:
    stage = row["stage"]
    method = str(row["method_detail"])
    if stage == "exact":
        return "Resolved (exact)"
    if stage == "fuzzy":
        return "Resolved (fuzzy)"
    if stage == "llm":
        return "Resolved (LLM)"
    if method == "llm_rejected":
        return "Rejected by validator"
    if method == "llm_no_match":
        return "Declined by model"
    if method == "llm_error":
        return "API error"
    return "Unresolved"


def build_flow(df: pd.DataFrame):
    total = len(df)
    s1_matched = int((df["stage"] == "exact").sum())
    s2_matched = int((df["stage"] == "fuzzy").sum())
    s1_remainder = total - s1_matched
    s2_remainder = s1_remainder - s2_matched

    outcomes = df.apply(classify, axis=1).value_counts()
    outcome_order = [
        "Resolved (exact)",
        "Resolved (fuzzy)",
        "Resolved (LLM)",
        "Rejected by validator",
        "Declined by model",
        "API error",
        "Unresolved",
    ]

    labels = ["Settlements", "Stage 1: Exact", "Stage 2: Fuzzy", "Stage 3: LLM"]
    labels += [o for o in outcome_order if outcomes.get(o, 0) > 0]
    idx = {label: i for i, label in enumerate(labels)}

    sources, targets, values = [], [], []

    sources.append(idx["Settlements"]); targets.append(idx["Stage 1: Exact"]); values.append(total)
    sources.append(idx["Stage 1: Exact"]); targets.append(idx["Resolved (exact)"]); values.append(s1_matched)
    sources.append(idx["Stage 1: Exact"]); targets.append(idx["Stage 2: Fuzzy"]); values.append(s1_remainder)
    sources.append(idx["Stage 2: Fuzzy"]); targets.append(idx["Resolved (fuzzy)"]); values.append(s2_matched)
    sources.append(idx["Stage 2: Fuzzy"]); targets.append(idx["Stage 3: LLM"]); values.append(s2_remainder)
    for outcome in ["Resolved (LLM)", "Rejected by validator", "Declined by model", "API error", "Unresolved"]:
        n = int(outcomes.get(outcome, 0))
        if n > 0:
            sources.append(idx["Stage 3: LLM"]); targets.append(idx[outcome]); values.append(n)

    df = df.copy()
    df["outcome"] = df.apply(classify, axis=1)
    detail: dict[str, list[str]] = {}
    for label in labels:
        if label == "Settlements":
            detail[label] = df["settlement_id"].tolist()
        elif label == "Stage 1: Exact":
            detail[label] = df["settlement_id"].tolist()
        elif label == "Stage 2: Fuzzy":
            detail[label] = df[df["stage"] != "exact"]["settlement_id"].tolist()
        elif label == "Stage 3: LLM":
            detail[label] = df[
                (df["stage"] == "llm")
                | (df["method_detail"].isin(["llm_rejected", "llm_no_match", "llm_error"]))
            ]["settlement_id"].tolist()
        else:
            detail[label] = df[df["outcome"] == label]["settlement_id"].tolist()

    return labels, sources, targets, values, detail


def main() -> None:
    df = pd.read_csv(LEDGER)
    labels, sources, targets, values, detail = build_flow(df)

    colour_map = {
        "Settlements": "#6366f1",
        "Stage 1: Exact": "#3b82f6",
        "Stage 2: Fuzzy": "#0ea5e9",
        "Stage 3: LLM": "#8b5cf6",
        "Resolved (exact)": "#10b981",
        "Resolved (fuzzy)": "#34d399",
        "Resolved (LLM)": "#6ee7b7",
        "Rejected by validator": "#f59e0b",
        "Declined by model": "#fbbf24",
        "API error": "#ef4444",
        "Unresolved": "#9ca3af",
    }

    fig = go.Figure(go.Sankey(
        node=dict(
            label=labels,
            pad=20,
            thickness=20,
            color=[colour_map.get(l, "#94a3b8") for l in labels],
            line=dict(color="white", width=0.5),
        ),
        link=dict(source=sources, target=targets, value=values, color="rgba(148,163,184,0.35)"),
    ))
    fig.update_layout(
        title_text="Recon: settlement flow through the pipeline",
        font=dict(size=13, family="Inter, system-ui, sans-serif"),
        height=600,
        margin=dict(l=20, r=20, t=60, b=20),
    )

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(OUT_HTML, include_plotlyjs="cdn")
    OUT_JSON.write_text(json.dumps(detail, indent=2) + "\n")

    print(f"Wrote {OUT_HTML}")
    print(f"Wrote {OUT_JSON}")
    print()
    print("Flow summary:")
    for label in labels[1:]:
        n = len(detail[label])
        if n:
            print(f"  {label}: {n}")


if __name__ == "__main__":
    main()