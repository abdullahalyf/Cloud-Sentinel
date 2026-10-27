"""
CloudSentinel dashboard: a calm operations console.

Rules (see AGENTS.md):
  - Read data ONLY through get_store(); every number on screen comes from a row.
  - Actions ONLY insert a CommandRow. The dashboard never touches Docker.
  - The live part is an @st.fragment that refreshes itself.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from html import escape as esc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import altair as alt
import pandas as pd
import streamlit as st

from shared.contracts import CommandRow
from shared.store import get_store

REFRESH = "2s"
OFFLINE_AFTER_SECONDS = 15          # no heartbeat for this long = Sentinel OFFLINE
STATUS = {"running": "#3FB97C", "warned": "#E0A93B", "paused": "#E0A93B", "killed": "#E5534B"}
LINES = ["#3987E5", "#D95926", "#199E70"]   # validated categorical order (dark)
MUTED, GRID = "#8B95A5", "#2A313B"

st.set_page_config(page_title="CloudSentinel", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
html, body, [class*="css"] { font-variant-numeric: tabular-nums; }
header[data-testid="stHeader"], #MainMenu, footer { display: none; }
.block-container { padding: 1.5rem 2.5rem 3rem; max-width: 1500px; }
.cs-bar { display:flex; gap:3rem; align-items:flex-end; padding-bottom:1rem; border-bottom:1px solid #2A313B; margin-bottom:1.75rem; }
.cs-bar .k { color:#8B95A5; font-size:.85rem; letter-spacing:.04em; text-transform:uppercase; }
.cs-bar .v { font-size:1.35rem; font-weight:600; line-height:1.5; }
.cs-bar .s { font-size:.9rem; color:#8B95A5; }
.cs-brand { font-size:1.1rem; font-weight:600; margin-right:auto; }
.dot { display:inline-block; width:.6rem; height:.6rem; border-radius:50%; margin-right:.5rem; }
div[data-testid="stHeading"] { margin-top:2rem; }
h3 { font-size:.9rem !important; font-weight:600 !important; letter-spacing:.04em; text-transform:uppercase; color:#8B95A5; padding:0 0 .5rem !important; }
.cs-head { color:#8B95A5; font-size:.85rem; letter-spacing:.04em; text-transform:uppercase; }
.cs-cell { font-size:1rem; line-height:2.4rem; }
.cs-row { border-top:1px solid #2A313B; }
.cs-bar-bg { background:#232A33; height:.4rem; border-radius:2px; margin-top:1.05rem; }
.cs-bar-fg { height:.4rem; border-radius:2px; }
div[data-testid="stHorizontalBlock"]:has(.cs-cell) { border-top:1px solid #1F252E; padding:.25rem 0; }
table.log, table.log th, table.log td { border-left:0 !important; border-right:0 !important; border-top:0 !important; }
table.log { width:100%; border-collapse:collapse; font-size:.95rem; }
table.log th { text-align:left; color:#8B95A5; font-weight:400; font-size:.85rem; letter-spacing:.04em; text-transform:uppercase; padding:.4rem .75rem; border-bottom:1px solid #2A313B; }
table.log td { padding:.45rem .75rem; border-bottom:1px solid #1F252E; vertical-align:top; }
table.log td.t { color:#8B95A5; white-space:nowrap; width:6rem; } table.log td.e { white-space:nowrap; width:11rem; }
table.log tr.kill td { color:#E6EAF0; } table.log tr.kill td.e { color:#E5534B; font-weight:600; }
table.log tr.fresh { animation: hl 3s ease-out; }
@keyframes hl { from { background:#3a1d1f; } to { background:transparent; } }
div[data-testid="stHorizontalBlock"] { align-items:center; }
.stButton button { padding:.1rem .8rem; min-height:2rem; border-radius:4px; }
</style>""", unsafe_allow_html=True)

store = get_store()


# ── data helpers (pure functions over store rows) ────────────────────────────
def age_seconds(created_at: str) -> float:
    return (datetime.now(timezone.utc) - datetime.fromisoformat(created_at.replace("Z", "+00:00"))).total_seconds()


def sentinel_status(alerts: list[dict]) -> tuple[bool, float | None]:
    """(online, seconds since the last heartbeat). (False, None) if there was never one."""
    beats = [a for a in alerts if a["rule"] == "sentinel_heartbeat"]
    if not beats:
        return False, None
    age = min(age_seconds(a["created_at"]) for a in beats)
    return age <= OFFLINE_AFTER_SECONDS, age


def latest_verdict(alerts: list[dict]) -> dict | None:
    """Newest brain verdict. Message looks like 'KILL (80%, infinite_loop): reason'."""
    verdicts = [a for a in alerts if a["rule"].endswith("_verdict")]
    if not verdicts:
        return None
    a = max(verdicts, key=lambda a: a["created_at"])
    head, _, reason = a["message"].partition(":")
    action, _, rest = head.partition(" (")
    conf, _, pattern = rest.rstrip(")").partition(", ")
    return {"agent": a["agent"], "source": a["rule"].removesuffix("_verdict"), "action": action.strip(),
            "confidence": conf, "pattern": pattern, "reason": reason.strip(), "at": a["created_at"]}


def brain_cost(alerts: list[dict]) -> tuple[float, float]:
    """(spent_usd, saved_usd) from the newest 'brain_cost' alert; zeros before the first one."""
    costs = [a for a in alerts if a["rule"] == "brain_cost"]
    if not costs:
        return 0.0, 0.0
    msg = max(costs, key=lambda a: a["created_at"])["message"]
    kv = dict(p.split("=") for p in msg.rsplit("[", 1)[-1].rstrip("]").split() if "=" in p)
    return float(kv["spent_usd"]), float(kv["saved_usd"])


def sparkline(values: list[float], color: str, w: int = 96, h: int = 26) -> str:
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    pts = " ".join(f"{i * w / (len(values) - 1):.1f},{h - 2 - (v - lo) / span * (h - 4):.1f}" for i, v in enumerate(values))
    return (f'<svg width="{w}" height="{h}" style="vertical-align:middle"><polyline points="{pts}" fill="none" '
           f'stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/></svg>')


def send(agent: str, command: str, reason: str) -> None:
    store.insert_command(CommandRow(agent=agent, command=command, requested_by="dashboard", reason=reason))


@st.dialog("Kill agent")
def confirm_kill(agent: str) -> None:
    st.write(f"Stop the **{agent}** container now? The sentinel executes this on its next tick.")
    if st.button("Kill", type="primary"):
        send(agent, "KILL", "Emergency kill switch (dashboard)")
        st.rerun()


# ── sections ─────────────────────────────────────────────────────────────────
def status_bar(alerts: list[dict], latest: pd.DataFrame) -> None:
    online, age = sentinel_status(alerts)
    spent, saved = brain_cost(alerts)
    counts = latest["status"].value_counts() if not latest.empty else pd.Series(dtype=int)
    running = int(counts.get("running", 0) + counts.get("warned", 0))
    sentinel = (f'<span class="dot" style="background:{STATUS["running"]}"></span>Online <span class="s">{age:.0f}s ago</span>'
                if online else
                f'<span class="dot" style="background:{STATUS["killed"]}"></span>Offline '
                f'<span class="s">{"no heartbeat yet" if age is None else f"last seen {age:.0f}s ago"}</span>')
    items = [("Sentinel", sentinel),
             ("Agents", f'{running} running <span class="s">· {int(counts.get("paused", 0))} paused · '
                        f'{int(counts.get("killed", 0))} killed</span>'),
             ("Est. saved", f"${saved:,.2f}"),
             ("Brain spend", f'${spent:.4f} <span class="s">spent to save ${saved:,.2f}</span>')]
    cells = "".join(f'<div><div class="k">{k}</div><div class="v">{v}</div></div>' for k, v in items)
    st.markdown(f'<div class="cs-bar"><div class="cs-brand">CloudSentinel</div>{cells}</div>', unsafe_allow_html=True)


COLS = [2.2, 2.6, 1, 1, 2, 2]


def agents_table(metrics: pd.DataFrame, latest: pd.DataFrame) -> None:
    st.markdown("### Agents")
    heads = st.columns(COLS)
    for c, t in zip(heads, ["Agent", "Tokens / min", "Calls / s", "Memory", "Budget used", ""]):
        c.markdown(f'<span class="cs-head">{t}</span>', unsafe_allow_html=True)
    if latest.empty:
        st.caption("No agents reporting yet. Start the sentinel: `python -m sentinel --fake`")
        return
    for agent, row in latest.iterrows():
        status = row["status"]
        series = metrics[metrics["agent"] == agent].sort_values("created_at")["tokens_per_min"].tail(40).tolist()
        pct = min(100.0, 100.0 * row["total_tokens"] / row["token_budget"]) if row["token_budget"] else 0.0
        bar = STATUS["killed"] if pct >= 90 else STATUS["warned"] if pct >= 70 else MUTED
        c = st.columns(COLS)
        c[0].markdown(f'<div class="cs-cell"><span class="dot" style="background:{STATUS.get(status, MUTED)}"></span>'
                      f'{esc(agent)} <span style="color:{MUTED};font-size:.9rem">{esc(status)}</span></div>', unsafe_allow_html=True)
        c[1].markdown(f'<div class="cs-cell">{sparkline(series, MUTED)} &nbsp;{int(row["tokens_per_min"]):,}</div>', unsafe_allow_html=True)
        c[2].markdown(f'<div class="cs-cell">{row["calls_per_sec"]:.1f}</div>', unsafe_allow_html=True)
        c[3].markdown(f'<div class="cs-cell">{row["memory_pct"]:.0f}%</div>', unsafe_allow_html=True)
        c[4].markdown(f'<div class="cs-bar-bg"><div class="cs-bar-fg" style="width:{pct:.0f}%;background:{bar}"></div></div>'
                      f'<span style="color:{MUTED};font-size:.85rem">{pct:.0f}% of {int(row["token_budget"]):,}</span>', unsafe_allow_html=True)
        a1, a2 = c[5].columns(2)
        if status == "killed":
            a1.caption("stopped")
            continue
        if status == "paused":
            a1.button("Resume", key=f"resume_{agent}", on_click=send, args=(agent, "RESUME", "Resumed from dashboard"))
        else:
            a1.button("Pause", key=f"pause_{agent}", on_click=send, args=(agent, "PAUSE", "Paused from dashboard"))
        if a2.button("Kill", key=f"kill_{agent}"):
            confirm_kill(agent)


def token_chart(metrics: pd.DataFrame, actions: list[dict]) -> None:
    st.markdown("### Tokens per minute, last 5 minutes")
    if metrics.empty:
        st.caption("Waiting for the first metrics.")
        return
    df = metrics[["agent", "created_at", "tokens_per_min"]].copy()
    names = sorted(df["agent"].unique())
    color = alt.Color("agent:N", scale=alt.Scale(domain=names, range=LINES[:len(names)]),
                      legend=alt.Legend(orient="top", offset=0, title=None, labelColor="#E6EAF0", symbolType="stroke"))
    base = alt.Chart(df).encode(x=alt.X("created_at:T", title=None, axis=alt.Axis(format="%H:%M:%S", grid=False)))
    lines = base.mark_line(strokeWidth=2, interpolate="linear").encode(
        y=alt.Y("tokens_per_min:Q", title=None, axis=alt.Axis(gridColor=GRID, tickCount=4)), color=color)
    kills = pd.DataFrame([{"at": a["created_at"], "agent": a["agent"]} for a in actions if a["action"] == "KILL"])
    layers = lines
    if not kills.empty:
        kills["at"] = pd.to_datetime(kills["at"], utc=True)
        rule = alt.Chart(kills).mark_rule(color=STATUS["killed"], strokeDash=[4, 3], strokeWidth=1.5).encode(x="at:T")
        label = alt.Chart(kills).mark_text(color=STATUS["killed"], align="left", dx=5, dy=-4, baseline="bottom", fontSize=12) \
            .encode(x="at:T", y=alt.value(10), text=alt.Text("agent:N"))
        layers = lines + rule + label
    st.altair_chart(layers.properties(height=280).configure_view(stroke=None).configure_axis(
        labelColor=MUTED, domainColor=GRID, tickColor=GRID, labelFontSize=12), width="stretch")


def latest_decision(alerts: list[dict], actions: list[dict]) -> dict | None:
    """Newest decision of any kind: a brain verdict, or a KILL/PAUSE/WARN action (human, rules, brain).
    A brain action is shown through its verdict (it carries confidence and pattern)."""
    v = latest_verdict(alerts)
    act = max(actions, key=lambda a: a["created_at"], default=None)
    if act is None or (v and v["at"] > act["created_at"]):
        return v
    if v and v["agent"] == act["agent"] and act["actor"] == v["source"] and abs(age_seconds(v["at"]) - age_seconds(act["created_at"])) <= 10:
        return v
    return {"agent": act["agent"], "source": act["actor"], "action": act["action"], "confidence": "", "pattern": "",
            "reason": act["reason"], "at": act["created_at"]}


def decision_panel(alerts: list[dict], actions: list[dict]) -> None:
    st.markdown("### Latest decision")
    d = latest_decision(alerts, actions)
    if not d:
        st.caption("No decision yet. Verdicts and kill/pause actions appear here.")
        return
    st.markdown(f'<div style="font-size:1.6rem;font-weight:600;line-height:1.4">{esc(d["action"])} '
                f'<span style="color:{MUTED};font-size:1rem;font-weight:400">{esc(d["agent"])}</span></div>', unsafe_allow_html=True)
    extra = "".join(f'{k} <b style="color:#E6EAF0">{esc(v)}</b> &nbsp;·&nbsp; ' for k, v in
                    (("Confidence", d["confidence"]), ("Pattern", d["pattern"])) if v)
    st.markdown(f'<div class="cs-cell" style="color:{MUTED}">{extra}Decided by <b style="color:#E6EAF0">{esc(d["source"])}</b>'
                f' &nbsp;·&nbsp; {esc(d["at"][11:19])}</div>', unsafe_allow_html=True)
    st.write(d["reason"])


def event_log(alerts: list[dict], actions: list[dict]) -> None:
    st.markdown("### Event log")
    rows = [(a["created_at"], a["agent"], a["rule"], a["message"], "") for a in alerts
            if a["rule"] not in ("sentinel_heartbeat", "brain_cost")]
    rows += [(a["created_at"], a["agent"], a["action"].lower(), a["reason"], a["actor"]) for a in actions]
    if not rows:
        st.caption("Nothing has happened yet.")
        return
    body = ""
    for at, agent, event, detail, by in sorted(rows, reverse=True)[:12]:
        cls = ("kill" + (" fresh" if age_seconds(at) < 6 else "")) if event == "kill" else ""
        body += (f'<tr class="{cls}"><td class="t">{esc(at[11:19])}</td><td>{esc(agent)}</td><td class="e">{esc(event)}</td>'
                 f'<td>{esc(detail)}</td><td style="color:{MUTED}">{esc(by)}</td></tr>')
    st.markdown('<table class="log"><tr><th>Time</th><th>Agent</th><th>Event</th><th>Detail</th><th>By</th></tr>'
                f'{body}</table>', unsafe_allow_html=True)


def demo_controls(agents: list[str]) -> None:
    with st.expander("Demo controls"):
        if not agents:
            st.caption("No agents yet.")
        for col, agent in zip(st.columns(max(len(agents), 1)), agents):
            col.button(f"Simulate rogue: {agent}", key=f"rogue_{agent}", on_click=send, args=(agent, "GO_ROGUE", "Demo: simulate rogue"))


@st.fragment(run_every=REFRESH)
def live() -> None:
    alerts, actions = store.recent_alerts(limit=500), store.recent_actions(limit=100)
    metrics = pd.DataFrame(store.recent_metrics(minutes=5))
    if metrics.empty:
        metrics = pd.DataFrame(columns=["agent", "created_at", "tokens_per_min", "calls_per_sec", "total_tokens",
                                         "token_budget", "memory_pct", "status"])
    else:
        metrics["created_at"] = pd.to_datetime(metrics["created_at"], utc=True, format="ISO8601")
    latest = metrics.sort_values("created_at").groupby("agent").tail(1).set_index("agent").sort_index()
    status_bar(alerts, latest)
    agents_table(metrics, latest)
    st.markdown('<div style="height:1.25rem"></div>', unsafe_allow_html=True)
    left, right = st.columns([3, 2], gap="large")
    with left:
        token_chart(metrics, actions)
    with right:
        decision_panel(alerts, actions)
    event_log(alerts, actions)
    demo_controls(list(latest.index))


live()
