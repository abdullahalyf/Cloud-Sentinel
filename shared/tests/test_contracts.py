import json
import sys
from pathlib import Path

from shared.contracts import Attr, CommandRow, MemoryRow, SpanRow, ToolCallRow, agent_view, load_json, prompt_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "telemetry" / "sdk"))


def test_sdk_attribute_names_match_contract():
    import cloudsentinel as cs

    pairs = {"OPERATION": Attr.OPERATION, "INPUT_TOKENS": Attr.INPUT_TOKENS, "OUTPUT_TOKENS": Attr.OUTPUT_TOKENS,
             "TOOL_NAME": Attr.TOOL_NAME, "CS_AGENT_ID": Attr.CS_AGENT_ID, "CS_PROMPT_PREVIEW": Attr.CS_PROMPT_PREVIEW,
             "CS_TASK_STATUS": Attr.CS_TASK_STATUS, "CS_TOOL_ARGS": Attr.CS_TOOL_ARGS, "REQUEST_MODEL": Attr.REQUEST_MODEL,
             "CS_NODE": Attr.CS_NODE, "CS_NODE_STEP": Attr.CS_NODE_STEP, "CS_NODE_FRAMEWORK": Attr.CS_NODE_FRAMEWORK,
             "CS_NODE_STATE_DELTA": Attr.CS_NODE_STATE_DELTA, "CS_NODE_NEXT": Attr.CS_NODE_NEXT}
    for name, value in pairs.items():
        assert getattr(cs, name) == value, name
    assert cs._prompt_hash("Hello  World") == prompt_hash("hello world")


def test_json_columns_are_serialized():
    assert json.loads(SpanRow("a", "chat", "x", tool_args={"k": 1}).to_row()["tool_args"]) == {"k": 1}
    assert json.loads(CommandRow("a", "PAUSE", {"x": 1}).to_row()["params"]) == {"x": 1}
    assert json.loads(MemoryRow("a", 1, {"m": "v"}).to_row()["content"]) == {"m": "v"}
    row = ToolCallRow("a", "t", {"amount": 5}, final_args={}).to_row()
    assert json.loads(row["args"]) == {"amount": 5} and row["final_args"] == "{}"


def test_load_json_is_safe():
    assert load_json("not json") == {} and load_json(None) == {} and load_json('{"a": 1}') == {"a": 1}


def test_agent_view_has_contract_keys():
    v = agent_view({"agent_id": "beta", "state": "paused"}, {"usd_per_min": 0.1, "tool_cycle": 1}, None)
    assert set(v) == {"agent_id", "display_name", "runtime", "state", "budget_usd", "spend_usd", "total_tokens",
                      "tokens_per_min", "usd_per_min", "calls_per_sec", "exact_repeats", "loop_score", "tool_cycle",
                      "memory_pct", "last_verdict", "updated_at"}
    assert v["tool_cycle"] is True and v["state"] == "paused"
