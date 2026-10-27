from shared.contracts import AgentEvent


def test_roundtrip():
    e = AgentEvent("alpha", "llm_call", 100.0, tokens_in=10, tokens_out=5, prompt="hi")
    back = AgentEvent.parse_line(e.to_line())
    assert back == e
    assert back.tokens == 15


def test_ignores_normal_logs_and_garbage():
    assert AgentEvent.parse_line("hello world") is None
    assert AgentEvent.parse_line("{not json") is None
    assert AgentEvent.parse_line('{"type": "llm_call"}') is None          # missing "cs": 1
    assert AgentEvent.parse_line('{"cs": 1, "tokens_in": "abc"}') is None  # bad number


def test_same_prompt_same_hash():
    a = AgentEvent("a", "llm_call", prompt="Retry fetch order ")
    b = AgentEvent("a", "llm_call", prompt="retry fetch order")
    assert a.prompt_hash == b.prompt_hash


def test_pause_resume_contracts():
    from typing import get_args
    from shared.contracts import ActionRow, AgentStatus, CommandRow, CommandType

    for command in ('PAUSE', 'RESUME'):
        assert command in get_args(CommandType)
        assert CommandRow('beta', command).to_row()['command'] == command
    assert 'paused' in get_args(AgentStatus)
    assert ActionRow('beta', 'PAUSE', 'human', 'Quarantine').to_row()['action'] == 'PAUSE'
