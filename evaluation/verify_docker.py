"""Exercise a built image, restart persistence and optional live request. No key values in output."""

import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx

from agent_runtime.models import utcnow

IMAGE = "agent-runtime-platform:2026-09"


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()


def wait_health(base):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            response = httpx.get(base + "/health", timeout=2)
            if response.status_code == 200:
                return response.json()
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError("container health deadline exceeded")


def post(base, path, payload=None):
    response = httpx.post(base + path, json=payload, timeout=160)
    response.raise_for_status()
    return response.json()


def main():
    name = "arp-verify-" + uuid4().hex[:8]
    volume = name + "-data"
    proof = {
        "recorded_at": utcnow(),
        "image": IMAGE,
        "image_id": command("docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"),
        "docker_server": command("docker", "version", "--format", "{{.Server.Version}}"),
        "checks": {},
        "live": {"status": "not_run_no_key"},
    }
    try:
        command("docker", "volume", "create", volume)
        command(
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "-p",
            "127.0.0.1::8000",
            "-v",
            volume + ":/app/runtime-data",
            IMAGE,
        )
        base = "http://" + command("docker", "port", name, "8000/tcp").splitlines()[0]
        proof["checks"]["health"] = wait_health(base)
        states = {}
        for filename in ("direct.json", "react-offline.json", "pipeline.json"):
            states[filename] = post(
                base, "/runs", json.loads(Path("examples", filename).read_text())
            )
            assert states[filename]["status"] == "SUCCESS", filename
        assert states["direct.json"]["final_result"] == {"value": 42}
        assert states["react-offline.json"]["final_result"] == {"value": 323}
        assert states["pipeline.json"]["final_result"]["steps"]["summary"]["value"]["sum"] == 30
        assert states["pipeline.json"]["final_result"]["steps"]["unmatched"]["status"] == "SKIPPED"
        proof["checks"]["offline_runs"] = {
            k: {
                "status": v["status"],
                "request_id": v["request_id"],
                "final_result": v["final_result"],
            }
            for k, v in states.items()
        }
        request_id = states["pipeline.json"]["request_id"]
        trace = httpx.get(base + "/traces/" + request_id).json()
        assert trace["events"][-1]["kind"] == "final"
        replay = post(base, "/replay/" + request_id)
        assert replay["state"]["final_result"] == states["pipeline.json"]["final_result"]
        assert replay["state"]["llm_call_count"] == replay["state"]["tool_call_count"] == 0
        proof["checks"]["trace_event_count"] = len(trace["events"])
        proof["checks"]["deterministic_replay"] = True
        command("docker", "restart", name)
        base = "http://" + command("docker", "port", name, "8000/tcp").splitlines()[0]
        proof["checks"]["restart_health"] = wait_health(base)
        persisted = httpx.get(base + "/runs/" + request_id).json()
        assert persisted == states["pipeline.json"]
        proof["checks"]["restart_persistence"] = True
        proof["checks"]["user"] = command("docker", "exec", name, "id", "-u")
        assert proof["checks"]["user"] == "10001"
        assert (
            command("docker", "exec", name, "sh", "-c", "test ! -e /app/.env && echo absent")
            == "absent"
        )
        proof["checks"]["env_file_absent"] = True
        proof["checks"]["python"] = command("docker", "exec", name, "python", "--version")
        if os.getenv("DEEPSEEK_API_KEY"):
            live_name = name + "-live"
            try:
                # Docker takes the value from inherited environment. Never interpolate the key into argv.
                command(
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    live_name,
                    "-p",
                    "127.0.0.1::8000",
                    "-e",
                    "DEEPSEEK_API_KEY",
                    IMAGE,
                )
                live_base = (
                    "http://" + command("docker", "port", live_name, "8000/tcp").splitlines()[0]
                )
                wait_health(live_base)
                result = post(
                    live_base, "/runs", json.loads(Path("examples/react-live.json").read_text())
                )
                proof["live"] = {
                    "status": result["status"],
                    "final_result": result["final_result"],
                    "token_usage": result["token_usage"],
                    "llm_call_count": result["llm_call_count"],
                    "tool_call_count": result["tool_call_count"],
                    "latency_ms": result["latency_ms"],
                    "errors": result["errors"],
                }
                assert result["status"] == "SUCCESS" and result["final_result"] == {"value": 323}
            finally:
                command("docker", "rm", "-f", live_name)
        proof["result"] = "PASS"
    except Exception as exc:
        proof["result"] = "FAIL"
        proof["error_type"] = type(exc).__name__
        raise
    finally:
        # Preserve structured evidence even when a verification fails.
        Path("docs/evidence/docker-verification.json").write_text(
            json.dumps(proof, ensure_ascii=False, indent=2) + "\n"
        )
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
        subprocess.run(["docker", "volume", "rm", volume], capture_output=True, check=False)
    print(json.dumps(proof, indent=2))


if __name__ == "__main__":
    main()
