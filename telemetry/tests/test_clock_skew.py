import json
import time

from telemetry.collector.normalize import SKEW_KEY, normalize_otlp_json
from telemetry.tests.test_normalize import make_span, payload

START = 1730000000.0      # make_span() starts here and lasts 0.5 s


def one(span, now=None):
    rows = normalize_otlp_json(payload([span]), now)
    assert len(rows) == 1
    return rows[0]


def test_a_span_within_30_s_of_the_collector_clock_is_left_alone():
    r = one(make_span(), now=START + 10)
    assert r.start_ts == START and r.end_ts == START + 0.5 and r.duration_ms == 500.0
    assert r.detail == "{}"


def test_exactly_30_s_is_not_skewed():
    r = one(make_span(), now=START + 30)
    assert r.start_ts == START and r.detail == "{}"


def test_an_agent_clock_behind_the_collector_uses_the_receive_time():
    now = START + 31
    r = one(make_span(), now=now)
    assert r.start_ts == now
    assert abs(r.end_ts - (now + 0.5)) < 1e-6
    assert r.duration_ms == 500.0
    assert json.loads(r.detail)[SKEW_KEY] == -31.0


def test_an_agent_clock_ahead_of_the_collector_uses_the_receive_time():
    now = START - 3600
    r = one(make_span(), now=now)
    assert r.start_ts == now and r.duration_ms == 500.0
    assert json.loads(r.detail)[SKEW_KEY] == 3600.0


def test_graph_node_detail_keeps_its_keys_and_gets_the_skew():
    span = make_span(name="graph_node n", attrs={"gen_ai.operation.name": "graph_node",
                                                 "cloudsentinel.node.name": "n"})
    d = json.loads(one(span, now=START + 500).detail)
    assert d["node"] == "n" and d[SKEW_KEY] == -500.0


def test_the_skew_key_name_is_the_one_in_the_task():
    assert SKEW_KEY == "cloudsentinel.clock_skew_s"


def test_without_now_the_collectors_real_clock_is_used():
    before = time.time()
    r = one(make_span())                 # the 2024 timestamp is far from the real clock
    assert before <= r.start_ts <= time.time() + 1
    assert SKEW_KEY in json.loads(r.detail)