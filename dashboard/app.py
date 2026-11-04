"""
CloudSentinel control tower (Streamlit).   Owner: Tamjid.

    streamlit run dashboard/app.py

WORKING BASELINE so every C2 feature is usable from day one. Tamjid makes it great
(docs/tasks/tamjid.md). Rules: talk to the system ONLY through dashboard/api_client.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so `api_client` imports when run by streamlit

import pandas as pd
import streamlit as st

import api_client as api

STATE_ICON = {"healthy": "🟢", "suspicious": "🟠", "paused": "🟡", "probation": "🔵", "killed": "💀"}

st.set_page_config(page_title="CloudSentinel", page_icon="🛡️", layout="wide")
st.title("🛡️ CloudSentinel: control tower")
st.caption("Circuit breaker for AI agents: observe · decide · pause / heal / kill · prove the savings")


def approvals() -> None:
    pending = api.tool_calls(status="pending")
    for call in pending:
        with st.container(border=True):
            st.warning(f"✋ **{call['agent_id']}** wants to run `{call['tool_name']}` "
                       f"(${call['value_usd']:.2f} at stake): {call['reason']}")
            st.json(call["args"])
            c1, c2, c3 = st.columns(3)
            if c1.button("✅ Approve", key=f"ok-{call['id']}"):
                api.decide(call["id"], "allow", reason="approved on dashboard")
            if c2.button("⛔ Deny", key=f"deny-{call['id']}"):
                api.decide(call["id"], "deny", reason="denied on dashboard")
            new_args = c3.text_input("Rewrite args (JSON)", json.dumps(call["args"]), key=f"rw-{call['id']}")
            if c3.button("✏️ Rewrite", key=f"rwb-{call['id']}"):
                try:
                    api.decide(call["id"], "rewrite", json.loads(new_args), reason="rewritten on dashboard")
                except json.JSONDecodeError:
                    st.error("Invalid JSON")


def agent_cards(agents: list[dict]) -> None:
    cols = st.columns(max(len(agents), 1))
    for col, a in zip(cols, agents):
        with col, st.container(border=True):
            st.markdown(f"### {STATE_ICON.get(a['state'], '⚪')} {a['agent_id']}")
            st.caption(a["state"].upper())
            st.write(f"**${a['usd_per_min']:.4f}**/min · {a['tokens_per_min']:,} tok/min")
            st.progress(min(a["spend_usd"] / max(a["budget_usd"], 1e-9), 1.0),
                        text=f"\\${a['spend_usd']:.3f} / \\${a['budget_usd']:.2f}")  # \$ = no LaTeX
            st.write(f"Loop score **{a['loop_score']:.2f}** · repeats ×{a['exact_repeats']} · mem {a['memory_pct']:.0f}%")
            b1, b2 = st.columns(2)
            if a["state"] in ("healthy", "suspicious", "probation"):
                if b1.button("⏸ Pause", key=f"p-{a['agent_id']}"):
                    api.command(a["agent_id"], "PAUSE", "paused from dashboard")
                if b2.button("🛑 Kill", key=f"k-{a['agent_id']}", type="primary"):
                    api.command(a["agent_id"], "KILL", "emergency kill switch")
                if st.button("😈 Simulate incident", key=f"r-{a['agent_id']}"):
                    kind = {"beta": "paraphrase_loop", "gamma": "token_bomb", "delta": "bad_tool_call"}.get(a["agent_id"], "loop")
                    api.command(a["agent_id"], "GO_ROGUE", "demo", {"kind": kind})
            elif a["state"] == "paused":
                if b1.button("▶️ Resume", key=f"res-{a['agent_id']}"):
                    api.command(a["agent_id"], "RESUME", "resumed from dashboard")
                if b2.button("🛑 Kill", key=f"k2-{a['agent_id']}", type="primary"):
                    api.command(a["agent_id"], "KILL", "killed while paused")
            elif a["state"] == "killed" and b1.button("🔄 Restart", key=f"rs-{a['agent_id']}"):
                api.command(a["agent_id"], "RESTART", "restarted from dashboard")


def memory_editor(agents: list[dict]) -> None:
    ids = [a["agent_id"] for a in agents]
    if not ids:
        return
    agent_id = st.selectbox("Agent", ids, index=ids.index("beta") if "beta" in ids else 0)
    mem = api.memory(agent_id)
    content = json.dumps(mem["content"] if mem else {}, indent=2)
    st.caption(f"version {mem['version']} · last edited by {mem['edited_by']}" if mem else "no memory yet")
    text = st.text_area("Memory (JSON)", content, height=150, key=f"mem-{agent_id}-{mem['version'] if mem else 0}")
    reason = st.text_input("Reason", "fixed a wrong belief", key=f"why-{agent_id}")
    if st.button("💾 Save memory"):
        try:
            api.save_memory(agent_id, json.loads(text), reason, mem["version"] if mem else None)
            st.success("Saved. The agent reads it on its next step.")
        except json.JSONDecodeError:
            st.error("Invalid JSON")
        except api.ApiError as exc:
            st.error(exc.detail)


@st.fragment(run_every="1s")
def live() -> None:
    try:
        health = api.health()
        agents = api.fleet()
    except api.ApiError as exc:
        st.error(f"{exc.detail}. Start the brain: `python -m brain --fake` (or the mock: `python -m shared.mocks.mock_api`).")
        return
    roi = api.roi()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💰 Saved (est.)", f"${roi['saved_usd']:,.2f}")
    c2.metric("Spend", f"${roi['total_spend_usd']:,.3f}")
    c3.metric("Interventions", roi["interventions"])
    c4.metric("Mode / judge", f"{health['mode']} / {health['judge']}")
    approvals()
    agent_cards(agents)

    verdicts = api.verdicts(limit=1)
    if verdicts:
        v = verdicts[0]
        st.info(f"🧠 **{v['source']}** on **{v['agent_id']}**: {v['action']} ({v['confidence']:.0%}, {v['pattern']}): "
                f"{v['reason']}" + (f"\n\n💡 Suggested fix: {v['suggested_fix']}" if v.get("suggested_fix") else ""))

    rows = api.metrics(minutes=5)
    if rows:
        df = pd.DataFrame(rows)
        # one row per agent per tick → round to the second so all agents share a time axis
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True, format="ISO8601").dt.floor("2s")
        st.subheader("Token flow ($/min)")
        st.line_chart(df.pivot_table(index="created_at", columns="agent_id", values="usd_per_min", aggfunc="last"))

    left, right = st.columns(2)
    left.subheader("Actions")
    left.dataframe(pd.DataFrame(api.actions(limit=20)), hide_index=True, width="stretch")
    right.subheader("Alerts")
    right.dataframe(pd.DataFrame(api.alerts(limit=20)), hide_index=True, width="stretch")


live()
with st.expander("🧬 Memory editor (heal an agent)", expanded=True):
    try:
        memory_editor(api.fleet())
    except api.ApiError as exc:
        st.caption(exc.detail)
