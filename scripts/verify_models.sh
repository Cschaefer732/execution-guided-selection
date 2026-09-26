#!/usr/bin/env bash
# Report the model each harness ACTUALLY called, per instance, for one arm's last run.
#
# The whole point of a harness comparison is that the model is held fixed, and every harness
# pins its model somewhere different — the default agent on the command line, dsh in a
# --patch overlay behind a nested include. Config is not evidence: one session found a dsh
# composed config claiming one model while its web_search provider independently called a
# different one. So read it back out of each harness's own session log.
#
#   scripts/verify_models.sh nova
#   scripts/verify_models.sh dsh
#
# Every branch below counts what it matched. If a branch matches zero log files/rows, that is
# NOT the same as verified-clean — it means nothing was checked. Empty output must never read
# as success: the branch prints "NO EVIDENCE FOUND" and the script exits non-zero.
set -uo pipefail

ARM="${1:?usage: verify_models.sh <arm>}"
HOST="${2:-${AGENT_HOST:-localhost}}"
EXPECT="${EXPECT_MODEL:-qwen3.8:27b}"

echo "arm=$ARM  expecting=$EXPECT  host=$HOST"

case "$ARM" in
  dsh*)
    # dsh: zstd-compressed JSONL session per workdir, keyed by the mangled cwd.
    ssh "$HOST" '
      count=0
      for f in ~/.dsh/sessions/--tmp-swe-dsh-*/session-*/session.jsonl.zstd; do
          [ -f "$f" ] || continue
          count=$((count+1))
          inst=$(echo "$f" | sed -E "s|.*--tmp-swe-dsh-(.*)--/session.*|\1|")
          models=$(zstd -dc "$f" 2>/dev/null | grep -oE "\"model\":\"[^\"]+\"" | sort -u | sed "s/\"model\"://;s/\"//g" | tr "\n" " ")
          printf "  %-28s %s\n" "$inst" "${models:-<none recorded>}"
        done
      if [ "$count" -eq 0 ]; then
        echo "NO EVIDENCE FOUND: no ~/.dsh/sessions/--tmp-swe-dsh-*/session-*/session.jsonl.zstd on this host"
        exit 1
      fi
    '
    status=$?
    ;;
  openclaude*)
    # openclaude (Claude-Code-shaped TS fork): one JSONL session log per instance under
    # ~/.openclaude/projects/<mangled-cwd>/*.jsonl — mangled by turning both '/' and '_' into
    # '-', so /tmp/swe/openclaude/django__django-11099 becomes
    # -tmp-swe-openclaude-django--django-11099. Verified against the 2026-08-18 run: every
    # entry (user and assistant) carries "model":"qwen3.8:27b" in that log.
    ssh "$HOST" "
      count=0
      for d in ~/.openclaude/projects/-tmp-swe-${ARM}-*/; do
          [ -d \"\$d\" ] || continue
          f=\$(ls \"\$d\"*.jsonl 2>/dev/null | head -1)
          [ -f \"\$f\" ] || continue
          count=\$((count+1))
          inst=\$(basename \"\$d\" | sed -E 's/^-tmp-swe-${ARM}-//; s/--/__/')
          models=\$(grep -oE '\"model\":\"[^\"]+\"' \"\$f\" | sort -u | sed 's/\"model\"://;s/\"//g' | tr '\n' ' ')
          printf '  %-28s %s\n' \"\$inst\" \"\${models:-<none recorded>}\"
        done
      if [ \"\$count\" -eq 0 ]; then
        echo 'NO EVIDENCE FOUND: no ~/.openclaude/projects/-tmp-swe-${ARM}-*/*.jsonl session logs on this host'
        exit 1
      fi
    "
    status=$?
    ;;
  opencode*)
    # opencode (sst/opencode): sessions + per-message model calls live in a SQLite store at
    # ~/.local/share/opencode/opencode.db. session.directory is the eval workdir; each
    # assistant message row carries its own providerID/modelID (not just the session-level
    # default), so aggregate distinct models per session the same way the dsh/openclaude
    # branches do, rather than trusting a single config field.
    ssh "$HOST" "
      db=~/.local/share/opencode/opencode.db
      if ! out=\$(sqlite3 -separator '|' \"\$db\" \"
          SELECT s.directory,
                 COALESCE(GROUP_CONCAT(DISTINCT json_extract(m.data,'\\\$.providerID')||'/'||json_extract(m.data,'\\\$.modelID')), '')
          FROM session s
          LEFT JOIN message m ON m.session_id = s.id AND json_extract(m.data,'\\\$.role')='assistant'
          WHERE s.directory LIKE '/tmp/swe/${ARM}/%'
          GROUP BY s.directory
          ORDER BY s.directory;
        \" 2>&1); then
        echo \"NO EVIDENCE FOUND: sqlite3 query against \$db failed: \$out\"
        exit 1
      fi
      if [ -z \"\$out\" ]; then
        echo \"NO EVIDENCE FOUND: no session rows in \$db for directory /tmp/swe/${ARM}/%\"
        exit 1
      fi
      echo \"\$out\" | while IFS='|' read -r dir model; do
        inst=\$(basename \"\$dir\")
        printf '  %-28s %s\n' \"\$inst\" \"\${model:-<none recorded>}\"
      done
    "
    status=$?
    ;;
  *)
    # default agent (private harness): crush.log inside each cloned workdir.
    ssh "$HOST" "
      count=0
      for d in /tmp/swe/${ARM}/*/; do
          f=\"\$d/.crush/logs/crush.log\"
          [ -f \"\$f\" ] || continue
          count=\$((count+1))
          models=\$(grep -oE '\"model\":\"[^\"]+\"' \"\$f\" 2>/dev/null | sort -u | sed 's/\"model\"://;s/\"//g' | tr '\n' ' ')
          printf '  %-28s %s\n' \"\$(basename \$d)\" \"\${models:-<none recorded>}\"
        done
      if [ \"\$count\" -eq 0 ]; then
        echo 'NO EVIDENCE FOUND: no /tmp/swe/${ARM}/*/.crush/logs/crush.log on this host'
        exit 1
      fi
    "
    status=$?
    ;;
esac

echo
if [ "${status:-1}" -ne 0 ]; then
  echo "verify_models.sh: FAILED for arm=$ARM — nothing was verified. Silence is not evidence."
  exit 1
fi

echo "Any model above other than $EXPECT means the comparison is not apples-to-apples."
echo "Secondary calls (titles, web search, compaction) count: they consume a different model"
echo "and may leave the box entirely."
