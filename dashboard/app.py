"""
CloudSentinel Command Center (Streamlit).   Owner: Tamjid.

    streamlit run dashboard/app.py

This is a WORKING BASELINE so everyone can see data from day one. Tamjid makes it great:
design, nicer charts, "money saved" counter, sounds/animations on kill, etc.

Rules for this file:
  • Read data ONLY through get_store()  (never call Supabase/SQLite directly)
  • The kill switch ONLY inserts a CommandRow — the dashboard never touches Docker.
    The sentinel executes the command within ~1 second.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so `shared` is importable

import pandas as pd
import streamlit as st

from shared.contracts import CommandRow
from shared.store import get_store

COST_PER_1K_TOKENS_USD = 0.01   # demo number for the "money saved" counter

st.set_page_config(page_title="CloudSentinel", page_icon="🛡️", layout="wide")
store = get_store()

st.title("🛡️ CloudSentinel — Command Center")
st.caption("Circuit breaker for AI agents. Watching token spend, loops and memory in real time.")


@st.fragment(run_every="2s")
def live_panel() -> None:
    metrics = pd.DataFrame(store.recent_metrics(minutes=5))
    actions = pd.DataFrame(store.recent_actions(limit=50))

    if metrics.empty:
        st.info("No data yet. Start the sentinel:  `python -m sentinel --fake`  (or with Docker).")
        return

    metrics["created_at"] = pd.to_datetime(metrics["created_at"], utc=True, format="ISO8601")
    latest = metrics.sort_values("created_at").groupby("agent").tail(1).set_index("agent")

    # ── top numbers ──
    killed = actions[actions["action"] == "KILL"] if not actions.empty else actions
    saved_tokens = int(killed["tokens_saved_estimate"].sum()) if not killed.empty else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Agents running", int((latest["status"] != "killed").sum()))
    c2.metric("Agents killed", len(killed))
    c3.metric("Tokens/min (all)", f"{int(latest.loc[latest['status'] != 'killed', 'tokens_per_min'].sum()):,}")
    c4.metric("Est. saved (1h)", f"${saved_tokens / 1000 * COST_PER_1K_TOKENS_USD:,.2f}")

    # ── token flow chart ──
    st.subheader("Token flow (tokens / minute)")
    chart = metrics.pivot_table(index="created_at", columns="agent", values="tokens_per_min", aggfunc="last")
    st.line_chart(chart)

    # ── per-agent cards with the kill switch ──
    st.subheader("Agents")
    cols = st.columns(max(len(latest), 1))
    for col, (agent, row) in zip(cols, latest.iterrows()):
        with col:
            icon = {"running": "🟢", "warned": "🟠", "killed": "💀"}.get(row["status"], "⚪")
            st.markdown(f"### {icon} {agent}")
            st.write(f"**{row['tokens_per_min']:,}** tokens/min · **{row['calls_per_sec']}** calls/s")
            st.write(f"Memory **{row['memory_pct']:.0f}%** · same prompt ×{row['loop_repeats']}")
            st.progress(min(row["total_tokens"] / max(row["token_budget"], 1), 1.0),
                        text=f"Budget {row['total_tokens']:,} / {row['token_budget']:,}")
            if row["status"] != "killed":
                if st.button("🛑 EMERGENCY KILL", key=f"kill-{agent}", type="primary"):
                    store.insert_command(CommandRow(agent, "KILL", "dashboard", "Emergency kill switch"))
                    st.toast(f"Kill command sent to {agent}")
                if st.button("😈 Simulate rogue", key=f"rogue-{agent}"):
                    store.insert_command(CommandRow(agent, "GO_ROGUE", "dashboard", "demo"))
                    st.toast(f"{agent} will go rogue")

    # ── activity log ──
    left, right = st.columns(2)
    with left:
        st.subheader("Actions")
        st.dataframe(actions, hide_index=True, width="stretch")
    with right:
        st.subheader("Alerts")
        st.dataframe(pd.DataFrame(store.recent_alerts(limit=30)), hide_index=True, width="stretch")


live_panel()
