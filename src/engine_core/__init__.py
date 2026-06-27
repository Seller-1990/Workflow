"""engine_core 包：headless 友好的执行内核子组件

注意：本包不再 re-export engine.py 的 WorkflowEngine，因为 engine.py 自身
依赖 engine_core.watcher 等，re-export 会触发循环导入。
GUI / CLI 应当直接 ``from engine import WorkflowEngine``。
"""

from engine_core.batch import compute_batches
from engine_core.watcher import (
    FileWatcher,
    validate_watch_folders,
    scan_folder_mtimes,
    scan_mtime,
)
from engine_core.notification import send_run_notification
from engine_core.lifecycle import (
    RunContext,
    SkipDecision,
    begin_run,
    finalize_run,
    mark_step_running,
    create_running_step_log,
    create_skipped_step_log,
    check_skip_on_success,
    should_skip_on_success,
    record_skip_on_success,
    build_prev_step_status_map,
)
from engine_core.scheduler import run_steps_parallel
from engine_core.cancel import install_cancel_watcher
from engine_core.stages import (
    UNASSIGNED_STAGE_UID,
    UNASSIGNED_STAGE_NAME,
    build_stage_meta,
    normalize_stage_uid,
)
from engine_core.preview import (
    SEPARATOR_LINE,
    build_stage_group_map,
    describe_batch_mode,
    format_dry_run_lines,
)
from engine_core.log_cleanup import LOG_DIR_PATTERN, cleanup_old_log_dirs
from engine_core.selection import select_steps
from engine_core.force_stop import (
    ForceStopResult,
    force_cancel_run_record,
    read_run_history_status,
)
