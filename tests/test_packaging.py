import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import build_container, build_zip


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "agent"
        self.source.mkdir()
        for name in build_zip.SOURCE_FILES:
            (self.source / name).write_text("# test\n")
        (self.source / ".env").write_text("test-only-secret")
        (self.source / "deploy.py").write_text("# not runtime\n")
        self.output = self.root / "output" / "agent.zip"
        self.commands = []

    def bundle(self, command, **kwargs):
        self.commands.append(command)
        packages = Path(command[command.index("--target") + 1])
        packages.mkdir()
        (packages / "dependency.py").write_text("# Linux runtime dependency\n")
        (packages / "__pycache__").mkdir()
        (packages / "__pycache__" / "dependency.pyc").write_bytes(b"cache")

    def test_build_integrity_digest_layout_and_platform(self):
        digest = build_zip.build(self.output, self.source, self.bundle)
        self.assertEqual(digest, hashlib.sha256(self.output.read_bytes()).hexdigest())
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(set(archive.namelist()), {
                "main.py", "requirements.txt", "packages/dependency.py",
            })
            self.assertIsNone(archive.testzip())
        self.assertIn("manylinux2014_x86_64", self.commands[0])
        self.assertIn("3.13", self.commands[0])
        self.assertIn("--only-binary=:all:", self.commands[0])
        self.assertIn(digest, self.output.with_suffix(".zip.sha256").read_text())

    def test_refuses_overwrite_and_detects_changed_source(self):
        build_zip.build(self.output, self.source, self.bundle)
        with self.assertRaises(FileExistsError):
            build_zip.build(self.output, self.source, self.bundle)
        (self.source / "main.py").write_text("# changed\n")
        with self.assertRaises(ValueError):
            build_zip.validate_zip(self.output, self.source)

    def test_unsafe_archive_and_size_limit(self):
        self.output.parent.mkdir()
        with zipfile.ZipFile(self.output, "w") as archive:
            for name in build_zip.SOURCE_FILES:
                archive.write(self.source / name, name)
            archive.writestr("packages/../../.env", "test-only-secret")
        with self.assertRaises(ValueError):
            build_zip.validate_zip(self.output, self.source)
        with patch.object(build_zip, "MAX_ZIP_BYTES", 1), self.assertRaises(ValueError):
            build_zip.validate_zip(self.output, self.source)

    def test_bundle_failure_does_not_create_zip_or_expose_error(self):
        def fail(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "pip", stderr="test-secret")
        with self.assertRaises(RuntimeError) as caught:
            build_zip.build(self.output, self.source, fail)
        self.assertNotIn("test-secret", str(caught.exception))
        self.assertFalse(self.output.exists())

    def test_rejects_source_change_during_bundling(self):
        def change(command, **kwargs):
            self.bundle(command, **kwargs)
            (self.source / "main.py").write_text("# changed\n")
        with self.assertRaises(ValueError):
            build_zip.build(self.output, self.source, change)
        self.assertFalse(self.output.exists())


class ContainerBuildTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.zip = Path(self.directory.name) / "agent.zip"
        with zipfile.ZipFile(self.zip, "w") as archive:
            for name in build_zip.SOURCE_FILES:
                archive.write(build_zip.SOURCE / name, name)
            archive.writestr("packages/dependency.py", "# bundled dependency\n")
        self.commands = []
        self.inspect_calls = 0
        self.platform = "amd64"
        self.probe_source = build_zip.source_digest()

    def docker(self, command, **kwargs):
        self.commands.append(command)
        result = subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[1:3] == ["image", "inspect"]:
            self.inspect_calls += 1
            if self.inspect_calls == 1:
                result.returncode = 1
            else:
                result.stdout = json.dumps([{
                    "Id": "sha256:" + "a" * 64, "Os": "linux",
                    "Architecture": self.platform, "Config": {"User": "10001:10001"},
                    "RootFS": {"Layers": ["sha256:" + "b" * 64]},
                }])
        elif command[1] == "build":
            context = Path(command[command.index("--build-context") + 1].split("=", 1)[1])
            self.assertTrue((context / "packages/dependency.py").is_file())
            self.assertFalse((context / ".env").exists())
        elif command[1] == "version":
            result.stdout = "29.1.5\n"
        elif command[1] == "run":
            result.stdout = json.dumps({
                "source_sha256": self.probe_source, "dependencies_match": True,
            })
        return result

    def test_build_reuses_zip_payload_and_inspects_immutable_image(self):
        result = build_container.build(self.zip, "poc:20261027T231555Z", self.docker)
        self.assertEqual(result["zip_sha256"], build_zip.validate_zip(self.zip))
        self.assertEqual(result["source_sha256"], build_zip.source_digest())
        run = self.commands[-1]
        self.assertIn("--read-only", run)
        self.assertEqual(run[run.index("--network") + 1], "none")
        self.assertIn(result["image_id"], run)
        command = next(command for command in self.commands if command[1] == "build")
        context = command[command.index("--build-context") + 1].split("=", 1)[1]
        self.assertFalse(Path(context).exists())

    def test_wrong_platform_or_source_blocks_build_acceptance(self):
        for platform, source in (("arm64", self.probe_source), ("amd64", "0" * 64)):
            with self.subTest(platform=platform):
                self.inspect_calls = 0
                self.platform, self.probe_source = platform, source
                with self.assertRaises(ValueError):
                    build_container.build(self.zip, "poc:test", self.docker)

    def test_invalid_archive_or_existing_tag_cannot_start_build(self):
        with patch.object(build_container, "validate_zip", side_effect=ValueError("invalid")):
            with self.assertRaises(ValueError):
                build_container.build(self.zip, "poc:test", self.docker)
        self.assertFalse(self.commands)
        self.inspect_calls = 1
        with self.assertRaises(FileExistsError):
            build_container.build(self.zip, "poc:test", self.docker)
        self.assertEqual(len(self.commands), 1)

    def test_build_failure_is_sanitized_and_preserves_failed_evidence(self):
        evidence = Path(self.directory.name) / "build.json"
        error = subprocess.CalledProcessError(1, ["docker"], stderr="test-secret")
        with patch.object(build_container, "build", side_effect=error):
            self.assertEqual(build_container.main([
                "--zip", str(self.zip), "--tag", "poc:test", "--evidence", str(evidence),
            ]), 1)
        record = evidence.read_text()
        self.assertNotIn("test-secret", record)
        self.assertEqual(json.loads(record)["stages"]["image_build"], "failed")


if __name__ == "__main__":
    unittest.main()
