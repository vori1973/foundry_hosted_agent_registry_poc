import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

try:
    from .build_zip import ROOT, source_digest, validate_zip
    from .verify import new_record, safe_error, start_stage, utc_now, write_record
except ImportError:
    from build_zip import ROOT, source_digest, validate_zip
    from verify import new_record, safe_error, start_stage, utc_now, write_record


PROBE = """
import hashlib, importlib.metadata, json, pathlib, re, sys
sys.path.insert(0, '/app/packages')
digest = hashlib.sha256()
for name in ('main.py', 'requirements.txt'):
    content = pathlib.Path('/app', name).read_bytes()
    digest.update(name.encode() + b'\\0' + str(len(content)).encode() + b'\\0' + content)
for line in pathlib.Path('/app/requirements.txt').read_text().splitlines():
    pin = re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\\s;]+)', line.strip())
    if pin and importlib.metadata.version(pin[1]) != pin[2]:
        raise RuntimeError('Installed dependency differs from the runtime lock.')
print(json.dumps({'source_sha256': digest.hexdigest(), 'dependencies_match': True}))
"""


def build(zip_path, tag, runner=subprocess.run):
    if len(tag) > 200 or not re.fullmatch(
        r"[a-z0-9][a-z0-9./_-]*(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?", tag
    ):
        raise ValueError("Choose a valid isolated local image tag.")
    digest = validate_zip(zip_path)
    before = source_digest()
    existing = runner(
        ["docker", "image", "inspect", tag],
        capture_output=True, text=True, timeout=30,
    )
    if existing.returncode == 0:
        raise FileExistsError("Refusing to overwrite an existing image tag.")
    docker_version = runner(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout.strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[A-Za-z0-9.+-]*)", docker_version):
        raise ValueError("A supported Docker server is required.")
    with tempfile.TemporaryDirectory(prefix="foundry-container-") as directory:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(directory)
        runner(
            ["docker", "build", "--platform", "linux/amd64", "--tag", tag,
             "--build-context", f"runtime={directory}", str(ROOT)],
            check=True, capture_output=True, text=True, timeout=600,
        )
    image = json.loads(runner(
        ["docker", "image", "inspect", tag],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout)[0]
    image_id = image["Id"]
    layers = image["RootFS"]["Layers"]
    if (
        image.get("Os") != "linux" or image.get("Architecture") != "amd64"
        or image["Config"].get("User") != "10001:10001"
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id)
        or not layers
        or any(not re.fullmatch(r"sha256:[a-f0-9]{64}", layer) for layer in layers)
    ):
        raise ValueError("Image platform, unprivileged user, or content identities are invalid.")
    probe = json.loads(runner(
        ["docker", "run", "--rm", "--network", "none", "--read-only",
         "--entrypoint", "python", image_id, "-c", PROBE],
        check=True, capture_output=True, text=True, timeout=60,
    ).stdout)
    if (
        source_digest() != before
        or probe.get("source_sha256") != before
        or probe.get("dependencies_match") is not True
    ):
        raise ValueError("Image source or installed dependencies differ from the ZIP baseline.")
    return {
        "zip_sha256": digest,
        "source_sha256": before,
        "dependencies_sha256": hashlib.sha256((ROOT / "agent/requirements.txt").read_bytes()).hexdigest(),
        "dockerfile_sha256": hashlib.sha256((ROOT / "Dockerfile").read_bytes()).hexdigest(),
        "dockerignore_sha256": hashlib.sha256((ROOT / ".dockerignore").read_bytes()).hexdigest(),
        "image_tag": tag,
        "image_id": image_id,
        "platform": "linux/amd64",
        "layers": layers,
        "tools": {
            "docker": docker_version,
            "python": ".".join(map(str, sys.version_info[:3])),
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build one container using the validated ZIP's bundled dependencies.")
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args(argv)
    record = new_record()
    record.update({"entry_point": "docker", "method": "local"})
    path = args.evidence or ROOT / ".artifacts" / record["run_id"] / "build.json"
    if path.exists() or path.is_symlink():
        parser.error("Evidence already exists; choose a new path.")
    started = time.monotonic()
    try:
        start_stage(record, "image_build")
        built = build(args.zip, args.tag)
        record["tools"].update(built.pop("tools"))
        record.update(built)
        record["stages"]["image_build"] = "passed"
        record["status"] = "passed"
    except Exception as error:
        record["status"] = "failed"
        record["stages"][record["stage"]] = "failed"
        record["error"] = safe_error(error)
    finally:
        record["finished_at"] = utc_now()
        record["duration_seconds"] = round(time.monotonic() - started, 3)
        write_record(path, record)
    print(f"Container build {record['status']}; evidence={path}")
    if record.get("error"):
        print(f"Error code: {record['error']['code']}; inspect build prerequisites.", file=sys.stderr)
    return 0 if record["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
