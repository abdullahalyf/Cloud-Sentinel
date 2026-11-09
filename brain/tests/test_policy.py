from brain.policy import Policy


def test_default_file_rules():
    p = Policy.load("brain/policies.yaml")
    assert p.decide_tool("issue_refund", {"amount": 50000})[0] == "approval"
    assert p.decide_tool("issue_refund", {"amount": 500})[0] == "allow"
    assert p.decide_tool("delete_customer", {})[0] == "deny"
    assert p.budget_for("delta") == 0.5 and p.budget_for("alpha") == 0.5


def test_first_match_wins_and_contains():
    p = Policy.from_dict({"tools": [{"match": "send_*", "action": "deny", "when": {"arg": "to", "op": "contains", "value": "@evil"}},
                                    {"match": "send_*", "action": "allow"}]})
    assert p.decide_tool("send_email", {"to": "a@evil.com"})[0] == "deny"
    assert p.decide_tool("send_email", {"to": "a@good.com"})[0] == "allow"


def test_bad_types_and_missing_file_are_safe(tmp_path):
    p = Policy.from_dict({"tools": [{"match": "*", "action": "deny", "when": {"arg": "n", "op": "gt", "value": 5}}]})
    assert p.decide_tool("x", {"n": "not a number"})[0] == "allow"
    assert Policy.load(str(tmp_path / "nope.yaml"), 0.7).budget_usd == 0.7
    bad = tmp_path / "bad.yaml"
    bad.write_text("tools: [unclosed")
    assert Policy.load(str(bad)).tools == []
