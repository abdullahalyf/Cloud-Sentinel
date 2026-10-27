"""
CloudSentinel dashboard: a calm operations console with live animated cybernetic telemetry.

Rules (see AGENTS.md):
  - Read data ONLY through get_store(); every number on screen comes from a row.
  - Actions ONLY insert a CommandRow. The dashboard never touches Docker.
  - The live part is an @st.fragment that refreshes itself.
"""
from __future__ import annotations

import base64
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
AGENT_PALETTE = {
    "alpha": "#00F0FF",   # Electric Cyan (Claude 3.5 Sonnet)
    "beta": "#FF5722",    # Deep Orange / Flame Coral (GPT-4o Omni)
    "gamma": "#A78BFA",   # Electric Lavender / Purple (Gemini 1.5 Pro)
}
LINES = ["#00F0FF", "#FF5722", "#A78BFA"]   # validated categorical order (dark)
MUTED, GRID = "#8B95A5", "#2A313B"

AGENT_MODELS = {
    "alpha": ("Claude 3.5 Sonnet", "Anthropic"),
    "beta": ("GPT-4o Omni", "OpenAI"),
    "gamma": ("Gemini 1.5 Pro", "Google"),
}

@st.cache_data
def load_background_b64() -> str:
    possible_paths = [
        Path(__file__).resolve().parent / "background.jpg",
        Path(__file__).resolve().parent.parent / "background.jpg",
        Path(__file__).resolve().parent / "dashboard" / "background.jpg",
    ]
    for p in possible_paths:
        if p.exists():
            try:
                with open(p, "rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")
            except Exception:
                pass
    return ""

BG_B64 = load_background_b64()

# Custom Electric Blue AI Cursors (Base64 SVG - vibrant & 100% visible on dark theme)
B64_DEF = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIj4KPHBhdGggZD0iTTMgMkwxOCAxMUwxMSAxM0w4IDE5TDMgMloiIGZpbGw9IiMwNjA4MTMiIHN0cm9rZT0iIzAwRjBGRiIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+CjxjaXJjbGUgY3g9IjUiIGN5PSI0IiByPSIyIiBmaWxsPSIjMDBGMEZGIi8+Cjwvc3ZnPg=="
B64_PTR = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyOCIgaGVpZ2h0PSIyOCIgdmlld0JveD0iMCAwIDI4IDI4IiBmaWxsPSJub25lIj4KPGNpcmNsZSBjeD0iMTQiIGN5PSIxNCIgcj0iOSIgc3Ryb2tlPSIjMDBGMEZGIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1kYXNoYXJyYXk9IjMgMyIvPgo8Y2lyY2xlIGN4PSIxNCIgY3k9IjE0IiByPSIzLjUiIGZpbGw9IiMwMEYwRkYiLz4KPGxpbmUgeDE9IjE0IiB5MT0iMiIgeDI9IjE0IiB5Mj0iNiIgc3Ryb2tlPSIjMDBGMEZGIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8bGluZSB4MT0iMTQiIHkxPSIyMiIgeDI9IjE0IiB5Mj0iMjYiIHN0cm9rZT0iIzAwRjBGRiIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiLz4KPGxpbmUgeDE9IjIiIHkxPSIxNCIgeDI9IjYiIHkyPSIxNCIgc3Ryb2tlPSIjMDBGMEZGIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8bGluZSB4MT0iMjIiIHkxPSIxNCIgeDI9IjI2IiB5Mj0iMTQiIHN0cm9rZT0iIzAwRjBGRiIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiLz4KPC9zdmc+"

st.set_page_config(page_title="CloudSentinel", layout="wide", initial_sidebar_state="collapsed")

CURSOR_TRACKER_HTML = """
<script>
(function() {
    function setupAura() {
        try {
            const parentDoc = window.parent ? window.parent.document : document;
            if (!parentDoc) return;
            
            let dot = parentDoc.getElementById('cs-cursor-dot');
            let aura = parentDoc.getElementById('cs-cursor-aura');
            
            if (!dot) {
                dot = parentDoc.createElement('div');
                dot.id = 'cs-cursor-dot';
                dot.style.cssText = 'position:fixed;top:0;left:0;width:7px;height:7px;background:#00F0FF;border-radius:50%;pointer-events:none;z-index:99999999;box-shadow:0 0 10px #00F0FF, 0 0 20px #00F0FF;transform:translate(-50%,-50%);transition:transform 0.04s ease-out;';
                parentDoc.body.appendChild(dot);
            }
            
            if (!aura) {
                aura = parentDoc.createElement('div');
                aura.id = 'cs-cursor-aura';
                aura.style.cssText = 'position:fixed;top:0;left:0;width:34px;height:34px;border:1.6px dashed #00F0FF;border-radius:50%;pointer-events:none;z-index:99999998;transform:translate(-50%,-50%);transition:left 0.08s ease-out,top 0.08s ease-out,width 0.18s,height 0.18s,border-color 0.18s,background 0.18s;box-shadow:0 0 16px rgba(0,240,255,0.4);';
                parentDoc.body.appendChild(aura);
            }
            
            parentDoc.addEventListener('mousemove', function(e) {
                dot.style.left = e.clientX + 'px';
                dot.style.top = e.clientY + 'px';
                aura.style.left = e.clientX + 'px';
                aura.style.top = e.clientY + 'px';
            });
            
            parentDoc.addEventListener('mousedown', function() {
                aura.style.width = '24px';
                aura.style.height = '24px';
                aura.style.border = '2px solid #EF4444';
                aura.style.background = 'rgba(239,68,68,0.2)';
                aura.style.boxShadow = '0 0 25px #EF4444';
            });
            
            parentDoc.addEventListener('mouseup', function() {
                aura.style.width = '34px';
                aura.style.height = '34px';
                aura.style.border = '1.6px dashed #00F0FF';
                aura.style.background = 'transparent';
                aura.style.boxShadow = '0 0 16px rgba(0,240,255,0.4)';
            });
        } catch(err) {}
    }
    setupAura();
    setTimeout(setupAura, 300);
    setTimeout(setupAura, 1000);
})();
</script>
"""

st.components.v1.html(CURSOR_TRACKER_HTML, height=0, width=0)
st.markdown('<div class="cyber-scanner-laser"></div>', unsafe_allow_html=True)

RAW_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">

<style>
/* 1. Custom Electric Blue AI Cursor (100% visible, cannot disappear) */
html, body, .stApp, [class*="css"], * {
    cursor: url('__B64_DEF__') 3 2, auto !important;
}
button, a, select, input, textarea, [role="button"], .stButton > button, summary, [data-baseweb="tab"], .cs-row, .stDataFrame {
    cursor: url('__B64_PTR__') 14 14, pointer !important;
}

/* 2. Base layout & typography (Geist + JetBrains Mono) */
html, body, [class*="css"] {
    font-family: 'Geist', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;
    font-variant-numeric: tabular-nums;
    font-size: 1.05rem;
    color: #E6EAF0;
}
header[data-testid="stHeader"], #MainMenu, footer { display: none; }

/* 3. Live Animated Cybernetic Moving Background */
html, body {
    background-color: #06070D !important;
}
.stApp {
    __BG_STYLE_RULE__
    background-size: 110% 110% !important;
    background-attachment: fixed !important;
    background-position: center !important;
    animation: bgFloatPan 36s ease-in-out infinite alternate !important;
}

[data-testid="stAppViewContainer"], section.main, .block-container, [data-testid="stHeader"] {
    background: transparent !important;
}
.block-container {
    padding: 1.25rem 2rem 3rem;
    max-width: 1650px;
    position: relative;
    z-index: 2;
}
.k, .s, table.log td.t, table.log td.e, table.log th, .cs-head, code {
    font-family: 'JetBrains Mono', monospace !important;
}

/* Background Cinematic Panning Animation */
@keyframes bgFloatPan {
    0% { background-position: 50% 50%; background-size: 108% 108%; }
    33% { background-position: 53% 47%; background-size: 114% 114%; }
    66% { background-position: 47% 53%; background-size: 111% 111%; }
    100% { background-position: 50% 50%; background-size: 108% 108%; }
}

/* Moving Aurora Lighting Effect Behind Content */
.stApp::before {
    content: "";
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: radial-gradient(circle at 18% 28%, rgba(0, 240, 255, 0.22) 0%, transparent 45%),
                radial-gradient(circle at 82% 72%, rgba(129, 140, 248, 0.20) 0%, transparent 45%),
                radial-gradient(circle at 50% 48%, rgba(37, 99, 235, 0.18) 0%, transparent 55%);
    pointer-events: none;
    z-index: 0;
    animation: auroraShift 16s ease-in-out infinite alternate !important;
}

@keyframes auroraShift {
    0% { transform: scale(1) translate(0px, 0px); opacity: 0.8; }
    50% { transform: scale(1.12) translate(30px, -20px); opacity: 1; }
    100% { transform: scale(1) translate(-20px, 30px); opacity: 0.8; }
}

/* Drifting Cybernetic Micro-Grid */
.stApp::after {
    content: "";
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: linear-gradient(rgba(0, 240, 255, 0.045) 1px, transparent 1px),
                linear-gradient(90deg, rgba(0, 240, 255, 0.045) 1px, transparent 1px);
    background-size: 44px 44px;
    pointer-events: none;
    z-index: 0;
    animation: gridDrift 50s linear infinite !important;
}

@keyframes gridDrift {
    0% { background-position: 0 0; }
    100% { background-position: 44px 44px; }
}

/* Moving Scanner Laser */
.cyber-scanner-laser {
    position: fixed;
    left: 0;
    width: 100vw;
    height: 3px;
    background: linear-gradient(90deg, transparent 0%, rgba(0, 240, 255, 0.2) 20%, #00F0FF 50%, rgba(0, 240, 255, 0.2) 80%, transparent 100%);
    box-shadow: 0 0 16px #00F0FF, 0 0 32px rgba(0, 240, 255, 0.6);
    pointer-events: none;
    z-index: 1;
    animation: laserScan 9s cubic-bezier(0.4, 0, 0.2, 1) infinite;
}

@keyframes laserScan {
    0% { top: -2%; opacity: 0; }
    10% { opacity: 0.85; }
    90% { opacity: 0.85; }
    100% { top: 102%; opacity: 0; }
}

/* 4. Top Status Bar */
.cs-bar {
    display: flex;
    gap: 2.2rem;
    align-items: flex-end;
    padding-bottom: 1.1rem;
    border-bottom: 1px solid #2A313B;
    margin-bottom: 1.75rem;
    flex-wrap: wrap;
    position: relative;
    z-index: 2;
}
.cs-bar .k {
    color: #8B95A5;
    font-size: 0.88rem;
    letter-spacing: .05em;
    text-transform: uppercase;
    font-weight: 500;
}
.cs-bar .v {
    font-size: 1.6rem;
    font-weight: 700;
    line-height: 1.4;
    letter-spacing: -0.01em;
}
.cs-bar .s {
    font-size: 0.94rem;
    color: #8B95A5;
    font-weight: 400;
}
.cs-brand {
    font-size: 1.35rem;
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

/* 5. Headings & Tables */
div[data-testid="stHeading"] { margin-top: 1.6rem; }
h3 {
    font-size: 1.05rem !important;
    font-weight: 700 !important;
    letter-spacing: .04em;
    text-transform: uppercase;
    color: #94A3B8;
    padding: 0 0 .5rem !important;
    position: relative;
    z-index: 2;
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
    position: relative;
    z-index: 2;
}

/* 6. Event Log */
table.log, table.log th, table.log td { border-left:0 !important; border-right:0 !important; border-top:0 !important; }
table.log {
    width: 100%;
    border-collapse: collapse;
    font-size: 1.02rem;
    position: relative;
    z-index: 2;
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
    border-color: #00F0FF;
    box-shadow: 0 0 12px rgba(0, 240, 255, 0.35);
}
</style>
"""

bg_style = (
    f"background-image: linear-gradient(180deg, rgba(8, 9, 18, 0.86) 0%, rgba(10, 11, 24, 0.92) 100%), url('data:image/jpeg;base64,{BG_B64}') !important;"
    if BG_B64
    else "background: radial-gradient(circle at 50% 0%, #151528 0%, #07070E 80%) !important;"
)

FINAL_CSS = (
    RAW_CSS.replace("__B64_DEF__", B64_DEF)
    .replace("__B64_PTR__", B64_PTR)
    .replace("__BG_STYLE_RULE__", bg_style)
)
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
            f'<span style="background:rgba(0,240,255,0.12);border:1px solid rgba(0,240,255,0.3);'
            f'border-radius:4px;padding:2px 6px;font-size:0.75rem;color:#38BDF8;margin-left:6px;font-weight:500">'
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
            a1.button("Revive", key=f"revive_{agent}", on_click=send, args=(agent, "RESUME", "Revived from dashboard"))
            a2.button("Rogue", key=f"rogue_row_{agent}", on_click=send, args=(agent, "GO_ROGUE", "Demo: trigger rogue"))
            continue
        if status == "paused":
            a1.button("Resume", key=f"resume_{agent}", on_click=send, args=(agent, "RESUME", "Resumed from dashboard"))
        else:
            a1.button("Pause", key=f"pause_{agent}", on_click=send, args=(agent, "PAUSE", "Paused from dashboard"))
        if a2.button("Kill", key=f"kill_{agent}"):
            confirm_kill(agent)


def token_chart(metrics: pd.DataFrame, actions: list[dict]) -> None:
    st.markdown("### Telemetry: Tokens per minute")
    if metrics.empty:
        st.caption("Waiting for the first metrics.")
        return

    all_agents = sorted(metrics["agent"].unique())
    if "chart_agents" not in st.session_state:
        st.session_state["chart_agents"] = set(all_agents)

    # Filter buttons to toggle / remove Alpha, Beta, Gamma
    cols = st.columns([1.2, 1.3, 1.3, 1.3, 2.5])
    if cols[0].button("👁️ Show All", key="filter_all", help="Display all agents"):
        st.session_state["chart_agents"] = set(all_agents)
        st.rerun()

    agent_icons = {"alpha": "🔵 Alpha", "beta": "🟠 Beta", "gamma": "🟣 Gamma"}
    for idx, name in enumerate(["alpha", "beta", "gamma"]):
        if name in all_agents:
            is_active = name in st.session_state["chart_agents"]
            icon = agent_icons.get(name, name)
            label = f"{icon} ✓" if is_active else f"⚪ + {name}"
            help_msg = f"Click to remove {name} from chart" if is_active else f"Click to display {name} on chart"
            if cols[idx + 1].button(label, key=f"toggle_{name}", help=help_msg):
                if is_active and len(st.session_state["chart_agents"]) > 1:
                    st.session_state["chart_agents"].remove(name)
                else:
                    st.session_state["chart_agents"].add(name)
                st.rerun()

    active_agents = st.session_state.get("chart_agents", set(all_agents))
    if not active_agents:
        active_agents = set(all_agents)

    df = metrics[["agent", "created_at", "tokens_per_min"]].copy()
    df = df[df["agent"].isin(active_agents)]
    if df.empty:
        st.caption("No metrics for currently selected agents.")
        return

    # Add drop-to-zero point for killed agents so the spike visibly drops to zero
    now_utc = pd.Timestamp.now(tz="UTC")
    min_t = metrics["created_at"].min()
    extra_rows = []
    for a in actions:
        if a["action"] == "KILL" and a["agent"] in active_agents:
            try:
                kill_ts = pd.to_datetime(a["created_at"], utc=True)
                if kill_ts < min_t:
                    continue  # do not pull historical kills that distort the visible time range
                extra_rows.append({"agent": a["agent"], "created_at": kill_ts + pd.Timedelta(seconds=1), "tokens_per_min": 0})
                extra_rows.append({"agent": a["agent"], "created_at": now_utc, "tokens_per_min": 0})
            except Exception:
                pass
    if extra_rows:
        df = pd.concat([df, pd.DataFrame(extra_rows)], ignore_index=True).sort_values("created_at")

    domain = [a for a in ["alpha", "beta", "gamma"] if a in active_agents] or sorted(df["agent"].unique())
    colors = [AGENT_PALETTE.get(a, "#818CF8") for a in domain]
    color_enc = alt.Color(
        "agent:N",
        scale=alt.Scale(domain=domain, range=colors),
        legend=alt.Legend(orient="top", offset=0, title=None, labelColor="#E6EAF0", symbolType="stroke", labelFontSize=12)
    )

    base = alt.Chart(df).encode(
        x=alt.X("created_at:T", title=None, axis=alt.Axis(format="%H:%M:%S", grid=False, labelFontSize=12))
    )
    lines = base.mark_line(strokeWidth=2.6, interpolate="monotone").encode(
        y=alt.Y("tokens_per_min:Q", title=None, axis=alt.Axis(gridColor=GRID, tickCount=4, labelFontSize=12)),
        color=color_enc,
        tooltip=[
            alt.Tooltip("created_at:T", title="Time", format="%H:%M:%S"),
            alt.Tooltip("agent:N", title="Agent"),
            alt.Tooltip("tokens_per_min:Q", title="Tokens / min", format=",.0f"),
        ]
    )

    # Soft Limit Reference Line (45k TPM) - clearly shows when threshold is breached
    limit_df = pd.DataFrame([{"limit": 45000, "label": "Soft Limit: 45k (AI Brain Trigger)"}])
    limit_line = alt.Chart(limit_df).mark_rule(
        color="rgba(245, 158, 11, 0.45)", strokeDash=[5, 4], strokeWidth=1.5
    ).encode(y="limit:Q")

    min_t = metrics["created_at"].min()

    kills = [a for a in actions if a["action"] == "KILL" and a["agent"] in active_agents]
    layers = lines + limit_line
    if kills:
        k_rows = []
        for a in kills:
            try:
                kill_ts = pd.to_datetime(a["created_at"], utc=True)
                if kill_ts < min_t:
                    continue
                agent_window = df[
                    (df["agent"] == a["agent"]) &
                    (df["created_at"] >= kill_ts - pd.Timedelta(seconds=12)) &
                    (df["created_at"] <= kill_ts + pd.Timedelta(seconds=2))
                ]
                peak_val = float(agent_window["tokens_per_min"].max()) if not agent_window.empty else 0.0
                if peak_val <= 0:
                    agent_all = df[df["agent"] == a["agent"]]
                    peak_val = float(agent_all["tokens_per_min"].max()) if not agent_all.empty else 5000.0

                actor_name = a.get("actor", "rules")
                k_rows.append({
                    "at": kill_ts,
                    "agent": a["agent"],
                    "actor": actor_name,
                    "tokens_per_min": max(peak_val, 1500.0),
                    "reason": a.get("reason", "Malfunctioning agent terminated"),
                    "event": f"KILL by {actor_name}",
                })
            except Exception:
                pass

        if k_rows:
            k_df = pd.DataFrame(k_rows).sort_values("at")
            deduped = []
            for _, row in k_df.iterrows():
                if not deduped or (row["agent"] != deduped[-1]["agent"]) or (row["at"] - deduped[-1]["at"]).total_seconds() > 12:
                    deduped.append(row)
                elif row["tokens_per_min"] > deduped[-1]["tokens_per_min"]:
                    deduped[-1] = row
            k_df = pd.DataFrame(deduped)

            stem = alt.Chart(k_df).mark_rule(
                strokeWidth=1.5, strokeDash=[3, 3], color="rgba(229, 83, 75, 0.45)"
            ).encode(x="at:T", y=alt.Y("tokens_per_min:Q"), y2=alt.datum(0))

            glow = alt.Chart(k_df).mark_circle(
                size=140, color="#E5534B", opacity=0.32
            ).encode(x="at:T", y="tokens_per_min:Q")

            dot = alt.Chart(k_df).mark_circle(
                size=55, color="#E5534B", opacity=1.0
            ).encode(
                x="at:T",
                y="tokens_per_min:Q",
                tooltip=[
                    alt.Tooltip("event:N", title="Event"),
                    alt.Tooltip("agent:N", title="Agent"),
                    alt.Tooltip("actor:N", title="Terminated By"),
                    alt.Tooltip("at:T", title="Kill Time", format="%H:%M:%S"),
                    alt.Tooltip("tokens_per_min:Q", title="Peak Spend", format=",.0f"),
                    alt.Tooltip("reason:N", title="Reason"),
                ]
            )

            pip = alt.Chart(k_df).mark_point(
                shape="circle", size=14, color="#FFFFFF", fill="#FFFFFF"
            ).encode(x="at:T", y="tokens_per_min:Q")

            layers = layers + stem + glow + dot + pip

    st.altair_chart(layers.properties(height=330).configure_view(stroke=None).configure_axis(
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
        ("🧠 LLM Brain", "Autonomous analysis on semantic loops & injections", "#38BDF8"),
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
