import argparse
import hashlib
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "agent"
MAX_ZIP_BYTES = 250 * 1024 * 1024
SOURCE_FILES = ("main.py", "requirements.txt")


def source_digest(source=SOURCE):
    digest = hashlib.sha256()
    for name in SOURCE_FILES:
        content = (source / name).read_bytes()
        digest.update(name.encode() + b"\0" + str(len(content)).encode() + b"\0" + content)
    return digest.hexdigest()


def validate_zip(path, source=SOURCE):
    if path.stat().st_size > MAX_ZIP_BYTES:
        raise ValueError("ZIP exceeds the 250 MiB upload limit.")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names) or not any(name.startswith("packages/") for name in names):
            raise ValueError("ZIP must contain unique files and bundled packages/.")
        for name in names:
            parts = name.split("/")
            if (
                name.startswith("/")
                or "\\" in name
                or any(part in {"", ".", "..", "__pycache__", ".env"} for part in parts)
                or (name not in SOURCE_FILES and not name.startswith("packages/"))
                or Path(name).suffix.lower() in {".pyc", ".pyo", ".pyd", ".dll", ".whl"}
            ):
                raise ValueError("ZIP contains an unexpected or unsafe path.")
            if (archive.getinfo(name).external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("ZIP must not contain symlinks.")
        for name in SOURCE_FILES:
            if name not in names or archive.read(name) != (source / name).read_bytes():
                raise ValueError("ZIP source/dependencies do not match the current agent.")
        if archive.testzip() is not None:
            raise ValueError("ZIP integrity check failed.")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(output, source=SOURCE, runner=subprocess.run):
    if output.exists() or output.is_symlink() or output.with_suffix(".zip.sha256").exists():
        raise FileExistsError("Refusing to overwrite an existing ZIP or digest.")
    before = source_digest(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="foundry-agent-") as directory:
        packages = Path(directory) / "packages"
        try:
            runner(
                [
                    sys.executable, "-m", "pip", "install", "--quiet", "--no-compile",
                    "--disable-pip-version-check", "-r", str(source / "requirements.txt"),
                    "--target", str(packages), "--platform", "manylinux2014_x86_64",
                    "--python-version", "3.13", "--implementation", "cp", "--only-binary=:all:",
                ],
                check=True, capture_output=True, text=True,
            )
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("Bundling failed; verify pip, binary wheel availability, and approved package access.") from None
        if source_digest(source) != before:
            raise ValueError("Agent source changed during packaging; rebuild from a stable source.")
        created = False
        try:
            with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
                created = True
                for name in SOURCE_FILES:
                    archive.write(source / name, name)
                for path in sorted(packages.rglob("*")):
                    if path.is_symlink():
                        raise ValueError("Bundled dependencies contain a symlink.")
                    if not path.is_file() or "__pycache__" in path.parts:
                        continue
                    if path.suffix.lower() in {".pyc", ".pyo"}:
                        continue
                    archive.write(path, "packages/" + path.relative_to(packages).as_posix())
            digest = validate_zip(output, source)
            with output.with_suffix(".zip.sha256").open("x", encoding="ascii") as stream:
                stream.write(f"{digest}  {output.name}\n")
        except Exception:
            if created:
                output.unlink(missing_ok=True)
            raise
    return digest


def main():
    parser = argparse.ArgumentParser(description="Build a bundled Linux Python 3.13 agent ZIP.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts" / stamp / "agent.zip")
    args = parser.parse_args()
    try:
        digest = build(args.output)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile):
        parser.exit(1, "ZIP build failed; check output availability, source, pip and binary dependency compatibility.\n")
    print(f"ZIP: {args.output}\nSHA256: {digest}\nSource: {source_digest()}")


if __name__ == "__main__":
    main()
