from mvp.early_start import splice_plan


def _plan():
    return {
        "mode": "compare",
        "product": "Kolanut",
        "personas": [
            {"name": "A", "favors": "https://rival1.com/"},
            {"name": "B", "favors": "product"},
            {"name": "C", "favors": "https://rival2.com/"},
            {"name": "D", "favors": "product"},
            {"name": "E", "favors": "https://rival3.com/"},
        ],
        "task_specs": [
            {"prompt": "Identify at-risk customer accounts", "favors": "https://rival1.com/"},
            {"prompt": "Draft outreach emails", "favors": "product"},
            {"prompt": "Compare pricing for 50 accounts", "favors": "https://rival2.com/"},
        ],
    }


def test_splice_puts_starter_first_and_keeps_counts():
    starter = {"persona": {"name": "S", "favors": "product"}, "task": "Identify at-risk customer accounts quickly"}
    out = splice_plan(_plan(), starter)
    assert [p["name"] for p in out["personas"]] == ["S", "A", "C", "D", "E"]
    # The similar task is replaced, not duplicated.
    assert out["tasks"][0] == "Identify at-risk customer accounts quickly"
    assert len(out["tasks"]) == 3
    assert "Identify at-risk customer accounts" not in out["tasks"]


def test_splice_replaces_product_task_when_nothing_similar():
    starter = {"persona": {"name": "S", "favors": "product"}, "task": "Build a churn dashboard"}
    out = splice_plan(_plan(), starter)
    assert out["tasks"] == ["Build a churn dashboard", "Identify at-risk customer accounts", "Compare pricing for 50 accounts"]
