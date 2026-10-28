import hashlib
import io
import json
import subprocess
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import httpx
from azure.core.credentials import AccessToken

from scripts import local_azure_cli, local_smoke
from scripts.build_zip import ROOT, source_digest
from scripts.preflight import Configuration
from scripts.verify import VerificationBlocked, new_record
from test_preflight import ENV


class LocalIdentityTests(unittest.TestCase):
    def test_adapter_accepts_only_unexpired_audience_scoped_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token.json"
            for expiry, result in ((time.time() + 600, 0), (time.time() - 1, 1)):
                path.write_text(json.dumps({"accessToken": "synthetic-token", "expires_on": expiry}))
                output, error = io.StringIO(), io.StringIO()
                with patch.object(local_azure_cli, "TOKEN_FILE", path), redirect_stdout(output), redirect_stderr(error):
                    self.assertEqual(local_azure_cli.main([
                        "account", "get-access-token", "--resource", "https://ai.azure.com", "--output", "json",
                    ]), result)
                self.assertNotIn("synthetic-token", error.getvalue())
                if result:
                    self.assertNotIn("synthetic-token", output.getvalue())
                else:
                    self.assertEqual(json.loads(output.getvalue())["accessToken"], "synthetic-token")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                local_azure_cli.main([
                    "account", "get-access-token", "--resource", "https://management.azure.com", "--output", "json",
                ])


class LocalSmokeTests(unittest.TestCase):
    def setUp(self):
        self.config = Configuration.from_env("zip", "local-test", timeout=1, env=ENV)
        self.zip = new_record(self.config)
        self.zip.update({
            "status": "passed", "stage": "verification", "agent_version": "1",
            "zip_sha256": "c" * 64,
            "smoke": {
                "status": "passed", "response_status": "completed",
                "assertions": dict.fromkeys(("nonempty", "marker", "name", "source"), True),
            },
        })
        self.build = {
            "method": "local", "status": "passed", "stage": "image_build",
            "source_sha256": source_digest(), "dependencies_sha256": self.zip["dependencies_sha256"],
            "zip_sha256": "c" * 64, "platform": "linux/amd64", "image_id": "sha256:" + "a" * 64,
            "layers": ["sha256:" + "b" * 64],
            "dockerfile_sha256": hashlib.sha256((ROOT / "Dockerfile").read_bytes()).hexdigest(),
            "dockerignore_sha256": hashlib.sha256((ROOT / ".dockerignore").read_bytes()).hexdigest(),
        }
        self.commands = []
        self.inputs = []
        self.post_count = 0
        self.fail_model = False

    def docker(self, command, **kwargs):
        self.commands.append(command)
        result = subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[1:3] == ["image", "inspect"]:
            result.stdout = json.dumps([{
                "Id": self.build["image_id"], "Os": "linux", "Architecture": "amd64",
                "RootFS": {"Layers": self.build["layers"]},
            }])
        elif command[1] == "run":
            result.stdout = "d" * 64
        elif command[1] == "exec" and "input" in kwargs:
            self.inputs.append(json.loads(kwargs["input"]))
        elif command[1] == "port":
            result.stdout = "127.0.0.1:12345\n"
        elif command[1:3] == ["container", "inspect"]:
            result.stdout = "true\n"
        return result

    def http(self, request):
        if request.url.path == "/readiness":
            return httpx.Response(200, json={"status": "ready"})
        self.post_count += 1
        if self.fail_model:
            return httpx.Response(200, json={"status": "failed", "error": {"message": "synthetic-secret"}})
        prompt = json.loads(request.content)["input"]
        return httpx.Response(200, json={
            "id": "test-response", "status": "completed",
            "output": [{"content": [{"type": "output_text", "text": "local-test zip " + prompt}]}],
        })

    def test_mismatched_or_failed_predecessors_stop_before_docker(self):
        local_smoke.require_build(self.config, self.zip, self.build)
        for key, value in (
            ("baseline_fingerprint", "stale"), ("status", "failed"), ("zip_sha256", "0" * 64),
        ):
            with self.subTest(key=key), self.assertRaises(VerificationBlocked):
                local_smoke.require_build(self.config, {**self.zip, key: value}, self.build)
        with self.assertRaises(VerificationBlocked):
            local_smoke.require_build(self.config, self.zip, {**self.build, "dockerfile_sha256": "stale"})

    def test_one_model_request_runtime_only_identity_and_cleanup(self):
        factory = httpx.Client
        transport = httpx.MockTransport(self.http)
        record = new_record(self.config)
        with patch.object(local_smoke.httpx, "Client", side_effect=lambda **kw: factory(transport=transport, **kw)):
            result = local_smoke.run_local(
                self.config, self.build, AccessToken("synthetic-secret", time.time() + 600), record, self.docker,
            )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(self.post_count, 1)
        command = next(command for command in self.commands if command[1] == "run")
        self.assertIn("127.0.0.1::8088", command)
        self.assertIn("--read-only", command)
        self.assertIn(
            "/run/poc-identity:rw,exec,nosuid,nodev,size=1m,uid=10001,gid=10001,mode=0700", command,
        )
        self.assertTrue(any(local_smoke.CHECK_IDENTITY in command for command in self.commands))
        self.assertNotIn("synthetic-secret", json.dumps(self.commands))
        self.assertNotIn("synthetic-secret", json.dumps(record))
        self.assertEqual(self.inputs[0]["token"]["accessToken"], "synthetic-secret")
        self.assertTrue(any(command[1] == "stop" for command in self.commands))
        self.assertEqual(record["cleanup_status"], "passed")

    def test_failed_model_is_not_retried_and_container_is_stopped(self):
        self.fail_model = True
        factory = httpx.Client
        transport = httpx.MockTransport(self.http)
        with patch.object(local_smoke.httpx, "Client", side_effect=lambda **kw: factory(transport=transport, **kw)):
            with self.assertRaises(RuntimeError):
                local_smoke.run_local(
                    self.config, self.build, AccessToken("synthetic-secret", time.time() + 600),
                    new_record(self.config), self.docker,
                )
        self.assertEqual(self.post_count, 1)
        self.assertTrue(any(command[1] == "stop" for command in self.commands))

    def test_startup_error_is_not_hidden_by_cleanup_failure(self):
        record = new_record(self.config)
        docker = self.docker

        def fail(command, **kwargs):
            if command[1:3] == ["container", "inspect"]:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
            if command[1] == "stop":
                raise subprocess.CalledProcessError(1, command, stderr="synthetic-secret")
            return docker(command, **kwargs)

        with (
            patch.object(local_smoke.time, "monotonic", return_value=0),
            self.assertRaisesRegex(RuntimeError, "exited before readiness"),
        ):
            local_smoke.run_local(
                self.config, self.build, AccessToken("synthetic-secret", time.time() + 600), record, fail,
            )
        self.assertEqual(record["cleanup_status"], "failed")
        self.assertEqual(self.post_count, 0)

    def test_approval_is_checked_before_token_or_docker_access(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "smoke.json"
            with patch.object(local_smoke, "AzureCliCredential") as credential:
                result = local_smoke.main([
                    "--name", "local-test", "--zip-evidence", "missing", "--build-evidence", "missing",
                    "--evidence", str(path),
                ])
            self.assertEqual(result, 1)
            credential.assert_not_called()
            self.assertEqual(json.loads(path.read_text())["error"]["field"], "approve_cloud")


if __name__ == "__main__":
    unittest.main()
