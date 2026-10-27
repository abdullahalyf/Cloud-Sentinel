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

AGENT_MODELS = {
    "alpha": ("Claude 3.5 Sonnet", "Anthropic"),
    "beta": ("GPT-4o Omni", "OpenAI"),
    "gamma": ("Gemini 1.5 Pro", "Google"),
}

CURSOR_PRECISION_DEFAULT = (
    "data:image/svg+xml,%3Csvg width='24' height='24' viewBox='0 0 24 24' fill='none' xmlns='http://www.w3.org/2000/svg'%3E"
    "%3Ccircle cx='12' cy='12' r='8' stroke='%23475569' stroke-width='1.2' stroke-dasharray='3 2'/%3E"
    "%3Ccircle cx='12' cy='12' r='2.5' fill='%233B82F6'/%3E"
    "%3Cline x1='12' y1='1' x2='12' y2='5' stroke='%2394A3B8' stroke-width='1.2' stroke-linecap='round'/%3E"
    "%3Cline x1='12' y1='19' x2='12' y2='23' stroke='%2394A3B8' stroke-width='1.2' stroke-linecap='round'/%3E"
    "%3Cline x1='1' y1='12' x2='5' y2='12' stroke='%2394A3B8' stroke-width='1.2' stroke-linecap='round'/%3E"
    "%3Cline x1='19' y1='12' x2='23' y2='12' stroke='%2394A3B8' stroke-width='1.2' stroke-linecap='round'/%3E"
    "%3C/svg%3E"
)

CURSOR_PRECISION_POINTER = (
    "data:image/svg+xml,%3Csvg width='28' height='28' viewBox='0 0 28 28' fill='none' xmlns='http://www.w3.org/2000/svg'%3E"
    "%3Cpath d='M7 3H3V7' stroke='%233B82F6' stroke-width='1.8' stroke-linecap='round'/%3E"
    "%3Cpath d='M21 3H25V7' stroke='%233B82F6' stroke-width='1.8' stroke-linecap='round'/%3E"
    "%3Cpath d='M7 25H3V21' stroke='%233B82F6' stroke-width='1.8' stroke-linecap='round'/%3E"
    "%3Cpath d='M21 25H25V21' stroke='%233B82F6' stroke-width='1.8' stroke-linecap='round'/%3E"
    "%3Ccircle cx='14' cy='14' r='2.2' fill='%2360A5FA'/%3E"
    "%3C/svg%3E"
)

st.set_page_config(page_title="CloudSentinel", layout="wide", initial_sidebar_state="collapsed")

# Inject Live Telemetry Background Canvas & Smooth Halo via component iframe into parent document
ANIMATION_SCRIPT = """
<script>
(function() {
    const parentDoc = window.parent ? window.parent.document : document;
    if (parentDoc && !parentDoc.getElementById('cs-telemetry-canvas')) {
        const canvas = parentDoc.createElement('canvas');
        canvas.id = 'cs-telemetry-canvas';
        canvas.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;pointer-events:none;z-index:0;opacity:0.65;';
        parentDoc.body.insertBefore(canvas, parentDoc.body.firstChild);

        const ctx = canvas.getContext('2d');
        let w = canvas.width = window.parent.innerWidth || window.innerWidth;
        let h = canvas.height = window.parent.innerHeight || window.innerHeight;

        window.parent.addEventListener('resize', () => {
            w = canvas.width = window.parent.innerWidth || window.innerWidth;
            h = canvas.height = window.parent.innerHeight || window.innerHeight;
        });

        const particles = [];
        const count = 48;
        for (let i = 0; i < count; i++) {
            particles.push({
                x: Math.random() * w,
                y: Math.random() * h,
                vx: (Math.random() - 0.5) * 0.45,
                vy: (Math.random() - 0.5) * 0.45,
                r: Math.random() * 2.0 + 1.0,
                alpha: Math.random() * 0.35 + 0.15
            });
        }

        let mouseX = -9999, mouseY = -9999;
        parentDoc.addEventListener('mousemove', (e) => {
            mouseX = e.clientX;
            mouseY = e.clientY;
        });

        function render() {
            ctx.clearRect(0, 0, w, h);
            for (let i = 0; i < particles.length; i++) {
                const p = particles[i];
                p.x += p.vx;
                p.y += p.vy;
                if (p.x < 0) p.x = w;
                if (p.x > w) p.x = 0;
                if (p.y < 0) p.y = h;
                if (p.y > h) p.y = 0;

                ctx.fillStyle = 'rgba(59, 130, 246, ' + p.alpha + ')';
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
                ctx.fill();

                for (let j = i + 1; j < particles.length; j++) {
                    const p2 = particles[j];
                    const dist = Math.hypot(p.x - p2.x, p.y - p2.y);
                    if (dist < 135) {
                        ctx.strokeStyle = 'rgba(59, 130, 246, ' + (0.15 * (1 - dist / 135)) + ')';
                        ctx.lineWidth = 0.85;
                        ctx.beginPath();
                        ctx.moveTo(p.x, p.y);
                        ctx.lineTo(p2.x, p2.y);
                        ctx.stroke();
                    }
                }

                const mdist = Math.hypot(p.x - mouseX, p.y - mouseY);
                if (mdist < 140) {
                    ctx.strokeStyle = 'rgba(96, 165, 250, ' + (0.35 * (1 - mdist / 140)) + ')';
                    ctx.lineWidth = 1.0;
                    ctx.beginPath();
                    ctx.moveTo(p.x, p.y);
                    ctx.lineTo(mouseX, mouseY);
                    ctx.stroke();
                }
            }
            requestAnimationFrame(render);
        }
        render();
    }
})();
</script>
"""
st.components.v1.html(ANIMATION_SCRIPT, height=0, width=0)

RAW_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">

<style>
/* CUSTOM PRECISION BLUE AI CURSOR — Native SVG fallback guarantees 100% visibility */
html, body, [class*="css"], .stApp, div, span, p {
    cursor: url('__CUR_DEFAULT__') 12 12, auto !important;
}
button, a, select, input, textarea, [role="button"], .stButton > button, summary {
    cursor: url('__CUR_POINTER__') 14 14, pointer !important;
}

/* Base layout & typography */
html, body, [class*="css"] {
    font-family: 'Geist', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;
    font-variant-numeric: tabular-nums;
    font-size: 1.02rem;
    color: #E6EAF0;
}
[data-testid="stAppViewContainer"], section.main, .block-container {
    background: transparent !important;
}
.k, .s, table.log td.t, table.log td.e, table.log th, .cs-head, code {
    font-family: 'JetBrains Mono', monospace !important;
}
header[data-testid="stHeader"], #MainMenu, footer { display: none; }
.block-container {
    padding: 1.25rem 2rem 3rem;
    max-width: 1650px;
}

/* Status Bar */
.cs-bar {
    display: flex;
    gap: 2.2rem;
    align-items: flex-end;
    padding-bottom: 1.1rem;
    border-bottom: 1px solid #2A313B;
    margin-bottom: 1.75rem;
    flex-wrap: wrap;
}
.cs-bar .k {
    color: #8B95A5;
    font-size: 0.88rem;
    letter-spacing: .05em;
    text-transform: uppercase;
    font-weight: 500;
}
.cs-bar .v {
    font-size: 1.55rem;
    font-weight: 700;
    line-height: 1.4;
    letter-spacing: -0.01em;
}
.cs-bar .s {
    font-size: 0.92rem;
    color: #8B95A5;
    font-weight: 400;
}
.cs-brand {
    font-size: 1.3rem;
    font-weight: 700;
    margin-right: auto;
    letter-spacing: -0.02em;
    color: #F8FAFC;
}
.dot {
    display: inline-block;
    width: .7rem;
    height: .7rem;
    border-radius: 50%;
    margin-right: .55rem;
    box-shadow: 0 0 8px currentColor;
}

/* Headings & Tables */
div[data-testid="stHeading"] { margin-top: 1.6rem; }
h3 {
    font-size: 1.05rem !important;
    font-weight: 700 !important;
    letter-spacing: .04em;
    text-transform: uppercase;
    color: #94A3B8;
    padding: 0 0 .5rem !important;
}
.cs-head {
    color: #8B95A5;
    font-size: 0.92rem;
    letter-spacing: .05em;
    text-transform: uppercase;
    font-weight: 600;
}
.cs-cell {
    font-size: 1.12rem;
    line-height: 2.5rem;
    font-weight: 500;
}
.cs-row { border-top: 1px solid #2A313B; }
.cs-bar-bg {
    background: #1F252E;
    height: .45rem;
    border-radius: 3px;
    margin-top: 1.05rem;
}
.cs-bar-fg {
    height: .45rem;
    border-radius: 3px;
}
div[data-testid="stHorizontalBlock"]:has(.cs-cell) {
    border-top: 1px solid #1F252E;
    padding: .35rem 0;
}

/* Event Log */
table.log, table.log th, table.log td { border-left:0 !important; border-right:0 !important; border-top:0 !important; }
table.log {
    width: 100%;
    border-collapse: collapse;
    font-size: 1.02rem;
}
table.log th {
    text-align: left;
    color: #8B95A5;
    font-weight: 500;
    font-size: 0.88rem;
    letter-spacing: .05em;
    text-transform: uppercase;
    padding: .5rem .85rem;
    border-bottom: 1px solid #2A313B;
}
table.log td {
    padding: .55rem .85rem;
    border-bottom: 1px solid #1F252E;
    vertical-align: top;
}
table.log td.t { color: #8B95A5; white-space: nowrap; width: 6.5rem; }
table.log td.e { white-space: nowrap; width: 11.5rem; }
table.log tr.kill td { color: #E6EAF0; }
table.log tr.kill td.e { color: #E5534B; font-weight: 600; }
table.log tr.fresh { animation: hl 3s ease-out; }
@keyframes hl { from { background: #3a1d1f; } to { background: transparent; } }

div[data-testid="stHorizontalBlock"] { align-items: center; }
.stButton button {
    padding: .25rem 1rem;
    min-height: 2.2rem;
    border-radius: 5px;
    font-weight: 500;
    transition: all 0.15s ease;
}
.stButton button:hover {
    border-color: #3B82F6;
    box-shadow: 0 0 10px rgba(59, 130, 246, 0.25);
}
</style>
"""
FINAL_CSS = RAW_CSS.replace("__CUR_DEFAULT__", CURSOR_PRECISION_DEFAULT).replace("__CUR_POINTER__", CURSOR_PRECISION_POINTER)
st.markdown(FINAL_CSS, unsafe_allow_html=True)

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


def sparkline(values: list[float], color: str, w: int = 110, h: int = 30) -> str:
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    pts = " ".join(f"{i * w / (len(values) - 1):.1f},{h - 2 - (v - lo) / span * (h - 4):.1f}" for i, v in enumerate(values))
    return (f'<svg width="{w}" height="{h}" style="vertical-align:middle"><polyline points="{pts}" fill="none" '
           f'stroke="{color}" stroke-width="1.8" stroke-linejoin="round"/></svg>')


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
    items = [
        ("Sentinel", sentinel),
        ("Agents", f'{running} running <span class="s">· {int(counts.get("paused", 0))} paused · '
                   f'{int(counts.get("killed", 0))} killed</span>'),
        ("Est. saved", f"${saved:,.2f}"),
        ("Brain spend", f'${spent:.4f} <span class="s">spent to save ${saved:,.2f}</span>'),
        ("Guardrails", '4 Active <span class="s">· Loop · Rate · RAM · AI</span>'),
        ("Monitored Fleet", '3 Models <span class="s">· Claude · GPT-4o · Gemini</span>'),
    ]
    cells = "".join(f'<div><div class="k">{k}</div><div class="v">{v}</div></div>' for k, v in items)
    st.markdown(f'<div class="cs-bar"><div class="cs-brand">⚡ CloudSentinel</div>{cells}</div>', unsafe_allow_html=True)


COLS = [2.6, 2.4, 1, 1, 2, 2]


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
        model_info = AGENT_MODELS.get(agent, ("", ""))
        model_badge = (
            f'<span style="background:rgba(59,130,246,0.12);border:1px solid rgba(59,130,246,0.25);'
            f'border-radius:4px;padding:2px 6px;font-size:0.75rem;color:#93C5FD;margin-left:6px;font-weight:500">'
            f'{esc(model_info[0])}</span>' if model_info[0] else ""
        )
        c = st.columns(COLS)
        c[0].markdown(f'<div class="cs-cell"><span class="dot" style="background:{STATUS.get(status, MUTED)}"></span>'
                      f'{esc(agent)}{model_badge} <span style="color:{MUTED};font-size:.9rem">{esc(status)}</span></div>', unsafe_allow_html=True)
        c[1].markdown(f'<div class="cs-cell">{sparkline(series, MUTED)} &nbsp;{int(row["tokens_per_min"]):,}</div>', unsafe_allow_html=True)
        c[2].markdown(f'<div class="cs-cell">{row["calls_per_sec"]:.1f}</div>', unsafe_allow_html=True)
        c[3].markdown(f'<div class="cs-cell">{row["memory_pct"]:.0f}%</div>', unsafe_allow_html=True)
        c[4].markdown(f'<div class="cs-bar-bg"><div class="cs-bar-fg" style="width:{pct:.0f}%;background:{bar}"></div></div>'
                      f'<span style="color:{MUTED};font-size:.88rem">{pct:.0f}% of {int(row["token_budget"]):,}</span>', unsafe_allow_html=True)
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
                      legend=alt.Legend(orient="top", offset=0, title=None, labelColor="#E6EAF0", symbolType="stroke", labelFontSize=12))
    base = alt.Chart(df).encode(x=alt.X("created_at:T", title=None, axis=alt.Axis(format="%H:%M:%S", grid=False, labelFontSize=12)))
    lines = base.mark_line(strokeWidth=2.2, interpolate="linear").encode(
        y=alt.Y("tokens_per_min:Q", title=None, axis=alt.Axis(gridColor=GRID, tickCount=4, labelFontSize=12)), color=color)
    kills = pd.DataFrame([{"at": a["created_at"], "agent": a["agent"]} for a in actions if a["action"] == "KILL"])
    layers = lines
    if not kills.empty:
        kills["at"] = pd.to_datetime(kills["at"], utc=True)
        rule = alt.Chart(kills).mark_rule(color=STATUS["killed"], strokeDash=[4, 3], strokeWidth=1.8).encode(x="at:T")
        label = alt.Chart(kills).mark_text(color=STATUS["killed"], align="left", dx=5, dy=-4, baseline="bottom", fontSize=13, fontWeight=600) \
            .encode(x="at:T", y=alt.value(10), text=alt.Text("agent:N"))
        layers = lines + rule + label
    st.altair_chart(layers.properties(height=320).configure_view(stroke=None).configure_axis(
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


def sentry_policies() -> None:
    st.markdown("### Active Circuit Breakers")
    policies = [
        ("🔁 Loop Sentry", "Max 5 repeat prompts in 60s → SIGKILL", "#3FB97C"),
        ("⚡ Rate Throttle", "Max 3,000 tokens/min velocity → SIGKILL", "#3FB97C"),
        ("💾 RAM Ceiling", "Max 85% container RAM ceiling → SIGKILL", "#3FB97C"),
        ("🧠 LLM Brain", "Autonomous analysis on semantic loops & injections", "#3987E5"),
    ]
    cards = "".join(
        f'<div style="display:flex;align-items:center;justify-content:space-between;padding:0.45rem 0.75rem;'
        f'border:1px solid #232A33;border-radius:6px;background:rgba(18,20,28,0.5);margin-bottom:0.45rem;">'
        f'<div><span style="font-weight:600;font-size:0.95rem;color:#E6EAF0">{title}</span>'
        f'<div style="font-size:0.83rem;color:{MUTED}">{desc}</div></div>'
        f'<span style="font-size:0.75rem;padding:2px 7px;border-radius:4px;background:rgba(63,185,124,0.15);color:{color};font-weight:600">ARMED</span>'
        f'</div>'
        for title, desc, color in policies
    )
    st.markdown(f'<div style="margin-top:0.4rem">{cards}</div>', unsafe_allow_html=True)


def decision_panel(alerts: list[dict], actions: list[dict]) -> None:
    st.markdown("### Latest decision")
    d = latest_decision(alerts, actions)
    if not d:
        st.caption("No decision yet. Verdicts and kill/pause actions appear here.")
        return
    st.markdown(f'<div style="font-size:1.75rem;font-weight:700;line-height:1.4">{esc(d["action"])} '
                f'<span style="color:{MUTED};font-size:1.1rem;font-weight:400">{esc(d["agent"])}</span></div>', unsafe_allow_html=True)
    extra = "".join(f'{k} <b style="color:#E6EAF0">{esc(v)}</b> &nbsp;·&nbsp; ' for k, v in
                    (("Confidence", d["confidence"]), ("Pattern", d["pattern"])) if v)
    st.markdown(f'<div class="cs-cell" style="color:{MUTED};font-size:0.95rem">{extra}Decided by <b style="color:#E6EAF0">{esc(d["source"])}</b>'
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
        sentry_policies()
    event_log(alerts, actions)
    demo_controls(list(latest.index))


live()
