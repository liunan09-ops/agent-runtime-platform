"""Write a local Git receipt after the final commit, avoiding a self-referential commit hash."""

import json
import subprocess
from pathlib import Path

from agent_runtime.models import utcnow


def main():
    root = Path(__file__).resolve().parents[1]

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    record = {
        "recorded_at": utcnow(),
        "branch": git("branch", "--show-current"),
        "base_head": "5a7f8f21d26807aeb02f21731adc0062f9c41fa1",
        "final_head": git("rev-parse", "HEAD"),
        "status": git("status", "--short", "--branch"),
        "scope": "All committed code, tests, reports and evidence; this reproducible receipt itself is ignored to avoid changing the hash it records.",
    }
    (root / "docs/evidence/final-head.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
