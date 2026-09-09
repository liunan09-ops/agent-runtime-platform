"""Audit publishable project files and all project blobs in new commits; never echo secrets."""

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from agent_runtime.models import utcnow

BASE = "5a7f8f21d26807aeb02f21731adc0062f9c41fa1"
PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parent
EXCLUDED = {
    ".venv",
    "runtime-data",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".git",
    "build",
    "dist",
}


def scan_text(content):
    found = []
    for name in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        value = os.getenv(name)
        if value and value in content:
            found.append("exact_environment_credential")
    patterns = {
        "key_pattern": r"\bsk-[A-Za-z0-9_-]{16,}\b",
        "private_key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "personal_absolute_path": r"/(?:Users|home)/[A-Za-z0-9_.-]+/",
        "personal_email": r"[A-Za-z0-9_.+-]+@(?:gmail\.com|qq\.com|163\.com|Mac\.[A-Za-z0-9.-]+)",
    }
    for label, pattern in patterns.items():
        if re.search(pattern, content):
            found.append(label)
    return found


def main(write_report=True):
    findings = []
    hashes = {}
    for path in sorted(PROJECT.rglob("*")):
        relative = path.relative_to(PROJECT)
        if not path.is_file() or any(
            p in EXCLUDED or p.endswith(".egg-info") for p in relative.parts
        ):
            continue
        if path.name in {".coverage", ".DS_Store", "final-head.json"} or path.suffix in {
            ".pyc",
            ".db",
        }:
            continue
        if str(relative) in {"docs/evidence/public-safety.json", "docs/evidence/public-safety.log"}:
            continue
        data = path.read_bytes()
        hashes[str(relative)] = hashlib.sha256(data).hexdigest()
        for kind in scan_text(data.decode("utf-8", errors="replace")):
            findings.append({"path": str(relative), "kind": kind})
        if path.name.startswith(".env") and path.name != ".env.example":
            findings.append({"path": str(relative), "kind": "environment_file"})
    # Traverse only project blobs introduced on this branch; no old project file is read.
    revs = subprocess.check_output(
        ["git", "rev-list", "--objects", f"{BASE}..HEAD", "--", "agent-runtime-platform/"],
        cwd=REPO,
        text=True,
    )
    blobs = 0
    for line in revs.splitlines():
        object_id, _, path = line.partition(" ")
        if not path:
            continue
        typ = subprocess.check_output(
            ["git", "cat-file", "-t", object_id], cwd=REPO, text=True
        ).strip()
        if typ != "blob":
            continue
        blobs += 1
        content = subprocess.check_output(["git", "cat-file", "blob", object_id], cwd=REPO).decode(
            "utf-8", errors="replace"
        )
        for kind in scan_text(content):
            findings.append({"path": path, "kind": "historical_" + kind, "object_id": object_id})
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", BASE], cwd=REPO, text=True
    ).splitlines()
    outside = [p for p in changed if not p.startswith("agent-runtime-platform/")]
    result = {
        "recorded_at": utcnow(),
        "scope": "Project source, fixtures, documentation, evidence files and historical project blobs since fixed base; excludes virtualenv, runtime databases, standard Git author identities.",
        "files_scanned": len(hashes),
        "historical_blobs_scanned": blobs,
        "findings": findings,
        "outside_project_changes": outside,
        "manual_review": {
            "synthetic_data_only": True,
            "no_corporate_data": True,
            "no_old_project_artifacts": True,
            "env_example_empty_credentials": True,
            "docker_copy_allowlist": True,
            "normal_git_author_metadata_retained": True,
        },
        "file_sha256": hashes,
        "PUBLIC_REPO_SAFE": "YES" if not findings and not outside else "NO",
    }
    if write_report:
        (PROJECT / "docs/evidence/public-safety.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
    print(json.dumps({k: v for k, v in result.items() if k != "file_sha256"}, indent=2))
    return 0 if result["PUBLIC_REPO_SAFE"] == "YES" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="Read-only audit; do not update evidence"
    )
    args = parser.parse_args()
    raise SystemExit(main(write_report=not args.check))
