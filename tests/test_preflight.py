import subprocess
import unittest
import copy
from dataclasses import replace
from unittest.mock import Mock, patch

from scripts.preflight import (
    Configuration, InputError, check_gar_connection, check_jfrog_connection, gar_settings, jfrog_settings,
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
GAR_ENV = {
    **ENV,
    "REGISTRY_CONNECTION_NAME": "gar-qualification",
    "GAR_REGISTRY_ORIGIN": "https://us-east1-docker.pkg.dev",
    "GAR_PROJECT_ID": "artifact-project",
    "GAR_LOCATION": "us-east1",
    "GAR_REPOSITORY": "poc-images",
    "GAR_ENTRA_AUDIENCE": "11111111-1111-1111-1111-111111111111",
    "GAR_WORKLOAD_IDENTITY_PROVIDER": (
        "//iam.googleapis.com/projects/123456789/locations/global/"
        "workloadIdentityPools/azure-pool/providers/azure-provider"
    ),
}
GAR_IMAGE = "us-east1-docker.pkg.dev/artifact-project/poc-images/agent@sha256:" + "a" * 64


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

    def test_gar_requires_explicit_qualification_mode_and_same_project_connection(self):
        with self.assertRaises(InputError):
            Configuration.from_env("gar", "agent", GAR_IMAGE, env=GAR_ENV)
        config = Configuration.from_env("gar", "agent", GAR_IMAGE, env=GAR_ENV, qualification=True)
        self.assertTrue(config.qualification)
        for changes in ({"qualification": False}, {"registry_connection": None}, {"image": GAR_IMAGE.split("@")[0]}):
            with self.subTest(changes=changes), self.assertRaises(InputError):
                replace(config, **changes).validate()
        with self.assertRaises(InputError):
            Configuration.from_env("zip", "agent", env=ENV, qualification=True)

    def test_gar_connection_keeps_audiences_distinct_and_rejects_conflicting_keys(self):
        config = Configuration.from_env("gar", "agent", GAR_IMAGE, env=GAR_ENV, qualification=True)
        settings = gar_settings(GAR_ENV)
        connection = {
            "id": config.project_id + "/connections/" + config.registry_connection,
            "name": config.registry_connection, "type": "CustomKeys",
            "target": settings["origin"],
            "metadata": {"type": "registry_connection", "mode": "oauth_token_exchange"},
            "credentials": dict(settings["keys"]),
        }
        project = Mock()
        project.connections.get.return_value = connection
        result = check_gar_connection(config, GAR_ENV, project)
        self.assertTrue(result["qualification_only"])
        self.assertEqual(project.connections.get.call_args.kwargs, {"include_credentials": True})
        self.assertEqual(settings["keys"]["audience"], GAR_ENV["GAR_ENTRA_AUDIENCE"])
        self.assertEqual(settings["keys"]["body.audience"], GAR_ENV["GAR_WORKLOAD_IDENTITY_PROVIDER"])
        for field, value in (
            ("id", "/different/project/connections/gar-qualification"),
            ("target", settings["origin"] + "/path"), ("name", "other"),
            ("type", "ApiKey"), ("metadata", {"type": "registry_connection", "mode": "other"}),
        ):
            project.reset_mock()
            project.connections.get.return_value = {**connection, field: value}
            with self.subTest(field=field), self.assertRaises(InputError):
                check_gar_connection(config, GAR_ENV, project)
            self.assertEqual(project.connections.get.call_count, 1)
        for changes in (
            {"audience": settings["provider"]},
            {"body.audience": settings["audience"]},
            {"body.grant_type": "urn:ietf:params:oauth:grant-type:token-exchange"},
            {"body.subject_token_type": "urn:ietf:params:oauth:token-type:jwt"},
            {"tokenendpoint": "https://other.example.com/token"},
            {"body.subject_token": "synthetic-secret"},
            {"headers.Authorization": "synthetic-secret"},
            {"AUDIENCE": "synthetic-secret"},
        ):
            altered = copy.deepcopy(connection)
            altered["credentials"].update(changes)
            project.connections.get.return_value = altered
            with self.subTest(keys=list(changes)), self.assertRaises(InputError) as caught:
                check_gar_connection(config, GAR_ENV, project)
            self.assertNotIn("synthetic-secret", str(caught.exception))
        altered = copy.deepcopy(connection)
        del altered["credentials"]["body.scope"]
        project.connections.get.return_value = altered
        with self.assertRaises(InputError):
            check_gar_connection(config, GAR_ENV, project)
        project.connections.get.side_effect = RuntimeError("synthetic-secret")
        with self.assertRaises(InputError) as caught:
            check_gar_connection(config, GAR_ENV, project)
        self.assertNotIn("synthetic-secret", str(caught.exception))

    def test_gar_rejects_wrong_repository_and_invalid_provider_before_connection_read(self):
        config = Configuration.from_env("gar", "agent", GAR_IMAGE, env=GAR_ENV, qualification=True)
        for image in (
            GAR_IMAGE.replace("us-east1", "us-west1"),
            GAR_IMAGE.replace("artifact-project", "other-project"),
            GAR_IMAGE.replace("poc-images/", "other-repo/"),
            GAR_IMAGE.replace("/agent@", "/../agent@"),
        ):
            project = Mock()
            with self.subTest(image=image), self.assertRaises(InputError):
                check_gar_connection(replace(config, image=image), GAR_ENV, project)
            project.connections.get.assert_not_called()
        for key in GAR_ENV.keys() - ENV.keys() - {"REGISTRY_CONNECTION_NAME"}:
            with self.subTest(key=key), self.assertRaises(InputError):
                gar_settings({**GAR_ENV, key: ""})
        for key, value in (
            ("GAR_PROJECT_ID", "123456789"),
            ("GAR_WORKLOAD_IDENTITY_PROVIDER", GAR_ENV["GAR_WORKLOAD_IDENTITY_PROVIDER"].replace("123456789", "artifact-project")),
            ("GAR_REGISTRY_ORIGIN", "http://us-east1-docker.pkg.dev"),
            ("GAR_REGISTRY_ORIGIN", "https://us-east1-docker.pkg.dev:443"),
            ("GAR_REGISTRY_ORIGIN", "https://us-east1-docker.pkg.dev?key=synthetic-secret"),
            ("GAR_WORKLOAD_IDENTITY_PROVIDER", GAR_ENV["GAR_WORKLOAD_IDENTITY_PROVIDER"].replace("azure-pool", "gcp-pool")),
        ):
            with self.subTest(key=key), self.assertRaises(InputError):
                gar_settings({**GAR_ENV, key: value})

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
