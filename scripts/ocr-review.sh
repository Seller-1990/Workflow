#!/bin/bash
# ocr 评审包装脚本（标准链版 · 新机 Windows 适配）
# 基线：zcode-advisor origin/main 的成熟版（锁所有权/原子发布/JSON 状态白名单全保留），
# 仅移植平台差异：① 公共 git 目录定位（worktree 安全）② GNU timeout 优先
# ③ python 优先于 WindowsApps 的 python3 壳 ④ Windows npm 全局路径补 PATH
# ⑤ timeout 退出码 124 计入「被强制终止」判定。
#
# 设计（与 ~/.dsh/AGENTS.md 一致）：
#   - 评审工具**不进 CI**：模型网关是内网地址（192.168.50.139），GitHub runner 够不着；
#     拦截靠 CI 的确定性检查，评审只作为 advisory 关卡。
#   - 也**不定时跑**：只在每个 PR 合并前调用一次。
#
# 模型降级链（provider|model，与 ~/.opencodereview/config.json 的 custom_providers 对应）：
#   ⚠️ 链的**唯一真源**是 ~/.dsh/templates/ocr-review/chain-public（运行时直接读它）。
#      本文件里那段 CHAIN 数组只是读不到链文件时的**兜底快照**，别在这里找当前顺序——
#      它必然滞后（改链不必改脚本，也就没人会记得同步它）。
#      改链：编辑 chain-public 再跑 bash ~/.dsh/bin/ocr-sync-reviewer.sh 刷快照。
#   这里不再逐条列举模型名与顺序：链外置的全部意义就是「枚举会过期」，再抄一份
#   只会制造第二处会撒谎的注释（2026-10-06 实测：注释写着主棒 deepseek，运行时首跳
#   其实是 chain-public 的 minimax-m3）。各模型的可用性/耗时/成本结论写在链文件里，
#   那才是它们生效的地方。
#   【2026-10-04】隐私铁律暂缓（用户拍板）：私有仓也可用本链（私有副本用 ocr-review.sh.private
#      变体，链走 chain-private，同样允许 cloud 条目）。
#   ⚠️ kimi-k3 不支持工具调用（三次探针无 tool_calls）→ 不能当 ocr 模型，勿加回。
# 用法：
#   ./scripts/ocr-review.sh              # 默认基准 origin/dev（不存在则回退 main）
#   ./scripts/ocr-review.sh v1.8.8       # 对比 tag / 分支
#   ./scripts/ocr-review.sh main HEAD   # 指定 from/to

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# 公共 git 目录：worktree 下 .git 是文件不是目录，写死会失败（指南 §11 第 11 条）。
GIT_COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null || echo .git)"
case "$GIT_COMMON_DIR" in
  /*|?:*) ;;
  *) GIT_COMMON_DIR="$REPO_ROOT/$GIT_COMMON_DIR" ;;
esac

# ── 并发锁（实测教训）──
# pre-push hook 每次推送都会起一个评审，而完整评审要 5–15 分钟。
# 连续推送（或 tag + main 分开推）会让多个评审同时跑：既争抢上游配额，
# 又争抢同一个报告文件 .git/ocr-review-last.txt，且各自耗内存。
# 实测曾同时存在 6 个 ocr review 进程，最久的已跑 38 分钟。
#
# 用 mkdir 做原子锁（POSIX 下最可靠；flock 在 macOS 上不可用）。
# 锁内含 pid + 起始时间；发现锁时：
#   - 持锁进程仍活着 → 提示并退出（不重复评审）
#   - 持锁进程已死（崩溃/被 kill）→ 视为陈旧锁，接管
LOCK_DIR="$GIT_COMMON_DIR/ocr-review.lock"
LOCK_INFO="$LOCK_DIR/info"
# 只有**自己拿到锁**才允许在退出时删锁。OCR_REVIEW_FORCE=1 整段跳过、根本不取锁，
# 若无条件删就会把另一个正在跑的评审的锁连根拔掉——而并行评审正是 FORCE 的用途，
# 于是「强制并行」变成「两个进程互相拆锁」。清理由 cleanup() 按这个标记判断。
LOCK_ACQUIRED=""
# OCR_REVIEW_FORCE=1 可绕过（需要并行评审时显式指定）
if [ -z "${OCR_REVIEW_FORCE:-}" ]; then
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    LOCK_ACQUIRED=1
    printf 'pid=%s\nstarted=%s\n' "$$" "$(date +%s)" > "$LOCK_INFO"
    trap 'rm -rf "$LOCK_DIR"' EXIT INT TERM
  else
    HOLD_PID=""
    [ -f "$LOCK_INFO" ] && HOLD_PID="$(sed -n 's/^pid=//p' "$LOCK_INFO" 2>/dev/null)"
    if [ -n "$HOLD_PID" ] && kill -0 "$HOLD_PID" 2>/dev/null; then
      echo "[ocr-review] 已有评审在进行（pid ${HOLD_PID}），本次跳过以免重复消耗。"
      echo "[ocr-review] 已有报告：$GIT_COMMON_DIR/ocr-review-last.txt"
      echo "[ocr-review] 如需强制并行，设 OCR_REVIEW_FORCE=1"
      exit 0
    fi
    # 陈旧锁：持锁进程已不存在，接管
    echo "[ocr-review] 发现陈旧锁（pid ${HOLD_PID:-未知} 已退出），接管"
    LOCK_ACQUIRED=1
    printf 'pid=%s\nstarted=%s\n' "$$" "$(date +%s)" > "$LOCK_INFO"
    trap 'rm -rf "$LOCK_DIR"' EXIT INT TERM
  fi
fi

# ocr 装在 nvm 全局；cron/非交互 shell 不继承 PATH，这里显式补上。
# 先看 PATH 里有没有，没有再补常见位置（不把某个固定版本当成唯一来源）。
if ! command -v ocr >/dev/null 2>&1; then
  # nvm 版本号会随升级变化，用通配匹配当前安装的 node，而不是写死某个版本
  # 先看 nvm 默认别名指向的具体版本
  NVM_DEFAULT="$HOME/.nvm/alias/default"
  if [ -f "$NVM_DEFAULT" ]; then
    DEFAULT_VER="$(tr -d '[:space:]' < "$NVM_DEFAULT")"
    case "$DEFAULT_VER" in v*) ;; *) DEFAULT_VER="v$DEFAULT_VER" ;; esac
    CAND="$HOME/.nvm/versions/node/$DEFAULT_VER/bin"
    [ -x "$CAND/ocr" ] && PATH="$CAND:$PATH"
  fi
  # 再按版本号倒序扫（字典序会把 v10 排在 v20 之前，可能命中陈旧的全局安装）
  if ! command -v ocr >/dev/null 2>&1; then
    for candidate in $(ls -1d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -Vr) \n        /usr/local/bin /opt/homebrew/bin \n        "${APPDATA:-$HOME/AppData/Roaming}/npm" "$HOME/AppData/Roaming/npm"; do
      if [ -x "$candidate/ocr" ]; then
        PATH="$candidate:$PATH"
        break
      fi
    done
  fi
  export PATH
fi
if ! command -v ocr >/dev/null 2>&1; then
  echo "错误：找不到 ocr 命令（npm i -g @alibaba-group/open-code-review）" >&2
  exit 1
fi

AGENT_MODEL_FILE="$HOME/.opencodereview/agent-model"

# python 解释器：Windows 上 python3 常是 WindowsApps 应用执行别名（会打 shebang 警告），
# 优先用真实安装的 python；两者都没有时 python3 兜底（macOS 无 python 只有 python3）。
PY="$(command -v python || command -v python3 || true)"
[ -n "$PY" ] || { echo "错误：找不到 python 解释器（渲染评审结果需要）" >&2; exit 1; }

# 校验 ref 是否真实存在（避免把非法参数带进 ocr）
require_ref() {
  local ref="$1"
  case "$ref" in ''|-*) return 1 ;; esac
  # rev-parse --verify 对 blob/tree 也返回 0，必须确认解析为 commit
  git rev-parse --verify --quiet --end-of-options "${ref}^{commit}" >/dev/null 2>&1
}

# 基准：默认 origin/dev，回退 origin/main 或本地 main；都不可用则 HEAD~1
resolve_base() {
  local candidate="${1:-}"
  if [ -n "$candidate" ]; then
    if require_ref "$candidate"; then echo "$candidate"; return 0; fi
    echo "错误：基准 ref 不存在：$candidate" >&2
    return 1
  fi
  local ref
  for ref in origin/dev origin/main main; do
    if require_ref "$ref"; then echo "$ref"; return 0; fi
  done
  if require_ref "HEAD~1"; then echo "HEAD~1"; return 0; fi
  # 只有一次提交时：空树作基准，让首次提交也能被评审
  local empty_tree
  empty_tree="$(git hash-object -t tree /dev/null 2>/dev/null || true)"
  if [ -n "$empty_tree" ]; then echo "$empty_tree"; return 0; fi
  echo "错误：找不到可用基准（仓库尚无提交）" >&2
  return 1
}

FROM="$(resolve_base "${1:-}")" || exit 1
TO="${2:-HEAD}"
if ! require_ref "$TO"; then
  echo "错误：目标 ref 不存在：$TO" >&2
  exit 1
fi

# 代理当前模型：仅作避让提示（避免评审与编码代理抢同一个模型配额）
AGENT_MODEL="$(tr -d '[:space:]' < "$AGENT_MODEL_FILE" 2>/dev/null || true)"
[ -n "$AGENT_MODEL" ] && echo "（编码代理当前模型：${AGENT_MODEL}，评审将优先使用其他 provider）"

# === 降级链区块开始（由 ~/.dsh/bin/ocr-sync-reviewer.sh 从 chain-public 生成，勿手改）===
# 降级链唯一真源：~/.dsh/templates/ocr-review/chain-public
#   一行一条 scope|provider|model，顺序即优先级，第一个产出有效 JSON 的即采用。
#   改链只改那个文件：副本运行时也直接读它，下面这份只是读不到时的兜底快照。
CHAIN_FILE="${OCR_REVIEW_CHAIN_FILE:-$HOME/.dsh/templates/ocr-review/chain-public}"
CHAIN_SCOPE="public"   # public 副本：cloud 条目合法，但仍以链文件为唯一真源
CHAIN=(
  "nas-hy4|space-bunny"
  "x666|ministral-14b-latest"
  "runanytime-astra|gpt-6-astra"
  "lucky|step-5-preview"
  "nas-octopus|gemini-3.7-flash"
  "nas-hy4|gemini-3.5-flash"
  "nas-hy4|deepseek-v4.1-flash"
  "nas-hy4|deepseek-v4.1-flash-sg"
  "nas-hy4|glm-5.3"
  "nas-hy4|gpt-6-astra"
  "nas-hy4|gemini-3.8-flash"
  "nas-hy4|kimi-k2.8-preview"
  "nas-hy4|hy3"
  "nas-hy4|hy4-preview-f"
)
# 运行时优先读链文件：读不到 / 解析出 0 条 → 保留上面的快照（脚本被单独拷走也跑得起来）。
_chain_found=()
if [ -r "$CHAIN_FILE" ]; then
  while IFS= read -r _line || [ -n "$_line" ]; do
    _line="${_line%%#*}"                       # 去掉行内注释
    _line="${_line//[[:space:]]/}"             # 去空白，容忍手滑多打空格
    _pipes="${_line//[!|]/}"                   # 只留竖线，用来数段数
    [ "${#_pipes}" -eq 2 ] || continue         # 必须正好 scope|provider|model
    _scope="${_line%%|*}"; _entry="${_line#*|}"
    [ -n "$_scope" ] || continue
    _p="${_entry%%|*}"; _m="${_entry#*|}"
    [ -n "$_p" ] && [ -n "$_m" ] || continue
    _chain_found[${#_chain_found[@]}]="$_entry"
  done < "$CHAIN_FILE"
fi
if [ "${#_chain_found[@]}" -gt 0 ]; then
  CHAIN=("${_chain_found[@]}")
else
  echo "（链文件 ${CHAIN_FILE} 不可用，用内嵌快照 ${#CHAIN[@]} 条）" >&2
fi
# === 降级链区块结束 ===

# 时间预算：防"建连后永久挂起"把整条链卡死（本机无 GNU timeout，见 run_with_deadline）。
#   HOP_TIMEOUT  单跳上限。完整评审实测 5–15 分钟，900s 覆盖正常耗时，只掐挂起。
#   TOTAL_BUDGET 整条链最长耗时。公开链条目多，按 6 跳封顶——再长会把
#                .git/ocr-review.lock 占用到之后每次推送都被误判"已有评审在进行"。
HOP_TIMEOUT="${OCR_REVIEW_HOP_TIMEOUT:-900}"
TOTAL_BUDGET="${OCR_REVIEW_TOTAL_BUDGET:-5400}"
CHAIN_START="$(date +%s)"

# 上游限流与资产噪音的稳定参数（都是实测踩出来的教训，不是默认值拍脑袋）：
#   --concurrency：ocr 默认并发 8 个子任务，实测会打满 x666 的「25 请求/5 分钟」限流（429），
#     曾连续 6 次评审全灭。降并发换稳；限流充裕的 provider 用 OCR_REVIEW_CONCURRENCY=8 调回。
#   --exclude：二进制图片资产进 diff 只会塞爆每个分组的上下文，对文本评审是纯噪音
#     （zcode-advisor 实测两个模型 20 组全返回空 comments）。要连图片一起审就设空串关掉。
# 用数组而不是字符串展开：排除模式里的 **/*.png 是通配符，字符串展开会被
# 当前目录里的真实文件 glob 成文件名，旗标就废了。
OCR_REVIEW_CONCURRENCY="${OCR_REVIEW_CONCURRENCY:-2}"
OCR_REVIEW_EXCLUDE="${OCR_REVIEW_EXCLUDE:-**/*.png,**/*.ico,**/*.icns,**/*.jpg,**/*.jpeg,**/*.gif,**/*.pdf}"
OCR_EXTRA_ARGS=()
OCR_EXTRA_ARGS+=(--concurrency "$OCR_REVIEW_CONCURRENCY")
[ -n "$OCR_REVIEW_EXCLUDE" ] && OCR_EXTRA_ARGS+=(--exclude "$OCR_REVIEW_EXCLUDE")

# 实际使用台账：每次评审把"用了哪个 provider/model、成没成"追加到一份公共日志，
# 供 ~/.dsh/hooks/ocr-pool-status.sh 展示最近几跳（否则没人知道当前到底在用谁）。
# 只写 provider/model 名与结果，不写 diff 内容、不写 key。
USAGE_LOG="${OCR_REVIEW_USAGE_LOG:-$HOME/.dsh/hooks/ocr-pool-usage.log}"
record_use() {  # $1=provider $2=model $3=ok|skip|fail
  printf '%s\t%s\t%s\t%s\t%s\n' "$(date '+%F %T')" "$(basename "${REPO_ROOT:-$PWD}")" "$1" "$2" "$3" \
    >>"$USAGE_LOG" 2>/dev/null || true
}

# 模板必须以 XXXXXX 结尾：GNU mktemp 把 -t 当 --tmpdir 并要求该后缀（BSD/macOS 两者都接受）。
TMPDIR_OCR="${TMPDIR:-/tmp}"
OUT_JSON="$(mktemp "${TMPDIR_OCR%/}/ocr-review-XXXXXX" 2>/dev/null)" || {
  echo "错误：无法创建临时文件（mktemp 失败）" >&2; exit 1;
}
[ -n "$OUT_JSON" ] || { echo "错误：mktemp 未返回路径" >&2; exit 1; }
ATTEMPT_LOG=""
# 注意：这个 trap 会覆盖前面的锁清理 trap，所以 rm -rf "$LOCK_DIR" 必须在这里再做一次，
# 否则锁目录永不消失，之后每次运行都误报"陈旧锁"（虽然能接管，但看着像坏了）。
# OCR_REVIEW_RAW_OUT（可选，由调用方提供，例如 pre-push hook）：把 ocr 的**原始 JSON**
# 另存一份。它是权威产物（下面的渲染表由它生成），而 OUT_JSON 只是 mktemp 临时文件、
# 退出时被本函数删掉 —— 此前评审成功后原始 JSON 一并消失，事后无法复核或重渲染。
#
# 两道守卫，缺一不可：
#   - `$CHOSEN` 非空 = 确有一跳产出完整评审。**不能**只看 OUT_JSON 非空：链全失败时
#     OUT_JSON 里留着最后一跳的 partial/无效输出，照拷会把上一份好结论覆盖成半成品。
#   - 命中锁而提前退出的进程根本走不到这里（锁检查在 OUT_JSON 创建之前）。
cleanup() {
  if [ -n "${OCR_REVIEW_RAW_OUT:-}" ] && [ -n "${CHOSEN:-}" ]; then
    # 这里不再检查 OUT_JSON 非空：$CHOSEN 只在 valid_output 通过后赋值，而 valid_output
    # 首行就是 [ -s "$OUT_JSON" ]，故「CHOSEN 非空」已蕴含「有完整评审可拷」。
    if [ -d "$OCR_REVIEW_RAW_OUT" ]; then
      # 传目录进来时 cp/mv 会把文件塞进目录、还顺带覆盖同名文件，与「保存到该路径」的
      # 契约不符；明确拒绝好过默默塞进去。（[ -d ] 跟随符号链接，指向目录的链接同样被拒。）
      echo "警告：OCR_REVIEW_RAW_OUT=$OCR_REVIEW_RAW_OUT 是目录（期望文件路径），跳过保存原始 JSON" >&2
    else
      # 先写同目录临时文件再 mv，而不是直接 cp：
      #   ① cp 是「打开目标→截断→写入」，并发读者会看到 0 字节或半截文件；本脚本用
      #      OCR_REVIEW_FORCE=1 明确支持并行运行，两个评审会争同一目标，必须原子发布。
      #   ② cp 会**跟随**目标符号链接（把内容写穿到链接指向的文件）；mv 替换链接本身。
      #   ③ 只有同目录的 mv 才是原子的（跨文件系统会退化成 copy+unlink）。
      #   ④ 临时名必须**不可预测**：用 "${TARGET}.tmp.$$" 这种可枚举（PID）的名字，
      #      攻击者能预置同名符号链接，cp 会跟随它把内容写穿到任意文件（已实测复现）。
      #      mktemp 在目标同目录创建、名随机，且 O_EXCL 保证不会被既有文件/链接抢占。
      local _raw_dir _raw_tmp
      _raw_dir="$(dirname "$OCR_REVIEW_RAW_OUT")"
      _raw_tmp="$(mktemp "${_raw_dir%/}/.ocr-raw-XXXXXX" 2>/dev/null)" || _raw_tmp=""
      if [ -z "$_raw_tmp" ]; then
        echo "警告：无法在 $_raw_dir 创建临时文件，保存原始 JSON 到 $OCR_REVIEW_RAW_OUT 失败（事后复核将不可用）" >&2
      elif ! cp -f "$OUT_JSON" "$_raw_tmp" 2>/dev/null || ! mv -f "$_raw_tmp" "$OCR_REVIEW_RAW_OUT" 2>/dev/null; then
        # 静默失败最坑：这个功能存在的意义就是「事后能复核」，写不成功必须说一声。
        # 但不改退出码——cleanup 不该篡改脚本本身的成败。
        rm -f "$_raw_tmp" 2>/dev/null || true
        echo "警告：保存原始 JSON 到 $OCR_REVIEW_RAW_OUT 失败（事后复核将不可用）" >&2
      fi
      # 注：mktemp 建的文件是 0600，mv 保留该权限 → 发布出去的原始 JSON 不会对同机其他
      # 用户可读（评审原文可能含代码）。别改成先 cp 到普通文件再改名，那会带上 umask 权限。
      #
      # 已知残余窗口：上面 [ -d ] 与 mv 之间，目标仍可能被并发替换成目录，此时 mv 会把
      # 文件移进该目录。能这么做的人对目标目录已有写权限、本可径直覆盖报告文件，
      # 故此处只做「更早发现」，不宣称已消除该竞态。
      #
      # 也不在此处预清理历史 .ocr-raw-*：本脚本用 OCR_REVIEW_FORCE=1 明确支持并行评审，
      # 另一个并发进程的临时文件正等着 mv，清掉它等于毁掉那次评审的发布。残留只可能来自
      # SIGKILL（trap 跑不到）——这是「同目录原子发布」换来的固有代价，不能靠删别人的文件消除。
      # （dirname 对 "/foo.json" 返回 "/"、对 "foo.json" 返回 "."，**永不为空**，故无需兜底。）
    fi
  fi
  rm -f "$OUT_JSON" ${ATTEMPT_LOG:+"$ATTEMPT_LOG"}
  # 只在**自己持锁**时回收（见 LOCK_ACQUIRED 定义处）：无条件删会把并行评审的锁拆掉。
  [ -n "$LOCK_ACQUIRED" ] && rm -rf "$LOCK_DIR"
}
trap cleanup EXIT INT TERM

# 判定一次尝试是否真正成功：退出码为 0 **且** 评审确实完整完成。
#
# 判定依据来自 ocr 自身的状态枚举（从其二进制字符串表提取，2026-09 实测）：
#   TerminalState = complete | partial | failed | skipped | aborted | legacy
# 其中只有 `complete` 表示「全部选中项都评审完成」；`partial` 会打印
# "Review partially complete: N finding(s); M of K selected item(s) failed."。
#
# 为什么用**白名单**而不是黑名单：黑名单已被咬过两次——
#   ① {"status":"failed",...}（无 comments）曾被当成干净通过；
#   ② 补上 failed/error/cancelled 后，{"status":"partial","comments":[]} 仍被当成通过。
# 只认 `complete` 才不会再有第三个未知状态漏过。
#
# 注意：**不能**用 retry_report.failed_requests 当判据——plan 阶段的失败
# （日志里的 "continuing without plan"）不影响评审覆盖，按它判定会在上游限流时
# 误拒完整结果、触发无谓重跑。覆盖完整性以 status 为准。
valid_output() {
  [ -s "$OUT_JSON" ] || return 1
  "$PY" - "$OUT_JSON" <<'PYCHECK' >/dev/null 2>&1
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(1)
if not isinstance(data, dict):
    sys.exit(1)

# 白名单：只有 complete 才算完整评审
if str(data.get("status") or "").lower() != "complete":
    sys.exit(1)

# comments 必须存在且为数组（0 条也是合法的"未发现问题"）
if not isinstance(data.get("comments"), list):
    sys.exit(1)
PYCHECK
}

# hard deadline：给一条命令套"最多 secs 秒"的上限，超时整组终止（含孙进程）。
#
# 为什么不用 `timeout`：本机是 macOS + bash 3.2，没有 GNU coreutils 的 timeout，
# 也没有 gtimeout（防止某天被装进来）。
# 为什么不用 `perl -e 'alarm N; exec @ARGV'`：alarm 只杀 perl 自己变出的那个进程，
# ocr 派生的子进程会漏成孤儿。这里改用"自成进程组 + 整组 signale"：
#   set -m 让后台任务成为组长（PGID == PID），超时时 kill -TERM -- -PID 全组带走。
# 安全细节：只有在确认目标 PGID 等于自身 PID 时才发组信号，否则退化成
# "先杀子进程、再杀父进程"，绝不可能误伤本脚本所在的进程组。
# 退出码：快命令原样透传；被杀时 143(TERM)/137(KILL)，调用方据此判定超时。
run_with_deadline() {
  local secs="$1"; shift
  case "$secs" in ''|*[!0-9]*) "$@"; return $? ;; esac
  [ "$secs" -gt 0 ] || { "$@"; return $?; }
  # 新机（Windows Git Bash / 装了 coreutils 的机器）有 GNU timeout，优先用它：
  # 语义清晰（超时退出码 124），且 MSYS 会一并带走子进程树。
  #
  # ⚠️ 必须用 `timeout --version` 探测而不是 `command -v timeout`：Windows 自带
  #    C:/Windows/System32/timeout.exe 是同名异物（等 N 秒的延时命令，不包装别的命令），
  #    命中它会把 `timeout 900 ocr review …` 当成非法参数静默跑偏。
  #    GNU 版有 --version，Windows 版没有（实测其退出码与输出均不同）。
  if timeout --version >/dev/null 2>&1; then
    timeout "$secs" "$@"
    return $?
  fi
  set -m
  "$@" &
  local cmd_pid=$!
  set +m
  (
    sleep "$secs" 2>/dev/null
    if [ "$(ps -o pgid= -p "$cmd_pid" 2>/dev/null | tr -d ' ')" = "$cmd_pid" ]; then
      kill -TERM -- "-$cmd_pid" 2>/dev/null
    else
      pkill -TERM -P "$cmd_pid" 2>/dev/null
      kill -TERM "$cmd_pid" 2>/dev/null
    fi
    sleep 2 2>/dev/null
    if [ "$(ps -o pgid= -p "$cmd_pid" 2>/dev/null | tr -d ' ')" = "$cmd_pid" ]; then
      kill -KILL -- "-$cmd_pid" 2>/dev/null
    else
      pkill -KILL -P "$cmd_pid" 2>/dev/null
      kill -KILL "$cmd_pid" 2>/dev/null
    fi
  ) &
  local watcher_pid=$!
  # 下面三行的 || rc=$? / || true 是给 set -e 型调用方兜底：超时后这一跳返回 143，
  # 裸 wait 在 set -euo pipefail 的脚本里会直接把整个评审带走，链就不再降级了（实测踩过）。
  local rc=0
  wait "$cmd_pid" 2>/dev/null || rc=$?
  kill "$watcher_pid" 2>/dev/null || true
  wait "$watcher_pid" 2>/dev/null || true
  return $rc
}

echo "评审范围：$FROM .. $TO"
CHOSEN=""
SKIPPED=0
SKIPPED_ALL=0
FAILURE_DIAG=""
for entry in "${CHAIN[@]}"; do
  provider="${entry%%|*}"
  model="${entry##*|}"
  # 总预算先用完就不再试后面的：宁可本次无评审，也不无限期占着锁
  REMAIN=$(( TOTAL_BUDGET - ($(date +%s) - CHAIN_START) ))
  if [ "$REMAIN" -le 0 ]; then
    echo "  总预算 ${TOTAL_BUDGET}s 已用尽，剩余 provider 不再尝试"
    break
  fi
  if [ -n "$AGENT_MODEL" ] && [ "$model" = "$AGENT_MODEL" ]; then
    echo "  跳过 ${provider}（$model 正被编码代理占用）"
    SKIPPED=$((SKIPPED + 1))
    [ "$SKIPPED" -eq "${#CHAIN[@]}" ] && SKIPPED_ALL=1
    continue
  fi
  HOP_LIMIT="$HOP_TIMEOUT"
  [ "$HOP_LIMIT" -gt "$REMAIN" ] && HOP_LIMIT="$REMAIN"
  # 每次尝试前清空，防止失败后残留上次结果被误判为成功
  : > "$OUT_JSON"
  ATTEMPT_LOG="$(mktemp "${TMPDIR_OCR%/}/ocr-attempt-XXXXXX" 2>/dev/null || true)"
  echo "  尝试 provider=$provider model=$model （上限 ${HOP_LIMIT}s）…"
  HOP_RC=0
  run_with_deadline "$HOP_LIMIT" ocr review --from "$FROM" --to "$TO" --format json --output "$OUT_JSON" \
       ${OCR_EXTRA_ARGS[@]+"${OCR_EXTRA_ARGS[@]}"} \
       --provider "$provider" --model "$model" >"${ATTEMPT_LOG:-/dev/null}" 2>&1 || HOP_RC=$?
  if [ "$HOP_RC" -eq 0 ] && valid_output; then
    echo "  成功：$provider / $model"
    CHOSEN="$provider/$model"
    record_use "$provider" "$model" ok
    [ -n "$ATTEMPT_LOG" ] && rm -f "$ATTEMPT_LOG"
    break
  fi
  case "$HOP_RC" in
    124|137|143) echo "  ⚠ 本跳到 ${HOP_LIMIT}s 上限被强制终止（退出码 ${HOP_RC}），降级到下一个" ;;
    esac
  # 保留该次失败输出尾部，供全失败时排查（此前一律丢进 /dev/null）
  if [ -n "$ATTEMPT_LOG" ]; then
    FAILURE_DIAG="${FAILURE_DIAG}--- ${provider}/${model} (exit=${HOP_RC}, limit=${HOP_LIMIT}s) ---
$(tail -5 "$ATTEMPT_LOG" 2>/dev/null)
"
    rm -f "$ATTEMPT_LOG"
  fi
  echo "  失败或输出无效，降级到下一个"
done

if [ -z "$CHOSEN" ]; then
  if [ "$SKIPPED_ALL" = "1" ]; then
    # 与「链坏了」区分开：这不是 provider 失败，是编码代理占用了链上每一个模型。
    # 记 skip 而不是 fail，否则台账会把「今天没评审」统计成「provider 全挂」。
    record_use "-" "-" skip
    echo "错误：所有 provider 都因与编码代理同模型被跳过（agent-model=${AGENT_MODEL}）。" >&2
    echo "      可临时指定：ocr review --provider <p> --model <m>" >&2
  else
    record_use "-" "-" fail
    echo "错误：${TOTAL_BUDGET}s 预算内没有一跳产出有效评审结果。" >&2
  fi
  if [ -n "$FAILURE_DIAG" ]; then
    echo "各 provider 输出尾部：" >&2
    printf '%s' "$FAILURE_DIAG" >&2
  fi
  exit 1
fi

# 把 ocr 的 JSON 输出转成便于阅读的表格。
# ocr 的真实 JSON 形状（2026-09 实测）：
#   { status, llm, message, summary, tool_calls, comments[], groups[], session_id, manifest, retry_report }
#   comments[] 元素键：path, content, suggestion_code, existing_code, start_line, end_line, thinking, category, severity
# 渲染失败必须让脚本非零退出（set -e 未开启，故显式传递）。
if ! "$PY" - "$OUT_JSON" "$CHOSEN" <<'PY'
import json, sys

path, chosen = sys.argv[1], sys.argv[2]
try:
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
except Exception as exc:
    print(f"无法解析 ocr 输出（{exc}）")
    sys.exit(1)

if not isinstance(data, dict):
    print("无法解析 ocr 输出（顶层不是对象）")
    sys.exit(1)

comments = data.get('comments')
if not isinstance(comments, list):
    comments = []
comments = [c for c in comments if isinstance(c, dict)]

print()
print(f"评审完成（{chosen}）—— 共 {len(comments)} 条意见")
summary = data.get('summary')
if isinstance(summary, str) and summary.strip():
    print(f"  摘要：{summary.strip()[:200]}")
if not comments:
    print("  未发现问题。")
    sys.exit(0)

import unicodedata

def display_width(text):
    # CJK 字形是双宽：用显示宽度而非码点数做列对齐
    return sum(2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1 for ch in text)

def pad(text, width):
    return text + ' ' * max(0, width - display_width(text))

def clip(text, width):
    # 截断时补省略号，避免读者误以为内容是完整的
    if display_width(text) <= width:
        return text
    out, used = '', 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
        if used + w > width - 1:
            break
        out += ch
        used += w
    return out + '…'

SEV_ORDER = {'critical': 0, 'high': 1, 'major': 1, 'medium': 2, 'minor': 3, 'low': 3, 'info': 4}

def sev_rank(comment):
    raw = comment.get('severity')
    return SEV_ORDER.get(str(raw).lower() if raw is not None else '', 9)

def sev_text(comment):
    raw = comment.get('severity')
    text = str(raw).strip() if raw is not None else ''
    return text or '-'

def location(comment):
    path_value = comment.get('path')
    p = str(path_value).strip() if path_value is not None else ''
    p = p or '?'
    start, end = comment.get('start_line'), comment.get('end_line')
    # 显式判空：行号 0 是合法值，不能用 `or` 丢掉
    if start is not None and end is not None and start != end:
        return f"{p}:{start}-{end}"
    if start is not None:
        return f"{p}:{start}"
    return p

SEV_W, LOC_W = 8, 46
print()
print(f"{pad('严重度', SEV_W)} {pad('位置', LOC_W)} 说明")
print("-" * 118)
for c in sorted(comments, key=sev_rank):
    msg = ' '.join(str(c.get('content') or '').split())
    cat_raw = c.get('category')
    cat = str(cat_raw).strip() if cat_raw is not None else ''
    if cat:
        msg = f"[{cat}] {msg}"
    print(f"{pad(clip(sev_text(c), SEV_W), SEV_W)} {pad(clip(location(c), LOC_W), LOC_W)} {clip(msg, 170)}")
    # 修复建议是评审里最有价值的部分，单独缩进打印
    suggestion_raw = c.get('suggestion_code')
    suggestion = str(suggestion_raw).strip() if suggestion_raw is not None else ''
    if suggestion and suggestion.lower() not in ('null', 'none'):
        first_line = suggestion.splitlines()[0]
        print(f"{'':<{SEV_W}} {'':<{LOC_W}}   ↳ 建议：{clip(first_line, 150)}")
PY
then
  echo "错误：评审结果渲染失败。" >&2
  exit 1
fi
