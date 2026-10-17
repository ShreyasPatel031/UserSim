from mvp import android_study as st

CFG = {
    "title": "T",
    "apps": [{"name": "A", "package": "a"}, {"name": "B", "package": "b"}],
    "personas": [{"name": "P1", "role": "r", "bio": "b"}, {"name": "P2", "role": "r", "bio": "b"}],
    "tasks": ["t1", "t2"],
}


def _row(app, persona, task, score, level="in_product", friction=0):
    return {"app": app, "persona": persona, "task": task, "steps": 3,
            "score": {"score": score, "level": level, "friction": friction, "reason": "x"}}


def test_cells_cover_every_persona_task_app_with_app_innermost():
    c = st.cells(CFG)
    assert len(c) == 8 and c[0] == (0, 0, 0) and c[1] == (0, 0, 1)


def test_summarize_and_report():
    rows = [_row("A", "P1", "t1", 8), _row("A", "P2", "t1", 4, "clear_evidence", 2), _row("B", "P1", "t1", 1, "wall_or_nothing", 3)]
    s = st.summarize(CFG, rows)
    assert s["A"]["mean_score"] == 6.0 and s["A"]["done_in_app"] == 1 and s["A"]["mean_friction"] == 1.0
    assert s["B"]["by_task"] == {"t1": 1.0, "t2": None}
    html = st.report_html(CFG, rows, s)
    assert "Scorecard" in html and "P2" in html


def test_cell_task_forbids_purchases():
    assert "Never start a purchase" in st.cell_task(CFG["personas"][0], "t1", "A")
