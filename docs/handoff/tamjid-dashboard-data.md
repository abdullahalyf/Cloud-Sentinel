# Dashboard data: Sentinel ONLINE/OFFLINE, brain verdict, brain cost, paused — Tamjid

কোনো contract বা table বদলায়নি। সব কিছু আগের মতোই `store.recent_alerts()`,
`store.recent_actions()` আর `store.recent_metrics()` থেকে আসে। শুধু নতুন একটা alert আসে:
`rule = "sentinel_heartbeat"` (`agent = "sentinel"`, `severity = "info"`), প্রতি ৫ সেকেন্ডে
(`HEARTBEAT_SECONDS`)।

**সাবধান:** heartbeat প্রতি ৫s-এ একটা alert লেখে। `recent_alerts(limit=30)` এখন প্রায় পুরোটাই
heartbeat হয়ে যাবে, তাই alerts table থেকে heartbeat বাদ দিন (নিচের Step 3) আর alert তুলুন
`limit=500` দিয়ে (~৪০ মিনিটের ইতিহাস)।

## Step 1 — helper functions
`dashboard/app.py`-তে `store = get_store()`-এর নিচে paste করুন। নতুন import শুধু `datetime`।

```python
from datetime import datetime, timezone

OFFLINE_AFTER_SECONDS = 15   # no heartbeat for this long = Sentinel OFFLINE


def _age_seconds(created_at: str) -> float:
    return (datetime.now(timezone.utc) - datetime.fromisoformat(created_at.replace("Z", "+00:00"))).total_seconds()


def sentinel_status(alerts: list[dict]) -> tuple[bool, float | None]:
    """(online, seconds since the last heartbeat). (False, None) if there was never one."""
    beats = [a for a in alerts if a["rule"] == "sentinel_heartbeat"]
    if not beats:
        return False, None
    age = min(_age_seconds(a["created_at"]) for a in beats)
    return age <= OFFLINE_AFTER_SECONDS, age


def latest_verdict(alerts: list[dict]) -> dict | None:
    """Newest brain verdict: {agent, source, text, created_at}. source = claude | gemini | fallback.
    text looks like 'KILL (80%, infinite_loop): Same prompt repeated 5x ...'."""
    verdicts = [a for a in alerts if a["rule"].endswith("_verdict")]
    if not verdicts:
        return None
    newest = max(verdicts, key=lambda a: a["created_at"])
    return {"agent": newest["agent"], "source": newest["rule"].removesuffix("_verdict"),
            "text": newest["message"], "created_at": newest["created_at"]}


def brain_cost(alerts: list[dict]) -> tuple[float, float] | None:
    """(spent_usd, saved_usd) from the newest 'brain_cost' alert, or None before the first one."""
    costs = [a for a in alerts if a["rule"] == "brain_cost"]
    if not costs:
        return None
    message = max(costs, key=lambda a: a["created_at"])["message"]
    values = dict(part.split("=") for part in message.rsplit("[", 1)[-1].rstrip("]").split() if "=" in part)
    return float(values["spent_usd"]), float(values["saved_usd"])


def paused_agents(latest) -> list[str]:
    """`latest` = the per-agent latest-metric DataFrame already built in live_panel()."""
    return [agent for agent, row in latest.iterrows() if row["status"] == "paused"]
```

## Step 2 — header strip (online, verdict, cost, paused)
`live_panel()`-এর শুরুতে `metrics`/`latest` বানানোর **পরে**, "top numbers"-এর আগে paste করুন।
`live_panel()`-এ `if metrics.empty: ... return` আছে; Sentinel OFFLINE দেখাতে চাইলে সেই
`return`-এর **আগেই** `alerts = ...` আর `online` অংশটুকু বসান।

```python
alerts = store.recent_alerts(limit=500)
online, age = sentinel_status(alerts)
if online:
    st.success(f"🟢 Sentinel ONLINE — last heartbeat {age:.0f}s ago")
elif age is None:
    st.error("🔴 Sentinel OFFLINE — no heartbeat yet. Start it:  `python -m sentinel --fake`")
else:
    st.error(f"🔴 Sentinel OFFLINE — last heartbeat {age:.0f}s ago (agents are NOT being guarded)")

verdict, cost, paused = latest_verdict(alerts), brain_cost(alerts), paused_agents(latest)
b1, b2, b3 = st.columns(3)
if verdict:
    b1.metric(f"Brain verdict ({verdict['source']}) — {verdict['agent']}", verdict["text"].split(":", 1)[0])
    b1.caption(verdict["text"].split(":", 1)[-1].strip())
else:
    b1.metric("Brain verdict", "none yet")
if cost:
    b2.metric("Brain cost vs saved", f"spent ${cost[0]:.4f} to save ${cost[1]:.2f}")
else:
    b2.metric("Brain cost vs saved", "spent $0.0000 to save $0.00")
b3.metric("Paused", len(paused))
if paused:
    b3.caption(", ".join(paused))
```

`latest` মানে app-এর বিদ্যমান `latest = metrics.sort_values("created_at").groupby("agent").tail(1).set_index("agent")`।
Paused agent-এর metric-এ `status == "paused"` থাকে (Pause/Resume বাটনের doc দেখুন)।

## Step 3 — alerts table থেকে heartbeat বাদ
`st.dataframe(pd.DataFrame(store.recent_alerts(limit=30)), ...)` লাইনটা বদলে:

```python
shown = [a for a in alerts if a["rule"] != "sentinel_heartbeat"][:30]
st.dataframe(pd.DataFrame(shown), hide_index=True, width="stretch")
```

(`alerts` যদি এই fragment-এর বাইরে হয়, `alerts = store.recent_alerts(limit=500)` আবার লিখুন।)

## যা দেখবেন
| কী | কবে |
|---|---|
| 🟢 ONLINE | sentinel চলছে, শেষ heartbeat ≤ 15s আগে |
| 🔴 OFFLINE | sentinel বন্ধ/মরে গেছে, বা ১৫s কোনো heartbeat নেই (Ctrl+C করে পরীক্ষা করুন) |
| Brain verdict | `KILL (80%, infinite_loop)` আর নিচে কারণ; `claude`/`gemini`/`fallback` source |
| Brain cost | `spent $0.0021 to save $1.40` (প্রথম kill/verdict-এর পরে) |
| Paused | PAUSE বাটনের পর সংখ্যা ও নাম |

## হাতে পরীক্ষা
```bash
python -m sentinel --fake --rogue-type paraphrase_loop     # terminal 1
streamlit run dashboard/app.py                             # terminal 2
```
২০ সেকেন্ড পর beta rogue হয়: verdict আর cost কার্ড ভরে যায়। terminal 1-এ Ctrl+C করুন:
~১৫s পর ড্যাশবোর্ড 🔴 OFFLINE দেখায়। আবার চালালে 🟢।
