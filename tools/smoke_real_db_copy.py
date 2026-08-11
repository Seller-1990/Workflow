# -*- coding: utf-8 -*-
"""6.0.0 真实库副本冒烟(重建版):隔离副本上验证 schema 升级与核心 CRUD。"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).name == "_smoke_copy.py" else Path.cwd()
# 脚本位于项目根时直接使用
sys.path.insert(0, str(Path.cwd() / "src"))
sys.path.insert(0, str(Path.cwd()))

REAL_DB = Path(os.environ["LOCALAPPDATA"]) / "工作流管理" / "data" / "workflows.db"

tmp = Path(tempfile.mkdtemp(prefix="wf_smoke_"))
(tmp / "data").mkdir(parents=True)
copy = tmp / "data" / "workflows.db"
shutil.copy2(REAL_DB, copy)
print(f"[1] 副本就绪: {copy}")

os.environ["WORKFLOW_APP_DATA_DIR"] = str(tmp)
import config  # noqa: E402
assert config.DATABASE_PATH.resolve() == copy.resolve(), "DATABASE_PATH 未指向副本"
print(f"[2] DATABASE_PATH 隔离正确: {config.DATABASE_PATH}")

import database  # noqa: E402
database.cleanup_session()
database.init_db()
applied = database._get_applied_versions(database.get_engine())
assert 10 in applied and 11 in applied, f"迁移未应用完: {applied}"
print(f"[3] schema 升级完成, 已应用版本: {sorted(applied)}")

with database.get_engine().connect() as conn:
    from sqlalchemy import text
    wf_count = conn.execute(text("SELECT COUNT(*) FROM workflows")).scalar()
    step_count = conn.execute(text("SELECT COUNT(*) FROM steps")).scalar()
    wh_count = conn.execute(text("SELECT COUNT(*) FROM webhook_configs")).scalar()
    notify_ok = conn.execute(text(
        "SELECT COUNT(*) FROM workflows WHERE json_extract(notify_config, '$.webhook_id') IS NOT NULL"
    )).scalar()
    risky_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(workflows)")).fetchall()]
    has_risky = all(c in risky_cols for c in
                    ("risky_paths_review_required", "risky_paths_revision", "risky_paths_confirmed_digest"))
print(f"[4] 工作流={wf_count} 步骤={step_count} webhook={wh_count} 绑定通知={notify_ok} 风险列={has_risky}")
assert wf_count == 4 and step_count >= 60 and wh_count == 1 and notify_ok >= 2
assert has_risky

new_wf = database.create_workflow("冒烟临时工作流", description="smoke")
new_wf_id = new_wf.id
database.create_step(new_wf_id, "冒烟步骤", step_type="python", script_path="smoke.py", order=1)
database.delete_workflow(new_wf_id)
gone = database.get_workflow_by_id(new_wf_id)
assert gone is None
print("[5] 新建/步骤/删除 无 NOT NULL/FK 错误")

payload = {
    "version": 1,
    "webhooks": [],
    "workflows": [{
        "id": "smoke_retired",
        "name": "冒烟退役字段",
        "watch": {"enabled": True, "mode": "bogus", "folders": ["D:/x", 9]},
        "single_script": {"enabled": True, "type": "cmd_shell", "path": 123},
        "steps": [{"name": "S", "step_type": "python", "script": "C:/smoke.py"}],
    }],
}
payload_path = tmp / "retired.json"
payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
count = database.import_from_json(payload_path)
wf = database.get_workflow_by_uid("smoke_retired")
assert wf is not None and count == 1
assert wf.risky_paths_review_required == 1, "导入含绝对路径应置 review_required=1"
assert wf.risky_paths_confirmed_digest is None
print(f"[6] 退役字段 JSON 导入忽略; 风险标记 review_required={wf.risky_paths_review_required}")
database.delete_workflow(wf.id)

wf2 = database.get_workflow_by_name("月度数据处理")
nc = wf2.get_notify_config()
assert nc.get("enabled") is True and nc.get("webhook_id") == 1, f"通知绑定丢失: {nc}"
print(f"[7] 通知配置完整: webhook_id={nc.get('webhook_id')}")

print("\n=== 副本冒烟全部通过 ===")
print(f"副本保留于: {tmp}")
