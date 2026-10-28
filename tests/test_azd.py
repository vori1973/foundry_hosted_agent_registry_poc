import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts import deploy, deploy_azd
from scripts.preflight import Configuration, InputError
from scripts.verify import new_record
from test_preflight import ENV, IMAGE, JFROG_ENV


class AzdTests(unittest.TestCase):
    def setUp(self):
        self.config = Configuration.from_env("acr", "acr-agent", IMAGE, env=ENV)
        self.record = new_record(self.config)
        self.commands = []
        self.registry = {"name": "registry", "loginServer": "registry.example.com", "id": "registry-id"}
        self.connection = {
            "category": "ContainerRegistry", "target": "https://registry.example.com",
            "authType": "AAD", "useWorkspaceManagedIdentity": True, "metadata": {"ResourceId": "registry-id"},
        }
        self.fail_deploy = False
        self.conflicting_project = False
        self.extensions = [
            {"id": "azure.ai.agents", "installedVersion": "1.0.0-beta.22"},
            {"id": "azure.ai.projects", "installedVersion": "1.0.0-beta.15"},
        ]

    def command(self, command, **kwargs):
        self.commands.append((command, kwargs))
        value = {}
        if command[:3] == ["azd", "extension", "list"]:
            value = self.extensions
        elif command[:3] == ["az", "resource", "show"]:
            value = {"location": "region", "tenant": "tenant-id"}
        elif command[:3] == ["az", "acr", "show"]:
            value = self.registry
        elif command[:2] == ["az", "rest"]:
            value = [self.connection]
        elif command[:2] == ["azd", "deploy"] and self.fail_deploy:
            raise subprocess.CalledProcessError(1, command, stderr="synthetic-secret")
        elif command[:4] == ["azd", "ai", "project", "add"] and self.conflicting_project:
            path = kwargs["cwd"] / "azure.yaml"
            template = yaml.safe_load(path.read_text())
            template["services"]["ai-project"]["deployments"] = [{"name": "unapproved-model"}]
            path.write_text(yaml.safe_dump(template))
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(value), stderr="")

    def test_rendered_prebuilt_service_matches_sdk_and_keeps_project_linkage(self):
        template = deploy_azd.render(self.config, self.record)
        template = yaml.safe_load(yaml.safe_dump(template))
        self.assertEqual(template["services"]["ai-project"]["endpoint"], self.config.endpoint)
        service = template["services"][self.config.name]
        definition = deploy.deployment_definition(self.config).as_dict()
        self.assertEqual(service["uses"], ["ai-project"])
        self.assertEqual(service["image"], definition["container_configuration"]["image"])
        self.assertEqual(service["protocols"], definition["protocol_versions"])
        self.assertEqual(service["env"], definition["environment_variables"])
        self.assertEqual(service["container"]["resources"], {"cpu": definition["cpu"], "memory": definition["memory"]})
        self.assertEqual(service["docker"], {"imagePassthrough": True, "remoteBuild": False})
        self.assertNotIn("codeConfiguration", service)
        self.assertEqual(template["infra"], {"provider": "microsoft.foundry"})

    def test_jfrog_service_matches_sdk_and_does_not_query_or_configure_acr(self):
        config = Configuration.from_env("jfrog", "jfrog-agent", IMAGE, env=JFROG_ENV)
        record = new_record(config)
        template = deploy_azd.render(config, record)
        service = template["services"][config.name]
        definition = deploy.deployment_definition(config).as_dict()
        self.assertEqual(service["registryConnectionId"], definition["container_configuration"]["registry_connection_id"])
        self.assertEqual(service["uses"], ["ai-project"])
        self.assertEqual(service["image"], definition["container_configuration"]["image"])
        self.assertEqual(service["env"], definition["environment_variables"])
        self.assertEqual(service["protocols"], definition["protocol_versions"])
        self.assertEqual(service["container"]["resources"], {"cpu": definition["cpu"], "memory": definition["memory"]})
        self.assertEqual(service["docker"], {"imagePassthrough": True, "remoteBuild": False})
        self.assertNotIn("codeConfiguration", service)
        with tempfile.TemporaryDirectory() as directory:
            deploy_azd.run_azd(config, record, Path(directory) / "workspace", self.command)
        commands = [command for command, _ in self.commands]
        self.assertFalse(any(command[:2] == ["az", "acr"] for command in commands))
        self.assertFalse(any("AZURE_CONTAINER_REGISTRY" in " ".join(command) for command in commands))
        self.assertFalse(any("build" in command or "push" in command or "provision" in command for command in commands))
        self.assertEqual(sum(command[:2] == ["azd", "deploy"] for command in commands), 1)

    def test_workspaces_and_commands_are_isolated_and_cli_failure_propagates(self):
        self.fail_deploy = True
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace with spaces"
            with self.assertRaises(subprocess.CalledProcessError):
                deploy_azd.run_azd(self.config, self.record, workspace, self.command)
            self.assertTrue((workspace / "azure.yaml").is_file())
            self.assertFalse((workspace / "Dockerfile").exists())
            for command, kwargs in self.commands:
                self.assertIsInstance(command, list)
                self.assertEqual(kwargs["cwd"], workspace)
                self.assertNotIn("shell", kwargs)
                self.assertTrue(kwargs["capture_output"])
                self.assertTrue(kwargs["check"])
                self.assertGreater(kwargs["timeout"], 0)
                self.assertNotIn("provision", command)
                self.assertNotIn("up", command)
            self.assertEqual(self.record["stage"], "creation")
            self.assertEqual(sum(cmd[:2] == ["azd", "deploy"] for cmd, _ in self.commands), 1)
            binding = next(index for index, (cmd, _) in enumerate(self.commands)
                           if cmd[:4] == ["azd", "ai", "project", "add"])
            deployment = next(index for index, (cmd, _) in enumerate(self.commands) if cmd[:2] == ["azd", "deploy"])
            self.assertLess(binding, deployment)
            self.assertEqual(self.commands[binding][0][5], self.config.project_id)
            self.assertTrue(all("--new-project" not in cmd and "--force" not in cmd for cmd, _ in self.commands))
            with self.assertRaises(FileExistsError):
                deploy_azd.run_azd(self.config, self.record, workspace, self.command)

    def test_missing_secretless_project_connection_blocks_before_azd(self):
        self.connection["useWorkspaceManagedIdentity"] = False
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(InputError):
            deploy_azd.run_azd(self.config, self.record, Path(directory) / "workspace", self.command)
        self.assertFalse(any(command[:3] in (["azd", "env", "new"], ["azd", "ai", "project"])
                             or command[:2] == ["azd", "deploy"] for command, _ in self.commands))

    def test_project_binding_cannot_introduce_unapproved_resource_configuration(self):
        self.conflicting_project = True
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(InputError):
            deploy_azd.run_azd(self.config, self.record, Path(directory) / "workspace", self.command)
        self.assertFalse(any(command[:2] == ["azd", "deploy"] for command, _ in self.commands))

    def test_missing_extension_stops_before_environment_or_project_binding(self):
        self.extensions = self.extensions[:1]
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(InputError):
            deploy_azd.run_azd(self.config, self.record, Path(directory) / "workspace", self.command)
        self.assertEqual(len(self.commands), 1)

    def test_missing_baseline_blocks_before_cloud_or_azd(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blocked.json"
            with patch.dict(os.environ, ENV, clear=True), \
                    patch.object(deploy_azd, "AIProjectClient") as project, \
                    patch.object(deploy_azd, "run_azd") as azd, \
                    redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(deploy_azd.main([
                    "--method", "acr", "--name", self.config.name, "--image", IMAGE,
                    "--zip-evidence", "missing.json", "--local-evidence", "missing-local.json",
                    "--publication-evidence", "missing-publication.json",
                    "--approve-cloud", "--evidence", str(path),
                ]), 1)
            project.assert_not_called()
            azd.assert_not_called()
            self.assertEqual(json.loads(path.read_text())["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
