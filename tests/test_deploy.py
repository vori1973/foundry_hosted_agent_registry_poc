import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from email import policy
from email.parser import BytesParser
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch
from contextlib import redirect_stderr, redirect_stdout

import requests
from azure.ai.projects import AIProjectClient
from azure.core.credentials import AccessToken
from azure.core.exceptions import ResourceNotFoundError

from scripts import deploy
from scripts.preflight import Configuration, InputError
from scripts.verify import VerificationBlocked, baseline_fingerprint, new_record
from test_preflight import ENV, IMAGE, JFROG_ENV
from test_verification import state


class Credential:
    def get_token(self, *args, **kwargs):
        return AccessToken("offline-test-only", 9999999999)


class DeploymentTests(unittest.TestCase):
    def test_real_sdk_jfrog_wire_places_connection_inside_container_configuration(self):
        config = Configuration.from_env("jfrog", "agent", IMAGE, env=JFROG_ENV)
        definition = deploy.deployment_definition(config)
        captured = []

        def request(method, url, **kwargs):
            wire = requests.Request(
                method, url, headers=kwargs.get("headers"), data=kwargs.get("data"),
                json=kwargs.get("json"),
            ).prepare()
            captured.append(wire)
            response = requests.Response()
            response.status_code = 200
            response.headers["Content-Type"] = "application/json"
            response.url = url
            response._content = json.dumps({
                "object": "agent.version", "id": "agent:1", "name": "agent", "version": "1",
                "created_at": 1, "definition": definition.as_dict(), "status": "active",
            }).encode()
            response.raw = BytesIO(response._content)
            return response

        with patch.object(requests.Session, "request", side_effect=request):
            with AIProjectClient(
                endpoint=config.endpoint, credential=Credential(), allow_preview=True, retry_total=0,
            ) as project:
                created = project.agents.create_version(agent_name=config.name, definition=definition)
        body = json.loads(captured[0].body)["definition"]
        self.assertEqual(body["container_configuration"], {
            "image": IMAGE, "registry_connection_id": config.registry_connection,
        })
        self.assertNotIn("code_configuration", body)
        self.assertNotIn("registry_connection_id", body)
        self.assertEqual(body["environment_variables"], {
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": config.model, "DEPLOYMENT_SOURCE": "jfrog",
            "PYTHONNOUSERSITE": "1",
        })
        deploy.validate_container_state(created, config)
        created.definition.container_configuration.registry_connection_id = "other-connection"
        with self.assertRaises(VerificationBlocked):
            deploy.validate_container_state(created, config)

    def test_jfrog_connection_conflict_blocks_before_agent_creation(self):
        config = Configuration.from_env("jfrog", "agent", IMAGE, env=JFROG_ENV)
        project = MagicMock()
        with patch.object(deploy, "require_publication"), \
                patch.object(deploy, "check_jfrog_connection", side_effect=InputError("registry_connection", "Conflict")):
            with self.assertRaises(InputError):
                deploy.deploy_container(project, config, new_record(config), ())
        project.agents.get.assert_not_called()
        project.agents.create_version.assert_not_called()

    def test_real_sdk_container_wire_omits_code_and_static_pull_credentials(self):
        config = Configuration.from_env("acr", "agent", IMAGE, env=ENV)
        definition = deploy.deployment_definition(config)
        captured = []

        def request(method, url, **kwargs):
            captured.append(requests.Request(
                method, url, headers=kwargs.get("headers"), data=kwargs.get("data"),
                json=kwargs.get("json"),
            ).prepare())
            response = requests.Response()
            response.status_code = 200
            response.headers["Content-Type"] = "application/json"
            response.url = url
            response._content = json.dumps({
                "object": "agent.version", "id": "agent:1", "name": "agent", "version": "1",
                "created_at": 1, "definition": definition.as_dict(), "status": "active",
            }).encode()
            response.raw = BytesIO(response._content)
            return response

        with patch.object(requests.Session, "request", side_effect=request):
            with AIProjectClient(
                endpoint=ENV["FOUNDRY_PROJECT_ENDPOINT"], credential=Credential(),
                allow_preview=True, retry_total=0,
            ) as project:
                created = project.agents.create_version(agent_name="agent", definition=definition)
        self.assertEqual(captured[0].method, "POST")
        self.assertIn("/agents/agent/versions", captured[0].url)
        body = json.loads(captured[0].body)
        self.assertEqual(body["definition"], definition.as_dict())
        self.assertEqual(body["definition"]["container_configuration"], {"image": IMAGE})
        self.assertNotIn("code_configuration", body["definition"])
        self.assertEqual(body["definition"]["protocol_versions"], [{"protocol": "responses", "version": "2.0.0"}])
        deploy.validate_container_state(created, config)
        created.definition.container_configuration.image = IMAGE + "drift"
        with self.assertRaises(VerificationBlocked):
            deploy.validate_container_state(created, config)

    def test_zip_definition_excludes_container_and_reserved_settings(self):
        config = Configuration.from_env("zip", "agent", env=ENV)
        definition = deploy.deployment_definition(config)
        self.assertIsNone(definition.container_configuration)
        self.assertEqual(definition.code_configuration.runtime, "python_3_13")
        self.assertEqual(definition.code_configuration.dependency_resolution, "bundled")
        self.assertEqual(definition.protocol_versions[0].protocol, "responses")
        self.assertEqual(definition.environment_variables["AZURE_AI_MODEL_DEPLOYMENT_NAME"], "test-model")
        self.assertNotIn("FOUNDRY_PROJECT_ENDPOINT", definition.environment_variables)
        self.assertNotIn("AGENT_NAME", definition.environment_variables)

    def test_real_sdk_zip_multipart_and_endpoint_binding(self):
        captured = []
        config = Configuration.from_env("zip", "agent", env=ENV)
        definition = deploy.deployment_definition(config)
        zip_bytes = BytesIO()
        with zipfile.ZipFile(zip_bytes, "w") as archive:
            archive.writestr("main.py", "# synthetic test\n")
        code = zip_bytes.getvalue()
        digest = hashlib.sha256(code).hexdigest()

        def request(method, url, **kwargs):
            captured.append(requests.Request(
                method, url, headers=kwargs.get("headers"), data=kwargs.get("data"),
                files=kwargs.get("files"), json=kwargs.get("json"),
            ).prepare())
            response = requests.Response()
            response.status_code = 200
            response.headers["Content-Type"] = "application/json"
            response.url = url
            response._content = json.dumps({
                "object": "agent.version", "id": "agent:1", "name": "agent",
                "version": "1", "metadata": {}, "created_at": 1,
                "definition": definition.as_dict(), "status": "active",
            }).encode()
            response.raw = BytesIO(response._content)
            return response

        with patch.object(requests.Session, "request", side_effect=request):
            with AIProjectClient(
                endpoint=ENV["FOUNDRY_PROJECT_ENDPOINT"], credential=Credential(),
                allow_preview=True, retry_total=0,
            ) as project:
                created = project.agents.create_version_from_code(
                    agent_name="agent", definition=definition,
                    code=BytesIO(code), code_zip_sha256=digest,
                    metadata={"poc_change": deploy.CHANGE},
                )
                self.assertEqual(created.version, "1")
                deploy.bind_version(project, "agent", "1")

        wire = captured[0]
        self.assertEqual(wire.method, "POST")
        self.assertIn("/agents/agent/versions", wire.url)
        headers = wire.headers
        self.assertEqual(headers["x-ms-code-zip-sha256"], digest)
        self.assertIn("multipart/form-data", headers["Content-Type"])
        payload = wire.body
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {headers['Content-Type']}\r\n\r\n".encode() + payload
        )
        parts = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
                 for part in message.iter_parts()}
        self.assertIn(code, parts.values())
        json_parts = [json.loads(value) for value in parts.values() if value.startswith(b"{")]
        self.assertTrue(json_parts)
        self.assertIn(definition.as_dict(), [part.get("definition", part) for part in json_parts])
        self.assertNotIn("container_configuration", str(json_parts))
        self.assertEqual(captured[1].method, "PATCH")
        self.assertEqual(json.loads(captured[1].body), {
            "agent_endpoint": {"version_selector": {"version_selection_rules": [{
                "type": "FixedRatio", "agent_version": "1", "traffic_percentage": 100,
            }]}}
        })

    def test_resume_rejects_stale_baseline_and_unrelated_ownership(self):
        config = Configuration.from_env("zip", "agent", env=ENV)
        project = MagicMock()
        project.agents.get_version.return_value = {
            "metadata": {"poc_change": deploy.CHANGE, "poc_method": "zip",
                         "poc_baseline": baseline_fingerprint(config)}
        }
        deploy.validate_resume(project, config, "1")
        project.agents.get_version.return_value["metadata"]["poc_baseline"] = "stale"
        with self.assertRaises(VerificationBlocked):
            deploy.validate_resume(project, config, "1")
        project.agents.get.return_value = {"versions": {"latest": {"metadata": {}}}}
        with self.assertRaises(ValueError):
            deploy.verify_ownership(project, config)
        project.agents.create_version_from_code.assert_not_called()

    def test_cli_requires_approval_before_cloud_access_and_preserves_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blocked.json"
            with patch.object(deploy, "AIProjectClient") as project, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(deploy.main([
                    "--method", "zip", "--name", "agent", "--zip", "unused.zip",
                    "--evidence", str(path),
                ]), 1)
            project.assert_not_called()
            self.assertEqual(json.loads(path.read_text())["status"], "blocked")

    def test_invalid_configuration_or_zip_stops_before_cloud_access(self):
        for field in ("AZURE_AI_MODEL_DEPLOYMENT_NAME", "zip"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                env = dict(ENV)
                if field != "zip":
                    env.pop(field)
                path = Path(directory) / "blocked.json"
                with patch.dict(os.environ, env, clear=True), \
                        patch.object(deploy, "tool_versions", return_value={"python": "3.13"}), \
                        patch.object(deploy, "AIProjectClient") as project, \
                        redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    self.assertEqual(deploy.main([
                        "--method", "zip", "--name", "agent", "--zip", "missing.zip",
                        "--approve-cloud", "--evidence", str(path),
                    ]), 1)
                project.assert_not_called()
                self.assertEqual(json.loads(path.read_text())["error"]["field"], field)

    def test_failed_provisioning_retains_version_and_never_invokes(self):
        config = Configuration.from_env("zip", "agent", env=ENV)
        record = new_record(config)
        record["zip_sha256"] = "a" * 64
        project = MagicMock()
        project.agents.get.side_effect = ResourceNotFoundError("test-secret")
        project.agents.create_version_from_code.return_value = {"name": "agent", "version": "1"}
        project.agents.get_version.return_value = state("failed")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent.zip"
            path.write_bytes(b"synthetic upload")
            with self.assertRaises(RuntimeError):
                deploy.deploy_zip(project, config, path, record)
        self.assertEqual(record["agent_version"], "1")
        self.assertEqual(record["stage"], "activation")
        project.agents.update_details.assert_not_called()
        project.get_openai_client.assert_not_called()

    def test_cli_resume_is_read_only_and_sanitizes_transport_failure(self):
        config = Configuration.from_env("zip", "agent", env=ENV)
        with tempfile.TemporaryDirectory() as directory:
            for outcome in ("passed", "failed", "blocked", "missing-artifact"):
                with self.subTest(outcome=outcome):
                    path = Path(directory) / f"resume-{outcome}.json"
                    project = MagicMock()
                    project.agents.get_version.return_value = {
                        **state(), "metadata": {
                            "poc_change": deploy.CHANGE, "poc_method": "zip",
                            "poc_baseline": baseline_fingerprint(config),
                        },
                        "definition": {"code_configuration": {"content_hash": "a" * 64}},
                    }
                    if outcome == "missing-artifact":
                        project.agents.get_version.return_value["definition"] = {}
                    output = StringIO()
                    with patch.dict(os.environ, ENV, clear=True), \
                            patch.object(deploy, "tool_versions", return_value={"python": "3.13"}), \
                            patch.object(deploy, "DefaultAzureCredential"), \
                            patch.object(deploy, "AIProjectClient") as factory, \
                            patch.object(deploy, "verify_deployment") as verify, \
                            redirect_stdout(output), redirect_stderr(output):
                        factory.return_value.__enter__.return_value = project
                        if outcome == "failed":
                            verify.side_effect = ConnectionError("test-secret")
                        elif outcome == "blocked":
                            verify.side_effect = VerificationBlocked("test-secret")
                        else:
                            verify.return_value = {"status": "passed"}
                        result = deploy.main([
                            "--method", "zip", "--name", "agent", "--version", "1",
                            "--approve-cloud", "--evidence", str(path),
                        ])
                    self.assertEqual(result, int(outcome != "passed"))
                    project.agents.create_version_from_code.assert_not_called()
                    project.agents.update_details.assert_not_called()
                    evidence = json.loads(path.read_text())
                    self.assertEqual(evidence["agent_version"], "1")
                    self.assertEqual(evidence["status"], "blocked" if outcome == "missing-artifact" else outcome)
                    if outcome == "missing-artifact":
                        verify.assert_not_called()
                    else:
                        self.assertEqual(evidence["zip_sha256"], "a" * 64)
                    self.assertEqual(evidence["stages"]["preflight"], "passed")
                    self.assertNotIn("test-secret", path.read_text() + output.getvalue())


if __name__ == "__main__":
    unittest.main()
