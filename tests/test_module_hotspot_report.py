import json

from tools import module_hotspot_report


def test_hotspot_baseline_regression_detection():
    rows = [(11, 1, 0, "src/a.py"), (3, 0, 0, "src/b.py")]
    assert module_hotspot_report.find_regressions(rows, {"src/a.py": 10, "src/b.py": 3}) == [("src/a.py", 11, 10)]


def test_write_and_load_baseline(tmp_path):
    path = tmp_path / "baseline.json"
    module_hotspot_report.write_baseline(path, [(5, 1, 0, "src/a.py")])
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["modules"]["src/a.py"] == 5
    assert module_hotspot_report.load_baseline(path) == {"src/a.py": 5}
