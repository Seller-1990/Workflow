"""An empty startup activity set must not imply target ownership."""
from _force_stop_fakes import _make_engine


def test_force_stop_unknown_startup_target_only_cleans_that_record(monkeypatch):
    eng, calls = _make_engine(monkeypatch, running=True, active_ids=(), current_id=None)
    eng.force_stop_run(200)
    assert eng._cancelled is False, "没有实际活动 ID 时不得猜测历史记录属于当前运行"
    assert [args[0] for args, _kwargs in calls["db_cleanup"]] == [200]
