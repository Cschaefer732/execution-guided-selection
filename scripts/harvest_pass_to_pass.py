import json
import pathlib

root = pathlib.Path.home() / "swe-grade-arm/logs/run_evaluation"
out: dict[str, dict[str, dict]] = {}
for slot in range(5):
    run_dir = root / f"nova-bo{slot}-bo13"
    if not run_dir.is_dir():
        continue
    for report_path in sorted(run_dir.glob("*/*/report.json")):
        iid = report_path.parent.name
        try:
            rep = json.loads(report_path.read_text())
        except Exception:
            continue
        inner = rep.get(iid, rep)
        status = (inner or {}).get("tests_status") or {}
        p2p = status.get("PASS_TO_PASS") or {}
        # PASS_TO_PASS only. The held-out section is deliberately not read.
        out.setdefault(str(slot), {})[iid] = {
            "success": len(p2p.get("success") or []),
            "failure": len(p2p.get("failure") or []),
            "applied": bool((inner or {}).get("patch_successfully_applied")),
        }
print(json.dumps(out))
