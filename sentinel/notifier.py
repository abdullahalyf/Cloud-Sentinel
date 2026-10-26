"""
Notifier: tells a human chat channel when the sentinel KILLs or PAUSEs an agent.

POSTs {"content": msg, "text": msg} to WEBHOOK_URL — Discord reads "content", Slack reads
"text". Runs in a background thread: a slow or broken webhook never blocks the loop,
and failures are only logged. No WEBHOOK_URL → does nothing.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor

from shared.config import Settings

log = logging.getLogger("sentinel.notifier")


class Notifier:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="notify") if cfg.webhook_url else None

    def notify(self, agent: str, action: str, actor: str, reason: str) -> Future | None:
        if self.pool is None:
            return None
        text = f"🛡️ CloudSentinel: {action} {agent} (by {actor}) — {reason}"[:1900]
        return self.pool.submit(self._post, text)

    def _post(self, text: str) -> None:
        body = json.dumps({"content": text, "text": text}).encode()
        req = urllib.request.Request(self.cfg.webhook_url, data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "CloudSentinel"})
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.webhook_timeout_seconds) as resp:
                resp.read()
        except Exception as exc:  # network down, 4xx/5xx, bad URL…
            log.warning("webhook failed: %s", exc)

    def shutdown(self) -> None:
        if self.pool is not None:
            self.pool.shutdown(wait=False, cancel_futures=True)
