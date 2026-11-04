"""
ShopBD refund agent built with LangGraph, monitored by CloudSentinel through ONE callback.   Owner: Fojle.

    pip install -e "telemetry/sdk[langgraph]"
    python -m telemetry.collector                          # terminal 1 (spans → store)
    python -m brain --fake                                 # terminal 2 (brain + API)
    CS_AGENT_ID=lg-refund python telemetry/examples/langgraph_refund_agent.py --rogue-after 20

The graph (a real recursive loop is possible — that is the point):

    START → classify → lookup_order ─┬─ status ok ───────────────→ decide → refund → END
                           ▲         └─ status error + memory says "retry" → retry ─┐
                           └──────────────────────────────────────────────────────┘

Rogue mode (after --rogue-after seconds, or when /tmp/go_rogue exists): the orders API fails for order
4471 and the agent's memory holds the bad belief "retry until success" → lookup_order ↔ retry forever,
with a paraphrased prompt every time. CloudSentinel sees the loop (semantic loop + failing tool cycle),
pauses the agent (between nodes — no container needed), a human fixes the memory, resume → it moves on.
The refund node asks the tool gate first: 50,000 BDT is held for a human.

LLM: an offline simulated chat model by default (no key, costs nothing). --claude uses Claude via the
anthropic SDK (model from CLAUDE_MODEL, default claude-haiku-5-5).
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Optional, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk"))  # use the local SDK without installing
import cloudsentinel as cs  # noqa: E402
from cloudsentinel.adapters.langgraph import CloudSentinelCallback, guard  # noqa: E402
from langchain_core.language_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, BaseMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langgraph.errors import GraphRecursionError  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

FLAG_FILE = Path("/tmp/go_rogue")
BAD_ORDER = 4471
BAD_BELIEF = {f"order_{BAD_ORDER}": "orders API returned 500 - retry until success"}
RETRY_WORDS = ["Retry: fetch order {o} status", "Get the status of order #{o} again", "Look up where order {o} stands",
               "Try again: query the orders API for {o}", "Re-check order #{o} and report its state",
               "Once more: pull the current status for order {o}", "See if order {o} has shipped yet"]
STEP_DELAY = float(os.getenv("STEP_DELAY", "0.5"))   # seconds per loop iteration (keeps the demo watchable)
TASK_GAP = float(os.getenv("TASK_GAP", "4"))         # seconds between healthy tasks (~0.5 LLM calls/s, under the soft limit)


# ── a chat model: offline simulator, or Claude ──────────────────────────────
class SimChat(BaseChatModel):
    """Deterministic fake LLM with realistic token usage (priced as model "sim")."""
    model_name: str = "sim"

    @property
    def _llm_type(self) -> str:
        return "sim"

    def _generate(self, messages: list[BaseMessage], stop: Optional[list[str]] = None, run_manager: Any = None,
                  **kw: Any) -> ChatResult:
        prompt = str(messages[-1].content)
        tin = 250 + len(prompt) // 4        # ~4 characters per token, plus a system prompt
        tout = random.randint(40, 120)
        msg = AIMessage(content=f"[sim] ok: {prompt[:60]}",
                        usage_metadata={"input_tokens": tin, "output_tokens": tout, "total_tokens": tin + tout})
        return ChatResult(generations=[ChatGeneration(message=msg)])


class ClaudeChat(BaseChatModel):
    """Minimal Claude chat model via the anthropic SDK (no extra LangChain package needed)."""
    model_name: str = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")

    @property
    def _llm_type(self) -> str:
        return "anthropic"

    def _generate(self, messages: list[BaseMessage], stop: Optional[list[str]] = None, run_manager: Any = None,
                  **kw: Any) -> ChatResult:
        import anthropic

        r = anthropic.Anthropic().messages.create(model=self.model_name, max_tokens=200, messages=[
            {"role": "user", "content": str(m.content)} for m in messages[-1:]])
        text = next((b.text for b in r.content if b.type == "text"), "")
        msg = AIMessage(content=text, usage_metadata={"input_tokens": r.usage.input_tokens,
                                                      "output_tokens": r.usage.output_tokens,
                                                      "total_tokens": r.usage.input_tokens + r.usage.output_tokens})
        return ChatResult(generations=[ChatGeneration(message=msg)])


# ── tools (wrapped with guard() → every call goes through the CloudSentinel tool gate) ─────
ROGUE = {"on": False}


@tool
def orders_api(order_id: int) -> str:
    """Return the shipping status of an order."""
    if ROGUE["on"] and order_id == BAD_ORDER:
        raise RuntimeError("orders API returned 500")
    return random.choice(["shipped", "delivered", "packed"])


@tool
def issue_refund(order_id: int, amount: int) -> str:
    """Refund an order (amount in BDT)."""
    return f"refunded {amount} BDT for order {order_id}"


TOOLS = {"orders_api": guard(orders_api),
         "issue_refund": guard(issue_refund, value_usd=lambda a: round(float(a.get("amount", 0)) / 122, 2),
                               fail_closed=True)}   # money moves → never run it if CloudSentinel is unreachable


# ── the graph ───────────────────────────────────────────────────────────────
class State(TypedDict, total=False):
    order_id: int
    intent: str
    status: str
    attempts: int
    amount: int
    answer: str


def build_graph(llm: BaseChatModel):
    def classify(s: State) -> dict:
        llm.invoke(f"Customer writes about order {s['order_id']}: classify the intent (refund / status)")
        return {"intent": "refund", "attempts": 0}

    def lookup_order(s: State) -> dict:
        try:
            status = TOOLS["orders_api"].invoke({"order_id": s["order_id"]})
        except cs.ToolDenied:
            status = "error: blocked by CloudSentinel"
        except Exception as exc:  # the API failed: the router decides what to do next
            status = f"error: {exc}"
        return {"status": status, "attempts": s.get("attempts", 0) + 1}

    def retry(s: State) -> dict:
        time.sleep(STEP_DELAY)
        llm.invoke(random.choice(RETRY_WORDS).format(o=s["order_id"]))
        return {"answer": f"retrying ({s.get('attempts', 0)})"}

    def decide(s: State) -> dict:
        if str(s.get("status", "")).startswith("error"):
            return {"amount": 0, "answer": f"order {s['order_id']} skipped (memory says move on)"}
        llm.invoke(f"Decide a refund amount in BDT for order {s['order_id']} ({s['status']})")
        return {"amount": 50_000 if s["order_id"] == BAD_ORDER else random.choice([300, 800, 1200])}

    def refund(s: State) -> dict:
        if not s.get("amount"):
            return {}
        try:
            return {"answer": TOOLS["issue_refund"].invoke({"order_id": s["order_id"], "amount": s["amount"]})}
        except cs.ToolDenied as exc:
            return {"answer": f"refund not done: {exc}"}

    def after_lookup(s: State) -> str:
        if not str(s.get("status", "")).startswith("error"):
            return "decide"
        belief = str(cs.memory.get().get(f"order_{s['order_id']}", ""))
        return "retry" if "retry" in belief.lower() else "decide"   # a human fix of the memory ends the loop

    g = StateGraph(State)
    for name, fn in [("classify", classify), ("lookup_order", lookup_order), ("retry", retry), ("decide", decide),
                     ("refund", refund)]:
        g.add_node(name, fn)
    g.add_edge(START, "classify")
    g.add_edge("classify", "lookup_order")
    g.add_conditional_edges("lookup_order", after_lookup, ["retry", "decide"])
    g.add_edge("retry", "lookup_order")
    g.add_edge("decide", "refund")
    g.add_edge("refund", END)
    return g.compile()


def run_once(app, order_id: int, recursion_limit: int = 500) -> dict:
    callback = CloudSentinelCallback()
    try:
        return app.invoke({"order_id": order_id}, config={"callbacks": [callback], "recursion_limit": recursion_limit})
    except GraphRecursionError:
        return {"answer": "gave up: recursion limit"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rogue-after", type=float, default=float(os.getenv("ROGUE_AFTER", "0") or 0),
                   help="go rogue after N seconds (0 = only when /tmp/go_rogue exists)")
    p.add_argument("--claude", action="store_true", help="use Claude instead of the offline simulator")
    p.add_argument("--tasks", type=int, default=0, help="stop after N tasks (0 = run forever)")
    args = p.parse_args()

    cs.init(agent_id=os.getenv("CS_AGENT_ID", "lg-refund"), runtime=os.getenv("CS_RUNTIME", "local"))
    app = build_graph(ClaudeChat() if args.claude else SimChat())
    started, done, healed = time.time(), 0, False
    while not args.tasks or done < args.tasks:
        timer = args.rogue_after > 0 and time.time() - started > args.rogue_after and not healed
        rogue_now = FLAG_FILE.exists() or timer   # after a heal, only a new GO_ROGUE flag makes it rogue again
        if rogue_now and not ROGUE["on"]:
            ROGUE["on"] = True
            cs.memory.set({**cs.memory.get(), **BAD_BELIEF}, reason="orders API failed: retry until success")
            print(f"[{cs._s.agent_id}] rogue: order {BAD_ORDER} will loop", flush=True)
        order = BAD_ORDER if ROGUE["on"] else random.randint(4400, 4600)
        try:
            result = run_once(app, order)
        except cs.AgentKilled as exc:
            print(f"[{cs._s.agent_id}] {exc}", flush=True)
            break
        print(f"[{cs._s.agent_id}] order {order}: {result.get('answer', result.get('status'))}", flush=True)
        if order == BAD_ORDER and "retry" not in str(cs.memory.get().get(f"order_{BAD_ORDER}", "")).lower():
            ROGUE["on"], healed = False, True   # healed: memory was fixed, back to normal work
            FLAG_FILE.unlink(missing_ok=True)
        done += 1
        cs.flush()
        time.sleep(TASK_GAP)
    cs.flush()


if __name__ == "__main__":
    main()
