import argparse
import json
import logging
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
from azure.identity import AzureCliCredential

try:
    from .build_zip import ROOT
    from .preflight import Configuration, InputError, positive_timeout, tool_versions
    from .verify import (
        VerificationBlocked, assert_smoke, new_record, read_record, require_build,
        safe_error, smoke_payload, start_stage, utc_now, write_record,
    )
except ImportError:
    from build_zip import ROOT
    from preflight import Configuration, InputError, positive_timeout, tool_versions
    from verify import (
        VerificationBlocked, assert_smoke, new_record, read_record, require_build,
        safe_error, smoke_payload, start_stage, utc_now, write_record,
    )


WAIT_FOR_IDENTITY = """
import os, pathlib, sys, time
deadline = time.monotonic() + 60
while not pathlib.Path('/run/poc-identity/ready').exists():
    if time.monotonic() >= deadline:
        raise SystemExit('Local identity setup did not complete.')
    time.sleep(0.1)
os.execv(sys.executable, [sys.executable, 'main.py'])
"""

INSTALL_IDENTITY = """
import json, pathlib, sys
data = json.load(sys.stdin)
root = pathlib.Path('/run/poc-identity')
for name, content, mode in (
    ('token.json', json.dumps(data['token']), 0o400),
    ('az', data['adapter'], 0o500),
    ('ready', '', 0o400),
):
    path = root / name
    path.write_text(content)
    path.chmod(mode)
root.chmod(0o500)
"""

CHECK_IDENTITY = """
import asyncio, sys
sys.path.insert(0, '/app/packages')
from azure.identity.aio import DefaultAzureCredential
async def check():
    async with DefaultAzureCredential() as credential:
        await credential.get_token('https://ai.azure.com/.default')
asyncio.run(check())
"""


def run_local(config, build, token, record, runner=subprocess.run):
    image_id = build["image_id"]
    image = json.loads(runner(
        ["docker", "image", "inspect", image_id],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout)[0]
    if (
        image.get("Id") != image_id or image.get("Os") != "linux"
        or image.get("Architecture") != "amd64"
        or image.get("RootFS", {}).get("Layers") != build.get("layers")
    ):
        raise VerificationBlocked("The immutable local image does not match build evidence.")
    container_id = None
    try:
        start_stage(record, "local_identity")
        container_id = runner(
            ["docker", "run", "--detach", "--rm", "--read-only",
             "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
             "--cpus", config.cpu, "--memory", "1g",
             "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
             "--tmpfs", "/run/poc-identity:rw,exec,nosuid,nodev,size=1m,uid=10001,gid=10001,mode=0700",
             "--publish", "127.0.0.1::8088",
             "--env", f"FOUNDRY_PROJECT_ENDPOINT={config.endpoint}",
             "--env", f"AZURE_AI_MODEL_DEPLOYMENT_NAME={config.model}",
             "--env", f"AGENT_NAME={config.name}",
             "--env", "DEPLOYMENT_SOURCE=zip",
             "--env", "AZURE_TOKEN_CREDENTIALS=AzureCliCredential",
             "--env", "PATH=/run/poc-identity:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin",
             "--entrypoint", "python", image_id, "-c", WAIT_FOR_IDENTITY],
            check=True, capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        if not re.fullmatch(r"[a-f0-9]{64}", container_id):
            raise RuntimeError("Docker returned an invalid container identity.")
        record["container_id"] = container_id
        payload = {
            "token": {"accessToken": token.token, "expires_on": token.expires_on},
            "adapter": (ROOT / "scripts/local_azure_cli.py").read_text(),
        }
        runner(
            ["docker", "exec", "--interactive", container_id, "python", "-c", INSTALL_IDENTITY],
            input=json.dumps(payload), check=True, capture_output=True, text=True, timeout=30,
        )
        runner(
            ["docker", "exec", container_id, "python", "-c", CHECK_IDENTITY],
            check=True, capture_output=True, text=True, timeout=30,
        )
        address = runner(
            ["docker", "port", container_id, "8088/tcp"],
            check=True, capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        if not re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", address):
            raise RuntimeError("The local Responses endpoint is not loopback-only.")
        start_stage(record, "readiness")
        deadline = time.monotonic() + config.timeout
        with httpx.Client(base_url=f"http://{address}", timeout=min(config.timeout, 60), trust_env=False) as client:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Local readiness deadline expired.")
                running = runner(
                    ["docker", "container", "inspect", "--format", "{{.State.Running}}", container_id],
                    capture_output=True, text=True, timeout=30,
                )
                if running.returncode or running.stdout.strip() != "true":
                    raise RuntimeError("The local container exited before readiness.")
                try:
                    ready = client.get("/readiness", timeout=min(remaining, 2))
                    if ready.status_code == 200 and time.monotonic() < deadline:
                        break
                except httpx.TransportError:
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError("Local readiness deadline expired.")
                time.sleep(min(0.25, max(0, deadline - time.monotonic())))
            start_stage(record, "verification")
            request, marker = smoke_payload(config.name, "zip")
            response = client.post("/responses", json=request)
            response.raise_for_status()
            return assert_smoke(response.json(), config.name, "zip", marker)
    finally:
        if container_id and re.fullmatch(r"[a-f0-9]{64}", container_id):
            failed = sys.exc_info()[0] is not None
            try:
                runner(
                    ["docker", "stop", "--time", "5", container_id],
                    capture_output=True, text=True, timeout=30,
                )
                remaining = runner(
                    ["docker", "container", "ls", "--all", "--filter", f"id={container_id}", "--format", "{{.ID}}"],
                    check=True, capture_output=True, text=True, timeout=30,
                )
                if remaining.stdout.strip():
                    raise RuntimeError("Local test cleanup failed; stop the recorded container.")
                record["cleanup_status"] = "passed"
            except Exception:
                record["cleanup_status"] = "failed"
                if not failed:
                    raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run one approved local-container Responses model smoke.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--zip-evidence", type=Path, required=True)
    parser.add_argument("--build-evidence", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--timeout", type=positive_timeout, default=60)
    parser.add_argument("--approve-cloud", action="store_true")
    args = parser.parse_args(argv)
    record = new_record()
    path = args.evidence or ROOT / ".artifacts" / record["run_id"] / "local-smoke.json"
    if path.exists() or path.is_symlink():
        parser.error("Evidence already exists; choose a new path.")
    started = time.monotonic()
    logging.getLogger("azure").setLevel(logging.WARNING)
    try:
        if not args.approve_cloud:
            raise InputError("approve_cloud", "Explicit model inference approval is required.")
        config = Configuration.from_env("zip", args.name, timeout=args.timeout)
        context = new_record(config)
        context["run_id"], context["started_at"] = record["run_id"], record["started_at"]
        record.update(context)
        record.update({"entry_point": "docker", "method": "local", "deployment_source": "zip"})
        record["tools"].update(tool_versions(container=True))
        build = read_record(args.build_evidence)
        require_build(config, read_record(args.zip_evidence), build)
        for key in (
            "image_id", "image_tag", "platform", "layers", "zip_sha256",
            "dockerfile_sha256", "dockerignore_sha256",
        ):
            record[key] = build[key]
        start_stage(record, "local_identity")
        with AzureCliCredential() as credential:
            token = credential.get_token("https://ai.azure.com/.default")
        if not time.time() + config.timeout + 30 < token.expires_on <= time.time() + 7200:
            raise InputError("local_identity", "A short-lived token with enough remaining lifetime is required.")
        record["identity_type"] = "short-lived-azure-cli-token-in-tmpfs"
        record["smoke"] = run_local(config, build, token, record)
        record["stages"]["verification"] = "passed"
        record["status"] = "passed"
    except Exception as error:
        record["status"] = "blocked" if isinstance(error, (InputError, VerificationBlocked)) else "failed"
        record["stages"][record["stage"]] = record["status"]
        record["error"] = safe_error(error)
    finally:
        record["finished_at"] = utc_now()
        record["duration_seconds"] = round(time.monotonic() - started, 3)
        write_record(path, record)
    print(f"Local smoke {record['status']}; stage={record['stage']}; evidence={path}")
    if record.get("error"):
        print(f"Error code: {record['error']['code']}; retain this run before retrying.", file=sys.stderr)
    return 0 if record["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
