# Pause / Resume — Tamjid

`dashboard/app.py`-এর `live_panel()`-এ, existing `with col:` এবং
`if row["status"] != "killed":` block-এর ভিতরে paste করুন। Existing
`CommandRow`, `store`, `agent`, `row`, `st` ব্যবহার করে; নতুন import লাগে না।

```python
if row["status"] == "paused":
    if st.button("▶️ Resume", key=f"resume-{agent}"):
        store.insert_command(CommandRow(
            agent, "RESUME", "dashboard", "Resume after quarantine review"))
        st.toast(f"Resume command sent to {agent}")
else:
    if st.button("⏸️ Pause / Quarantine", key=f"pause-{agent}"):
        store.insert_command(CommandRow(
            agent, "PAUSE", "dashboard", "Manual quarantine for review"))
        st.toast(f"Pause command sent to {agent}")
```

Sentinel command চালায়; existing 2s refresh-এ status আপডেট হয়। Paused agent-এর
জন্য Simulate rogue লুকান/disable করুন; running count ও icon-এ paused আলাদা দেখান।
Emergency Kill রাখুন। PAUSE-এ total tokens থামে; RESUME-এ আবার বাড়ে—এভাবেই যাচাই করুন।
