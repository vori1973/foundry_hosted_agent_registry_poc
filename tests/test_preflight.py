import subprocess
import unittest
import copy
from dataclasses import replace
from unittest.mock import Mock, patch

from scripts.preflight import (
    Configuration, InputError, check_jfrog_connection, jfrog_settings,
    positive_timeout, tool_versions,
)


ENV = {
    "FOUNDRY_PROJECT_ENDPOINT": "https://account.services.ai.azure.com/api/projects/project",
    "FOUNDRY_PROJECT_ID": (
        "/subscriptions/sub/resourceGroups/group/providers/"
        "Microsoft.CognitiveServices/accounts/account/projects/project"
    ),
    "AZURE_AI_MODEL_DEPLOYMENT_NAME": "test-model",
}
IMAGE = "registry.example.com/repository/agent@sha256:" + "a" * 64
JFROG_ENV = {
    **ENV,
    "REGISTRY_CONNECTION_NAME": "jfrog-pull",
    "JFROG_REGISTRY_ORIGIN": "https://registry.example.com",
    "JFROG_AUDIENCE": "11111111-1111-1111-1111-111111111111",
    "JFROG_OIDC_PROVIDER_NAME": "foundrypoc",
    "JFROG_TOKEN_ENDPOINT": "/access/api/v1/oidc/token",
}


class PreflightTests(unittest.TestCase):
    def test_zip_and_container_inputs(self):
        config = Configuration.from_env("zip", "test-agent", env=ENV)
        self.assertIsNone(config.image)
        self.assertEqual(Configuration.from_env("acr", "test-agent", IMAGE, env=ENV).image, IMAGE)
        jfrog = Configuration.from_env(
            "jfrog", "test-agent", IMAGE, env={**ENV, "REGISTRY_CONNECTION_NAME": "pull-only"}
        )
        self.assertEqual(jfrog.registry_connection, "pull-only")

    def test_missing_and_mismatched_configuration(self):
        for field in ENV:
            with self.subTest(field=field), self.assertRaises(ValueError):
                Configuration.from_env("zip", "agent", env={**ENV, field: ""})
        config = Configuration.from_env("zip", "agent", env=ENV)
        for changes in (
            {"endpoint": ENV["FOUNDRY_PROJECT_ENDPOINT"] + "?key=secret"},
            {"endpoint": "http://account.services.ai.azure.com/api/projects/project"},
            {"endpoint": "https://account.services.ai.azure.com/api/projects/other"},
            {"endpoint": "https://other.services.ai.azure.com/api/projects/project"},
            {"endpoint": "https://user:secret@account.services.ai.azure.com/api/projects/project"},
            {"name": "agent; command"},
            {"image": IMAGE},
            {"cpu": "invalid"},
            {"memory": "invalid"},
            {"method": "other"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(config, **changes).validate()

    def test_timeout_must_be_positive_and_finite(self):
        for value in (0, -1, "nan", "inf", "not-a-number", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                positive_timeout(value)

    def test_registry_requires_immutable_image_and_connection(self):
        for method, image in (("acr", None), ("acr", "registry.example.com/agent:latest"),
                              ("jfrog", IMAGE)):
            with self.subTest(method=method, image=image), self.assertRaises(ValueError):
                Configuration.from_env(method, "agent", image, env=ENV)

    def test_jfrog_connection_readback_checks_normalized_nonsecret_configuration(self):
        config = Configuration.from_env("jfrog", "agent", IMAGE, env=JFROG_ENV)
        connection = {
            "id": config.project_id + "/connections/" + config.registry_connection,
            "name": config.registry_connection, "type": "CustomKeys",
            "target": JFROG_ENV["JFROG_REGISTRY_ORIGIN"],
            "metadata": {"type": "registry_connection", "mode": "oauth_token_exchange"},
            "credentials": {
                "type": "CustomKeys", "audience": JFROG_ENV["JFROG_AUDIENCE"],
                "tokenendpoint": JFROG_ENV["JFROG_TOKEN_ENDPOINT"],
                "body.provider_name": JFROG_ENV["JFROG_OIDC_PROVIDER_NAME"],
            },
        }
        project = Mock()
        project.connections.get.return_value = connection
        self.assertEqual(check_jfrog_connection(config, JFROG_ENV, project)["connection_preflight"], "passed")
        self.assertEqual(project.connections.get.call_args.kwargs, {"include_credentials": True})
        for field, value in (
            ("id", "/different/project/connections/jfrog-pull"),
            ("name", "other"), ("type", "ApiKey"), ("target", "https://other.example.com"),
            ("metadata", {"type": "registry_connection", "mode": "other"}),
        ):
            project.reset_mock()
            project.connections.get.return_value = {**connection, field: value}
            with self.subTest(field=field), self.assertRaises(InputError):
                check_jfrog_connection(config, JFROG_ENV, project)
            self.assertEqual(project.connections.get.call_count, 1)
        for key in ("audience", "tokenendpoint", "body.provider_name"):
            altered = copy.deepcopy(connection)
            altered["credentials"][key] = "synthetic-secret"
            project.connections.get.return_value = altered
            with self.subTest(key=key), self.assertRaises(InputError) as caught:
                check_jfrog_connection(config, JFROG_ENV, project)
            self.assertNotIn("synthetic-secret", str(caught.exception))
        project.connections.get.side_effect = RuntimeError("synthetic-secret")
        with self.assertRaises(InputError) as caught:
            check_jfrog_connection(config, JFROG_ENV, project)
        self.assertNotIn("synthetic-secret", str(caught.exception))

    def test_jfrog_settings_reject_unapproved_endpoints_and_missing_values(self):
        for key in ("JFROG_REGISTRY_ORIGIN", "JFROG_AUDIENCE",
                    "JFROG_OIDC_PROVIDER_NAME", "JFROG_TOKEN_ENDPOINT"):
            with self.subTest(key=key), self.assertRaises(InputError):
                jfrog_settings({**JFROG_ENV, key: ""})
        for origin in (
            "http://registry.example.com", "https://user:password@registry.example.com",
            "https://registry.example.com/artifactory/api/docker/repository",
            "https://registry.example.com?key=secret",
        ):
            with self.subTest(origin=origin), self.assertRaises(InputError):
                jfrog_settings({**JFROG_ENV, "JFROG_REGISTRY_ORIGIN": origin})
        with self.assertRaises(InputError):
            jfrog_settings({**JFROG_ENV, "JFROG_TOKEN_ENDPOINT": "https://other.example.com/token"})

    @patch("scripts.preflight.sys.version_info", (3, 13, 0))
    def test_tool_versions_and_failures(self):
        runner = Mock(side_effect=[
            subprocess.CompletedProcess([], 0, '{"azure-cli":"2.80.0"}'),
            subprocess.CompletedProcess([], 0, "azd version 1.32.0"),
            subprocess.CompletedProcess([], 0, "28.1.1"),
        ])
        self.assertEqual(tool_versions("azd", True, runner)["docker"], "28.1.1")
        for output in ('{"azure-cli":"2.79.0"}', "invalid-json"):
            with self.assertRaises(ValueError):
                tool_versions(runner=Mock(return_value=subprocess.CompletedProcess([], 0, output)))
        with self.assertRaises(ValueError):
            tool_versions(runner=Mock(side_effect=FileNotFoundError("missing")))


if __name__ == "__main__":
    unittest.main()
