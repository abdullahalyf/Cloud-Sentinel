"""
CloudSentinel dashboard: a calm operations console with live animated cybernetic telemetry.

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
LINES = ["#00F0FF", "#D95926", "#818CF8"]   # validated categorical order (dark)
MUTED, GRID = "#8B95A5", "#2A313B"

AGENT_MODELS = {
    "alpha": ("Claude 3.5 Sonnet", "Anthropic"),
    "beta": ("GPT-4o Omni", "OpenAI"),
    "gamma": ("Gemini 1.5 Pro", "Google"),
}

B64_DEF = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij4KPGNpcmNsZSBjeD0iMTIiIGN5PSIxMiIgcj0iOCIgc3Ryb2tlPSIjNDc1NTY5IiBzdHJva2Utd2lkdGg9IjEuMiIgc3Ryb2tlLWRhc2hhcnJheT0iMyAyIiBmaWxsPSJub25lIi8+CjxjaXJjbGUgY3g9IjEyIiBjeT0iMTIiIHI9IjIuNSIgZmlsbD0iIzNCODJGNiIvPgo8bGluZSB4MT0iMTIiIHkxPSIxIiB4Mj0iMTIiIHkyPSI1IiBzdHJva2U9IiM5NEEzQjgiIHN0cm9rZS13aWR0aD0iMS4yIiBzdHJva2UtbGluZWNhcD0icm91bmQiLz4KPGxpbmUgeDE9IjEyIiB5MT0iMTkiIHgyPSIxMiIgeTI9IjIzIiBzdHJva2U9IiM5NEEzQjgiIHN0cm9rZS13aWR0aD0iMS4yIiBzdHJva2UtbGluZWNhcD0icm91bmQiLz4KPGxpbmUgeDE9IjEiIHkxPSIxMiIgeDI9IjUiIHkyPSIxMiIgc3Ryb2tlPSIjOTRBM0I4IiBzdHJva2Utd2lkdGg9IjEuMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+CjxsaW5lIHgxPSIxOSIgeTE9IjEyIiB4Mj0iMjMiIHkyPSIxMiIgc3Ryb2tlPSIjOTRBM0I4IiBzdHJva2Utd2lkdGg9IjEuMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+Cjwvc3ZnPg=="
B64_PTR = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyOCIgaGVpZ2h0PSIyOCIgdmlld0JveD0iMCAwIDI4IDI4Ij4KPHBhdGggZD0iTTcgM0gzVjciIHN0cm9rZT0iIzNCODJGNiIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIGZpbGw9Im5vbmUiLz4KPHBhdGggZD0iTTIxIDNIMjVWNyIgc3Ryb2tlPSIjM0I4MkY2IiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgZmlsbD0ibm9uZSIvPgo8cGF0aCBkPSJNNyAyNUgzVjIxIiBzdHJva2U9IiMzQjgyRjYiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBmaWxsPSJub25lIi8+CjxwYXRoIGQ9Ik0yMSAyNUgyNVYyMSIgc3Ryb2tlPSIjM0I4MkY2IiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgZmlsbD0ibm9uZSIvPgo8Y2lyY2xlIGN4PSIxNCIgY3k9IjE0IiByPSIyLjUiIGZpbGw9IiM2MEE1RkEiLz4KPC9zdmc+"

st.set_page_config(page_title="CloudSentinel", layout="wide", initial_sidebar_state="collapsed")

# -----------------------------------------------------------------------------
# LIVE ANIMATED BACKGROUND & ELECTRIC BLUE AI CURSOR OVERLAY
# -----------------------------------------------------------------------------
LIVE_VISUALS_MARKUP = """
<div id="cs-live-ambient-aurora">
    <div class="aurora-orb-cyan"></div>
    <div class="aurora-orb-violet"></div>
    <div class="aurora-orb-blue"></div>
    <div class="cyber-grid-stream"></div>
    <div class="cyber-scanner-laser"></div>
</div>

<script>
(function() {
    function initVisuals() {
        const targetDocuments = [];
        try { targetDocuments.push(document); } catch(e) {}
        try {
            if (window.parent && window.parent.document && window.parent.document !== document) {
                targetDocuments.push(window.parent.document);
            }
        } catch(e) {}

        targetDocuments.forEach(doc => {
            // 1. Permanently remove normal OS mouse cursor
            if (!doc.getElementById('cs-cursor-kill-style')) {
                const s = doc.createElement('style');
                s.id = 'cs-cursor-kill-style';
                s.innerHTML = `
                    *, *::before, *::after, html, body, div, button, a, input, select, textarea, [role="button"], iframe {
                        cursor: none !important;
                    }
                `;
                doc.head.appendChild(s);
            }

            // 2. Setup Live Neural Canvas
            if (!doc.getElementById('cs-neural-canvas')) {
                const canvas = doc.createElement('canvas');
                canvas.id = 'cs-neural-canvas';
                canvas.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;pointer-events:none;z-index:1;opacity:0.8;';
                doc.body.insertBefore(canvas, doc.body.firstChild);

                const ctx = canvas.getContext('2d');
                let w = canvas.width = window.innerWidth;
                let h = canvas.height = window.innerHeight;

                window.addEventListener('resize', () => {
                    w = canvas.width = window.innerWidth;
                    h = canvas.height = window.innerHeight;
                });

                const particles = [];
                const count = 55;
                for (let i = 0; i < count; i++) {
                    particles.push({
                        x: Math.random() * w,
                        y: Math.random() * h,
                        vx: (Math.random() - 0.5) * 0.95,
                        vy: (Math.random() - 0.5) * 0.95,
                        radius: Math.random() * 2.2 + 1.2,
                        color: Math.random() > 0.45 ? '#00F0FF' : '#818CF8'
                    });
                }

                let mouseX = -1000, mouseY = -1000;
                doc.addEventListener('mousemove', e => {
                    mouseX = e.clientX;
                    mouseY = e.clientY;
                });

                let pulseRadius = 0;
                function draw() {
                    ctx.clearRect(0, 0, w, h);

                    // Expanding radar pulse from center
                    pulseRadius += 0.8;
                    if (pulseRadius > Math.max(w, h)) pulseRadius = 0;
                    ctx.beginPath();
                    ctx.arc(w / 2, h / 2, pulseRadius, 0, Math.PI * 2);
                    ctx.strokeStyle = 'rgba(0, 240, 255, ' + Math.max(0, 0.15 * (1 - pulseRadius / Math.max(w, h))) + ')';
                    ctx.lineWidth = 1.2;
                    ctx.stroke();

                    // Particles & Connections
                    for (let i = 0; i < particles.length; i++) {
                        const p = particles[i];
                        p.x += p.vx;
                        p.y += p.vy;
                        if (p.x < 0 || p.x > w) p.vx *= -1;
                        if (p.y < 0 || p.y > h) p.vy *= -1;

                        ctx.beginPath();
                        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
                        ctx.fillStyle = p.color;
                        ctx.shadowBlur = 9;
                        ctx.shadowColor = p.color;
                        ctx.fill();
                        ctx.shadowBlur = 0;

                        // Inter-particle constellation lines
                        for (let j = i + 1; j < particles.length; j++) {
                            const p2 = particles[j];
                            const dx = p.x - p2.x;
                            const dy = p.y - p2.y;
                            const dist = Math.sqrt(dx * dx + dy * dy);
                            if (dist < 125) {
                                ctx.beginPath();
                                ctx.moveTo(p.x, p.y);
                                ctx.lineTo(p2.x, p2.y);
                                const alpha = (1 - dist / 125) * 0.35;
                                ctx.strokeStyle = p.color === '#00F0FF'
                                    ? 'rgba(0, 240, 255, ' + alpha + ')'
                                    : 'rgba(129, 140, 248, ' + alpha + ')';
                                ctx.lineWidth = 1;
                                ctx.stroke();
                            }
                        }

                        // Live Mouse Tethering (Electric Blue Beams)
                        const mdx = p.x - mouseX;
                        const mdy = p.y - mouseY;
                        const mdist = Math.sqrt(mdx * mdx + mdy * mdy);
                        if (mdist < 155) {
                            ctx.beginPath();
                            ctx.moveTo(p.x, p.y);
                            ctx.lineTo(mouseX, mouseY);
                            ctx.strokeStyle = 'rgba(0, 240, 255, ' + ((1 - mdist / 155) * 0.6) + ')';
                            ctx.lineWidth = 1.4;
                            ctx.stroke();
                        }
                    }
                    requestAnimationFrame(draw);
                }
                draw();
            }

            // 3. Setup Custom Electric Blue AI Mouse Cursor
            if (!doc.getElementById('cs-ai-mouse-cursor')) {
                const cur = doc.createElement('div');
                cur.id = 'cs-ai-mouse-cursor';
                cur.style.cssText = 'position:fixed;top:0;left:0;pointer-events:none;z-index:999999999;transition:opacity 0.2s ease;';
                cur.innerHTML = `
                    <div id="cs-ai-dot" style="position:fixed;width:7px;height:7px;background:#00F0FF;border-radius:50%;transform:translate(-50%,-50%);box-shadow:0 0 10px #00F0FF, 0 0 20px #00F0FF;pointer-events:none;transition:background 0.15s ease;"></div>
                    <div id="cs-ai-hud" style="position:fixed;width:34px;height:34px;border:1.6px dashed rgba(0, 240, 255, 0.8);border-radius:50%;transform:translate(-50%,-50%);pointer-events:none;box-shadow:0 0 16px rgba(0, 240, 255, 0.4);transition:width 0.18s ease-out, height 0.18s ease-out, border 0.18s, background 0.18s, box-shadow 0.18s;">
                        <div style="position:absolute;top:-4px;left:50%;width:2px;height:6px;background:#00F0FF;transform:translateX(-50%);"></div>
                        <div style="position:absolute;bottom:-4px;left:50%;width:2px;height:6px;background:#00F0FF;transform:translateX(-50%);"></div>
                        <div style="position:absolute;left:-4px;top:50%;width:6px;height:2px;background:#00F0FF;transform:translateY(-50%);"></div>
                        <div style="position:absolute;right:-4px;top:50%;width:6px;height:2px;background:#00F0FF;transform:translateY(-50%);"></div>
                        <div id="cs-ai-tag" style="position:absolute;top:40px;left:50%;transform:translateX(-50%);font-family:monospace;font-size:8px;font-weight:700;color:#00F0FF;letter-spacing:1px;white-space:nowrap;text-shadow:0 0 6px #00F0FF;opacity:0.85;">AI // TARGET</div>
                    </div>
                `;
                doc.body.appendChild(cur);

                const dot = cur.querySelector('#cs-ai-dot');
                const hud = cur.querySelector('#cs-ai-hud');
                const tag = cur.querySelector('#cs-ai-tag');

                let targetX = -200, targetY = -200;
                let currentX = -200, currentY = -200;

                doc.addEventListener('mousemove', e => {
                    cur.style.opacity = '1';
                    targetX = e.clientX;
                    targetY = e.clientY;
                    dot.style.left = targetX + 'px';
                    dot.style.top = targetY + 'px';

                    // Check hover on interactive target
                    const el = doc.elementFromPoint(e.clientX, e.clientY);
                    const isInteractive = el && (
                        el.closest('button') || el.closest('a') || el.closest('.cs-bar') ||
                        el.closest('[role="button"]') || el.closest('select') || el.closest('input') ||
                        el.closest('[data-baseweb="tab"]')
                    );

                    if (isInteractive) {
                        hud.style.width = '48px';
                        hud.style.height = '48px';
                        hud.style.border = '2px solid #00F0FF';
                        hud.style.background = 'rgba(0, 240, 255, 0.12)';
                        hud.style.boxShadow = '0 0 25px rgba(0, 240, 255, 0.65)';
                        if (tag) {
                            tag.innerText = 'AI // LOCKED';
                            tag.style.color = '#38BDF8';
                        }
                    } else {
                        hud.style.width = '34px';
                        hud.style.height = '34px';
                        hud.style.border = '1.6px dashed rgba(0, 240, 255, 0.8)';
                        hud.style.background = 'transparent';
                        hud.style.boxShadow = '0 0 16px rgba(0, 240, 255, 0.4)';
                        if (tag) {
                            tag.innerText = 'AI // ACTIVE';
                            tag.style.color = '#00F0FF';
                        }
                    }
                });

                doc.addEventListener('mousedown', () => {
                    hud.style.transform = 'translate(-50%,-50%) scale(0.7)';
                    hud.style.boxShadow = '0 0 35px #00F0FF';
                });

                doc.addEventListener('mouseup', () => {
                    hud.style.transform = 'translate(-50%,-50%) scale(1)';
                });

                function loop() {
                    currentX += (targetX - currentX) * 0.24;
                    currentY += (targetY - currentY) * 0.24;
                    hud.style.left = currentX + 'px';
                    hud.style.top = currentY + 'px';
                    requestAnimationFrame(loop);
                }
                loop();
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initVisuals);
    } else {
        initVisuals();
    }
})();
</script>
"""

st.html(LIVE_VISUALS_MARKUP)
st.components.v1.html(LIVE_VISUALS_MARKUP, height=0, width=0)

RAW_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">

<style>
/* 1. Base64 SVG Custom Mouse Cursor Fallback */
html, body, [class*="css"], .stApp, div, span, p {
    cursor: url('__B64_DEF__') 12 12, crosshair !important;
}
button, a, select, input, textarea, [role="button"], .stButton > button, summary {
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
[data-testid="stAppViewContainer"], section.main, .block-container {
    background: transparent !important;
}
.block-container {
    padding: 1.25rem 2rem 3rem;
    max-width: 1650px;
}
.k, .s, table.log td.t, table.log td.e, table.log th, .cs-head, code {
    font-family: 'JetBrains Mono', monospace !important;
}

/* 3. Live Animated Cybernetic Aurora Background */
#cs-live-ambient-aurora {
    position: fixed;
    top: 0; left: 0; width: 100vw; height: 100vh;
    pointer-events: none;
    z-index: 0;
    overflow: hidden;
    background: radial-gradient(circle at 50% 0%, #111126 0%, #06070D 85%);
}
.aurora-orb-cyan {
    position: absolute;
    width: 650px; height: 650px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(0, 240, 255, 0.22) 0%, rgba(0, 240, 255, 0.04) 50%, transparent 70%);
    filter: blur(55px);
    animation: orbFloat1 20s ease-in-out infinite alternate;
}
.aurora-orb-violet {
    position: absolute;
    width: 750px; height: 750px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(139, 92, 246, 0.20) 0%, rgba(99, 102, 241, 0.05) 50%, transparent 70%);
    filter: blur(65px);
    animation: orbFloat2 26s ease-in-out infinite alternate;
}
.aurora-orb-blue {
    position: absolute;
    width: 580px; height: 580px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(37, 99, 235, 0.18) 0%, rgba(16, 185, 129, 0.05) 50%, transparent 70%);
    filter: blur(50px);
    animation: orbFloat3 18s ease-in-out infinite alternate;
}
@keyframes orbFloat1 {
    0% { transform: translate(-10%, -10%) scale(1); }
    50% { transform: translate(45vw, 25vh) scale(1.15); }
    100% { transform: translate(15vw, 65vh) scale(0.95); }
}
@keyframes orbFloat2 {
    0% { transform: translate(65vw, 55vh) scale(0.9); }
    50% { transform: translate(25vw, 15vh) scale(1.2); }
    100% { transform: translate(75vw, -5vh) scale(1); }
}
@keyframes orbFloat3 {
    0% { transform: translate(30vw, 80vh) scale(1.1); }
    50% { transform: translate(60vw, 30vh) scale(0.85); }
    100% { transform: translate(-5vw, 35vh) scale(1.05); }
}
.cyber-grid-stream {
    position: absolute;
    top: 0; left: 0; width: 100%; height: 100%;
    background-image: 
        linear-gradient(rgba(0, 240, 255, 0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0, 240, 255, 0.04) 1px, transparent 1px);
    background-size: 44px 44px;
    animation: cyberGridTravel 35s linear infinite;
}
@keyframes cyberGridTravel {
    0% { background-position: 0 0; }
    100% { background-position: 44px 44px; }
}
.cyber-scanner-laser {
    position: absolute;
    top: -20px; left: 0; width: 100%; height: 2px;
    background: linear-gradient(90deg, transparent 0%, rgba(0, 240, 255, 0.2) 25%, #00F0FF 50%, rgba(0, 240, 255, 0.2) 75%, transparent 100%);
    box-shadow: 0 0 16px #00F0FF, 0 0 32px rgba(0, 240, 255, 0.6);
    animation: scannerDownSweep 9s ease-in-out infinite;
    opacity: 0.75;
}
@keyframes scannerDownSweep {
    0% { top: -20px; opacity: 0; }
    10% { opacity: 0.8; }
    90% { opacity: 0.8; }
    100% { top: 105vh; opacity: 0; }
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

FINAL_CSS = RAW_CSS.replace("__B64_DEF__", B64_DEF).replace("__B64_PTR__", B64_PTR)
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
