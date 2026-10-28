import json
import base64
import hashlib
import os
import subprocess
import tempfile
import tarfile
import unittest
import time
from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from scripts import publish
from scripts.preflight import Configuration, InputError
from scripts.verify import new_record, write_record
from test_preflight import ENV, JFROG_ENV


def group_token(**changes):
    scope_key = "scp" if "scp" in changes else "scope"
    claims = {
        "sub": "jfrt@test/users/publisher", scope_key: "applied-permissions/groups:poc-publish",
        "iat": int(time.time()), "exp": int(time.time()) + 3600,
        **changes,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return "synthetic." + encoded + ".signature"


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.config = Configuration.from_env("zip", "publication-test", env=ENV)
        self.runtime = "11111111-1111-1111-1111-111111111111"
        self.publisher = "22222222-2222-2222-2222-222222222222"
        self.local = {"image_id": "sha256:" + "a" * 64, "layers": ["sha256:" + "b" * 64]}
        self.commands, self.config_dirs = [], []
        self.config_content = json.dumps({
            "os": "linux", "architecture": "amd64", "rootfs": {"diff_ids": self.local["layers"]},
        }).encode()
        self.remote_config = "sha256:" + hashlib.sha256(self.config_content).hexdigest()
        self.runtime_role = "AcrPull"
        self.push_error = False

    def run_command(self, command, **kwargs):
        self.commands.append(command)
        result = subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if kwargs.get("env"):
            directory = kwargs["env"]["DOCKER_CONFIG"]
            self.config_dirs.append(directory)
            self.assertTrue(Path(directory).is_dir())
        if command[:3] == ["az", "acr", "show"]:
            value = {
                "id": "/subscriptions/sub/resourceGroups/group/providers/Microsoft.ContainerRegistry/registries/testacr",
                "loginServer": "testacr.azurecr.io", "roleAssignmentMode": "LegacyRegistryPermissions",
            }
        elif command[:3] == ["az", "resource", "show"]:
            value = {"identity": {"principalId": self.runtime}}
        elif command[:4] == ["az", "role", "assignment", "list"]:
            value = [
                {"principalId": self.runtime, "role": self.runtime_role, "scope": "registry", "condition": None},
                {"principalId": self.publisher, "role": "AcrPush", "scope": "registry", "condition": None},
            ]
        elif command[:4] == ["az", "acr", "config", "authentication-as-arm"]:
            value = {"status": "enabled"}
        elif command[:3] == ["docker", "image", "inspect"]:
            value = [{"Id": self.local["image_id"], "RootFS": {"Layers": self.local["layers"]}}]
        elif command[:3] == ["docker", "image", "save"]:
            with tarfile.open(command[command.index("--output") + 1], "w") as archive:
                for name, content in (
                    ("manifest.json", json.dumps([{"Config": "config.json"}]).encode()),
                    ("config.json", self.config_content),
                ):
                    member = tarfile.TarInfo(name)
                    member.size = len(content)
                    archive.addfile(member, BytesIO(content))
            return result
        elif command[:4] == ["docker", "buildx", "imagetools", "inspect"]:
            if "--raw" in command:
                value = {"config": {"digest": self.remote_config}, "layers": [{"digest": "sha256:" + "d" * 64}]}
            else:
                value = {"manifests": [
                    {"digest": "sha256:" + "e" * 64, "platform": {"os": "unknown", "architecture": "unknown"}},
                    {"digest": "sha256:" + "c" * 64, "platform": {"os": "linux", "architecture": "amd64"}},
                ]}
        else:
            if command[:2] == ["docker", "push"] and self.push_error:
                raise subprocess.CalledProcessError(1, command, stderr="synthetic-secret")
            return result
        result.stdout = json.dumps(value)
        return result

    def publish(self, existing=False):
        with patch.object(publish, "publisher_object_id", return_value=self.publisher):
            return publish.publish_acr(
                self.config, "testacr", "agents/test", "test-run", self.local, new_record(), self.run_command,
                existing=existing,
            )

    def test_one_existing_build_is_pushed_and_immutable_platform_content_is_checked(self):
        result = self.publish()
        self.assertEqual(result["image_reference"], "testacr.azurecr.io/agents/test@sha256:" + "c" * 64)
        self.assertTrue(any(command[:3] == ["docker", "tag", self.local["image_id"]] for command in self.commands))
        self.assertEqual(sum(command[:2] == ["docker", "push"] for command in self.commands), 1)
        self.assertFalse(any(command[:2] == ["docker", "build"] for command in self.commands))
        self.assertFalse(any(Path(directory).exists() for directory in self.config_dirs))

    def test_retained_publication_can_be_verified_without_another_push(self):
        result = self.publish(existing=True)
        self.assertIn("@sha256:", result["image_reference"])
        self.assertFalse(any(command[:2] in (["docker", "tag"], ["docker", "push"]) for command in self.commands))

    def test_remote_content_mismatch_and_push_failure_cannot_pass(self):
        self.remote_config = "sha256:" + "0" * 64
        with self.assertRaises(InputError):
            self.publish()
        self.commands.clear()
        self.push_error = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish()
        self.assertFalse(any(command[:3] == ["docker", "buildx", "imagetools"] for command in self.commands))
        self.assertFalse(any(Path(directory).exists() for directory in self.config_dirs))

    def test_publisher_permission_is_not_accepted_as_runtime_pull_permission(self):
        self.runtime_role = "Reader"
        with self.assertRaises(InputError):
            self.publish()
        self.assertFalse(any(command[:3] == ["az", "acr", "login"] for command in self.commands))
        self.assertFalse(any(command[:2] == ["docker", "push"] for command in self.commands))

    def test_missing_predecessor_evidence_blocks_before_credentials_or_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "publication.json"
            with patch.dict(os.environ, ENV, clear=True), \
                    patch.object(publish, "publish_acr") as publish_image, \
                    patch.object(publish, "tool_versions") as tools, \
                    redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(publish.main([
                    "--method", "acr", "--registry", "testacr", "--repository", "agents/test",
                    "--zip-evidence", str(Path(directory) / "missing.json"),
                    "--local-evidence", str(Path(directory) / "missing-local.json"),
                    "--approve-cloud", "--evidence", str(path),
                ]), 1)
            publish_image.assert_not_called()
            tools.assert_not_called()
            self.assertEqual(json.loads(path.read_text())["status"], "blocked")

    def jfrog_publication(self, *, existing=False):
        record = new_record(self.config)
        acr = {
            "config_sha256": self.remote_config, "registry_layers": ["sha256:" + "d" * 64],
            "manifest_sha256": "sha256:" + "c" * 64,
        }
        runner, token = Mock(side_effect=self.run_command), group_token()
        with patch.dict(os.environ, JFROG_ENV, clear=True), \
                patch.object(publish, "check_jfrog_connection", return_value={"connection_preflight": "passed"}), \
                patch.object(publish, "independent_jfrog_pull") as pull:
            self.last_pull = pull
            result = publish.publish_jfrog(
                self.config, "registry.example.com", "repository/agent", "test-run",
                self.local, record, acr, "poc-publish", runner,
                existing=existing, token_reader=lambda: token,
            )
        return result, record, runner, pull, token

    def test_jfrog_publishes_same_build_and_independently_pulls_without_acr_relay(self):
        result, record, runner, pull, token = self.jfrog_publication()
        self.assertTrue(result["image_reference"].startswith("registry.example.com/repository/agent@sha256:"))
        self.assertEqual(record["manifest_comparison"], "identical")
        self.assertEqual(record["independent_pull"], "passed")
        pull.assert_called_once()
        self.assertEqual(sum(command[:2] == ["docker", "push"] for command in self.commands), 1)
        self.assertFalse(any(command[0] == "az" or "build" in command or "import" in command for command in self.commands))
        login = next(call for call in runner.call_args_list if call.args[0][:2] == ["docker", "login"])
        self.assertEqual(login.kwargs["input"], token)
        for call in runner.call_args_list:
            self.assertNotIn(token, repr(call.args))
            self.assertNotIn(token, repr(call.kwargs.get("env")))
        self.assertFalse(any(Path(directory).exists() for directory in self.config_dirs))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "publication.json"
            write_record(path, record)
            self.assertNotIn(token, path.read_text())
            self.assertEqual(json.loads(path.read_text())["independent_pull"], "passed")

    def test_jfrog_retained_tag_skips_push_but_still_checks_content_and_pulls(self):
        _, _, _, pull, _ = self.jfrog_publication(existing=True)
        pull.assert_called_once()
        self.assertFalse(any(command[:2] in (["docker", "tag"], ["docker", "push"]) for command in self.commands))

    def test_jfrog_different_layers_or_failed_push_never_qualifies_as_a_pull(self):
        original = self.run_command

        def altered(command, **kwargs):
            result = original(command, **kwargs)
            if "--raw" in command:
                body = json.loads(result.stdout)
                body["layers"][0]["digest"] = "sha256:" + "0" * 64
                result.stdout = json.dumps(body)
            return result

        with patch.object(self, "run_command", side_effect=altered):
            with self.assertRaises(InputError):
                self.jfrog_publication()
            self.last_pull.assert_not_called()
        self.push_error = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.jfrog_publication()
        self.assertFalse(any(Path(directory).exists() for directory in self.config_dirs))

    def test_jfrog_requires_acr_publication_before_tool_checks_or_credentials(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, ENV, clear=True), \
                patch.object(publish, "read_record", return_value={}), \
                patch.object(publish, "require_baselines"), \
                patch.object(publish, "tool_versions") as tools, \
                patch.object(publish, "publish_jfrog") as publish_image, \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(publish.main([
                "--method", "jfrog", "--registry", "registry.example.com", "--repository", "repository/agent",
                "--zip-evidence", "zip.json", "--local-evidence", "local.json",
                "--approve-cloud", "--evidence", str(Path(directory) / "publication.json"),
            ]), 1)
        tools.assert_not_called()
        publish_image.assert_not_called()

    def test_publisher_token_rejects_admin_runtime_long_lived_and_expired_credentials(self):
        self.assertEqual(publish.publisher_token_identity(group_token(), "poc-publish"), "publisher")
        for changes in (
            {"scope": "applied-permissions/admin"},
            {"scope": "applied-permissions/groups:poc-pull"},
            {"scope": "applied-permissions/user applied-permissions/groups:poc-publish"},
            {"scope": None}, {"sub": None},
            {"exp": int(time.time()) - 1}, {"exp": int(time.time()) + 86400},
        ):
            with self.subTest(changes=changes), self.assertRaises(InputError):
                publish.publisher_token_identity(group_token(**changes), "poc-publish")
        with self.assertRaises(InputError):
            publish.publisher_token_identity("not-a-jwt", "poc-publish")

    def test_jfrog_quoted_group_scopes_accept_only_the_selected_group(self):
        for scope in (
            'applied-permissions/groups:"poc-publish"',
            'applied-permissions/groups:"poc-publish",',
            'api:* applied-permissions/groups:"poc-publish",',
        ):
            with self.subTest(scope=scope):
                self.assertEqual(publish.publisher_token_identity(group_token(scope=scope), "poc-publish"), "publisher")
        for scope in (
            'applied-permissions/groups:"poc-publish","other"',
            'applied-permissions/groups:"poc-publish" applied-permissions/admin',
            'applied-permissions/groups:"poc-publish" applied-permissions/user',
            'applied-permissions/groups:"poc-publish" applied-permissions/groups:other',
            'applied-permissions/groups:"poc-pull",',
            'applied-permissions/groups:"poc-publish",,',
            'applied-permissions/groups:"poc-publish',
        ):
            with self.subTest(scope=scope), self.assertRaises(InputError) as caught:
                publish.publisher_token_identity(group_token(scope=scope), "poc-publish")
            self.assertEqual(caught.exception.field, "publisher_token_scope")

    def test_jfrog_scp_claim_accepts_strings_and_arrays_without_ignoring_conflicting_scope(self):
        group_scope = 'applied-permissions/groups:"poc-publish",'
        for changes in (
            {"scp": group_scope},
            {"scp": "api:* " + group_scope},
            {"scp": [group_scope]},
            {"scp": ["api:*", group_scope]},
            {"scp": [group_scope], "scope": "applied-permissions/groups:poc-publish"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(publish.publisher_token_identity(group_token(**changes), "poc-publish"), "publisher")
        for changes in (
            {"scp": None}, {"scp": []}, {"scp": {}}, {"scp": [None]},
            {"scp": [group_scope, ""]},
            {"scp": [group_scope, "applied-permissions/admin"]},
            {"scp": [group_scope, "applied-permissions/user"]},
            {"scp": [group_scope, "applied-permissions/groups:other"]},
            {"scp": ['applied-permissions/groups:"poc-publish","other"']},
            {"scp": ["applied-permissions/groups:*"]},
            {"scp": [group_scope], "scope": "applied-permissions/admin"},
            {"scp": ["applied-permissions/admin"], "scope": group_scope},
            {"scp": None, "scope": group_scope},
        ):
            with self.subTest(changes=changes), self.assertRaises(InputError) as caught:
                publish.publisher_token_identity(group_token(**changes), "poc-publish")
            self.assertEqual(caught.exception.field, "publisher_token_scope")

    def test_publisher_input_diagnostics_distinguish_paste_format_scope_and_expiry_without_echo(self):
        for token, field in (
            ("", "publisher_token_empty"),
            ("synthetic-secret-reference-token", "publisher_token_format"),
            (group_token(scope="applied-permissions/admin"), "publisher_token_scope"),
            (group_token(sub="synthetic-secret"), "publisher_token_identity"),
            (group_token(exp=int(time.time()) - 1), "publisher_token_expiry"),
        ):
            with self.subTest(field=field), self.assertRaises(InputError) as caught:
                publish.publisher_token_identity(token, "poc-publish")
            self.assertEqual(caught.exception.field, field)
            self.assertNotIn("synthetic-secret", str(caught.exception))
            self.assertNotIn("synthetic-secret", publish.PUBLISHER_AUTH_HINTS[field])
        with patch.object(publish.sys.stdin, "isatty", return_value=True), \
                patch.object(publish.getpass, "getpass", return_value="  synthetic-token \t"):
            self.assertEqual(publish.read_publisher_token(), "synthetic-token")

    def test_owner_only_external_token_file_bypasses_terminal_input_without_echo(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "publisher-token"
            token = group_token()
            path.write_bytes(b"\xef\xbb\xbf" + token.encode() + b"\n")
            path.chmod(0o600)
            output, errors = StringIO(), StringIO()
            with patch.object(publish.getpass, "getpass") as prompt, \
                    redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(publish.read_publisher_token(path), token)
            prompt.assert_not_called()
            self.assertEqual(output.getvalue() + errors.getvalue(), "")
            self.assertTrue(path.exists())

    def test_token_files_reject_shared_permissions_links_repository_paths_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "publisher-token"
            path.write_text("synthetic-secret")
            path.chmod(0o644)
            with self.assertRaises(InputError) as caught:
                publish.read_publisher_token(path)
            self.assertEqual(caught.exception.field, "publisher_token_file")
            self.assertNotIn("synthetic-secret", str(caught.exception))
            path.chmod(0o600)
            link = root / "linked-token"
            link.symlink_to(path)
            with self.assertRaises(InputError):
                publish.read_publisher_token(link)
            with patch.object(publish, "ROOT", root), self.assertRaises(InputError):
                publish.read_publisher_token(path)
            with patch.object(publish.os, "geteuid", return_value=os.geteuid() + 1), self.assertRaises(InputError):
                publish.read_publisher_token(path)
            path.write_text("x" * 32769)
            with self.assertRaises(InputError):
                publish.read_publisher_token(path)
            with self.assertRaises(InputError):
                publish.read_publisher_token(root)
            with self.assertRaises(InputError):
                publish.read_publisher_token(Path("relative-token"))
            fifo = root / "token-pipe"
            os.mkfifo(fifo, 0o600)
            with self.assertRaises(InputError):
                publish.read_publisher_token(fifo)


class IndependentPullTests(unittest.TestCase):
    def setUp(self):
        self.origin, self.repository = "https://registry.example.com", "repository/agent"
        self.local = {"layers": ["sha256:" + "a" * 64]}
        self.config = json.dumps({
            "os": "linux", "architecture": "amd64", "rootfs": {"diff_ids": self.local["layers"]},
        }).encode()
        self.layer = b"synthetic-compressed-layer-content"
        descriptor = lambda content: {"digest": "sha256:" + hashlib.sha256(content).hexdigest(), "size": len(content)}
        self.manifest = json.dumps({"config": descriptor(self.config), "layers": [descriptor(self.layer)]}).encode()
        self.publication = {
            "manifest_sha256": descriptor(self.manifest)["digest"],
            "config_sha256": descriptor(self.config)["digest"],
            "registry_layers": [descriptor(self.layer)["digest"]],
        }
        self.requests = []
        self.corrupt = False
        self.redirect = False
        self.missing = False
        self.realm = self.origin + "/artifactory/api/docker/repository/v2/token"

    def response(self, request):
        self.requests.append(request)
        if request.url.path.endswith("/v2/token"):
            self.assertTrue(request.headers["authorization"].startswith("Basic "))
            self.assertEqual(request.url.params["scope"], "repository:agent:pull")
            return httpx.Response(200, json={"token": "synthetic-pull-token"})
        if "/manifests/" in request.url.path:
            if "authorization" not in request.headers:
                return httpx.Response(401, headers={
                    "WWW-Authenticate": f'Bearer realm="{self.realm}",service="registry.example.com",scope="repository:agent:pull"',
                })
            self.assertEqual(request.headers["authorization"], "Bearer synthetic-pull-token")
            if self.missing:
                return httpx.Response(404, json={"error": "synthetic-secret"})
            return httpx.Response(200, content=self.manifest)
        if request.url.host == "storage.example.com":
            self.assertNotIn("authorization", request.headers)
            return httpx.Response(200, stream=httpx.ByteStream(self.layer))
        if request.url.path.endswith(self.publication["config_sha256"]):
            return httpx.Response(200, stream=httpx.ByteStream(self.config))
        if self.redirect:
            return httpx.Response(307, headers={"location": "https://storage.example.com/blob?temporary=synthetic-secret"})
        return httpx.Response(200, stream=httpx.ByteStream(b"corrupted" if self.corrupt else self.layer))

    def pull(self):
        publish.independent_jfrog_pull(
            self.origin, self.repository, self.publication, self.local,
            "publisher", "synthetic-publisher-token", transport=httpx.MockTransport(self.response),
        )

    def test_manifest_config_and_every_layer_are_downloaded_outside_docker_cache(self):
        self.pull()
        self.assertEqual(sum("/blobs/" in request.url.path for request in self.requests), 2)

    def test_corrupted_layer_and_mismatched_manifest_fail(self):
        self.corrupt = True
        with self.assertRaises(InputError):
            self.pull()
        self.corrupt = False
        self.manifest += b" "
        with self.assertRaises(InputError):
            self.pull()

    def test_storage_redirect_never_receives_registry_credentials(self):
        self.redirect = True
        self.pull()
        self.assertTrue(any(request.url.host == "storage.example.com" for request in self.requests))

    def test_missing_image_cannot_pass_independent_pull(self):
        self.missing = True
        with self.assertRaises(httpx.HTTPStatusError):
            self.pull()
        self.assertFalse(any("/blobs/" in request.url.path for request in self.requests))

    def test_unapproved_token_realm_never_receives_credentials(self):
        self.realm = "https://unapproved.example.com/token"
        with self.assertRaises(InputError):
            self.pull()
        self.assertEqual(len(self.requests), 1)


if __name__ == "__main__":
    unittest.main()
