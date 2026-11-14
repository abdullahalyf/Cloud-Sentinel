from telemetry.collector.normalize import normalize_otlp_json


def make_span(name="chat claude-haiku-5-5", attrs=None, status_code=0):
    """Helper: one OTLP-JSON span. attrs = {"key": value} (str / int / float)."""
    def val(v):
        return {"intValue": str(v)} if isinstance(v, int) else {"doubleValue": v} if isinstance(v, float) else {"stringValue": v}
    return {"traceId": "0af7651916cd43dd8448eb211c80319c", "spanId": "b7ad6b7169203331", "name": name,
            "startTimeUnixNano": "1730000000000000000", "endTimeUnixNano": "1730000000500000000",
            "attributes": [{"key": k, "value": val(v)} for k, v in (attrs or {}).items()],
            "status": {"code": status_code}}


def one_row(span, resource=None):
    res = [{"key": k, "value": {"stringValue": v}} for k, v in (resource or {"service.name": "beta"}).items()]
    payload = {"resourceSpans": [{"resource": {"attributes": res}, "scopeSpans": [{"spans": [span]}]}]}
    rows = normalize_otlp_json(payload)
    assert len(rows) == 1
    return rows[0]


def test_chat_span_gives_operation_model_and_tokens():
    r = one_row(make_span(attrs={
        "gen_ai.operation.name": "chat", "gen_ai.request.model": "claude-haiku-5-5",
        "gen_ai.usage.input_tokens": 1000, "gen_ai.usage.output_tokens": 200}))
    assert r.operation == "chat"
    assert r.model == "claude-haiku-5-5"
    assert (r.input_tokens, r.output_tokens) == (1000, 200)


def test_execute_tool_span_gives_tool_name():
    r = one_row(make_span(name="execute_tool orders_api", attrs={
        "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "orders_api"}))
    assert r.operation == "execute_tool"
    assert r.tool_name == "orders_api"


def test_status_code_2_is_error_and_code_0_is_ok():
    assert one_row(make_span(status_code=2)).status == "error"
    assert one_row(make_span(status_code=0)).status == "ok"


def test_agent_id_falls_back_to_service_name():
    r = one_row(make_span(attrs={"gen_ai.operation.name": "chat"}), resource={"service.name": "gamma"})
    assert r.agent_id == "gamma"


def test_cost_is_positive_for_claude_haiku():
    r = one_row(make_span(attrs={
        "gen_ai.operation.name": "chat", "gen_ai.request.model": "claude-haiku-5-5",
        "gen_ai.usage.input_tokens": 1000, "gen_ai.usage.output_tokens": 200}))
    assert r.cost_usd > 0