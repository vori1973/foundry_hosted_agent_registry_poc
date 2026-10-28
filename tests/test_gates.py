import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import deploy, preflight
from scripts.build_zip import ROOT
from scripts.verify import VerificationBlocked, new_record, read_record, require_baselines, require_publication, write_record
from test_preflight import ENV, IMAGE, JFROG_ENV


class BaselineGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.zip_path, self.local_path = self.root / "zip.json", self.root / "local.json"
        self.config = preflight.Configuration.from_env("acr", "acr-test", IMAGE, env=ENV)
        zip_config = preflight.Configuration.from_env("zip", "zip-test", env=ENV)
        self.zip = new_record(zip_config)
        self.zip.update({
            "status": "passed", "stage": "verification", "agent_version": "1", "zip_sha256": "a" * 64,
            "smoke": {
                "status": "passed", "response_status": "completed",
                "assertions": dict.fromkeys(("nonempty", "marker", "name", "source"), True),
            },
        })
        self.local = new_record(zip_config)
        self.local.update({
            "method": "local", "status": "passed", "stage": "verification", "cleanup_status": "passed",
            "stages": {"readiness": "passed", "verification": "passed"},
            "smoke": copy.deepcopy(self.zip["smoke"]), "zip_sha256": self.zip["zip_sha256"],
            "image_id": "sha256:" + "b" * 64, "platform": "linux/amd64", "layers": ["sha256:" + "c" * 64],
            "dockerfile_sha256": hashlib.sha256((ROOT / "Dockerfile").read_bytes()).hexdigest(),
            "dockerignore_sha256": hashlib.sha256((ROOT / ".dockerignore").read_bytes()).hexdigest(),
        })

    def save(self):
        self.zip_path.write_text(json.dumps(self.zip))
        self.local_path.write_text(json.dumps(self.local))

    def test_matching_zip_and_local_model_evidence_passes(self):
        self.save()
        result = preflight.check_baselines(self.config, self.zip_path, self.local_path)
        self.assertEqual(result["image_id"], self.local["image_id"])
        self.assertEqual(result["layers"], self.local["layers"])

    def test_missing_failed_or_stale_predecessors_stop_before_external_work(self):
        for changes in (
            {"status": "failed"}, {"baseline_fingerprint": "stale"},
            {"source_sha256": "stale"}, {"dockerfile_sha256": "stale"},
            {"zip_sha256": "0" * 64}, {"cleanup_status": "failed"},
            {"smoke": {"status": "passed", "response_status": "incomplete"}},
            {"layers": []},
        ):
            with self.subTest(changes=changes):
                original = self.local
                self.local = {**original, **changes}
                self.save()
                with patch.dict("os.environ", ENV, clear=True), patch("scripts.preflight.tool_versions") as tools:
                    with patch("scripts.deploy.AIProjectClient") as project, redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as caught:
                            preflight.main([
                                "--method", "acr", "--name", self.config.name, "--image", IMAGE,
                                "--zip-evidence", str(self.zip_path), "--local-evidence", str(self.local_path),
                                "--check-tools",
                            ])
                    self.assertEqual(caught.exception.code, 1)
                    tools.assert_not_called()
                    project.assert_not_called()
                self.local = original
        self.local_path.unlink()
        with self.assertRaises(preflight.InputError):
            preflight.check_baselines(self.config, self.zip_path, self.local_path)
        with self.assertRaises(preflight.InputError):
            preflight.check_baselines(self.config, None, None)

    def test_changed_shared_model_or_zip_identity_invalidates_comparison(self):
        with self.assertRaises(VerificationBlocked):
            require_baselines(replace(self.config, model="other-model"), self.zip, self.local)
        for change in ({"status": "failed"}, {"zip_sha256": None}, {"dependencies_sha256": "stale"}):
            with self.subTest(change=change), self.assertRaises(VerificationBlocked):
                require_baselines(self.config, {**self.zip, **change}, self.local)

    def test_successful_local_record_roundtrips_without_credentials(self):
        path = self.root / "roundtrip.json"
        self.local["token"] = "synthetic-secret"
        self.local["adapter_stderr"] = "synthetic-secret"
        write_record(path, self.local)
        self.assertNotIn("synthetic-secret", path.read_text())
        require_baselines(self.config, self.zip, read_record(path))

    def test_publication_requires_matching_remote_and_local_immutable_content(self):
        publication = {
            **self.local, "method": "acr", "stage": "publication",
            "image_reference": IMAGE, "manifest_sha256": IMAGE.split("@")[1],
            "config_sha256": "sha256:" + "d" * 64, "registry_layers": ["sha256:" + "e" * 64],
        }
        require_publication(self.config, self.zip, self.local, publication)
        for changes in (
            {"status": "blocked"}, {"method": "local"}, {"stage": "verification"},
            {"image_reference": IMAGE + "stale"}, {"config_sha256": ""},
            {"registry_layers": []}, {"manifest_sha256": "sha256:" + "0" * 64},
            {"image_id": "sha256:" + "0" * 64}, {"baseline_fingerprint": "stale"},
        ):
            with self.subTest(changes=changes):
                project = MagicMock()
                with self.assertRaises(VerificationBlocked):
                    deploy.deploy_container(project, self.config, new_record(self.config), (
                        self.zip, self.local, {**publication, **changes},
                    ))
                project.agents.create_version.assert_not_called()
                project.agents.get.assert_not_called()

    def test_jfrog_requires_both_acr_model_baselines_and_equivalent_independently_pulled_content(self):
        config = preflight.Configuration.from_env("jfrog", "jfrog-test", IMAGE, env=JFROG_ENV)
        acr = {
            **self.local, "method": "acr", "stage": "publication",
            "image_reference": IMAGE, "manifest_sha256": IMAGE.split("@")[1],
            "config_sha256": "sha256:" + "d" * 64, "registry_layers": ["sha256:" + "e" * 64],
        }
        sdk = {**acr, "stage": "verification", "entry_point": "sdk", "agent_version": "1"}
        azd = {**sdk, "entry_point": "azd"}
        jfrog = {
            **acr, "method": "jfrog", "registry_connection": config.registry_connection,
            "independent_pull": "passed", "acr_manifest_sha256": acr["manifest_sha256"],
            "manifest_comparison": "identical",
        }
        records = [self.zip, self.local, jfrog, acr, sdk, azd]
        require_publication(config, *records)
        for index, changes in (
            (2, {"independent_pull": "failed"}),
            (2, {"registry_connection": "other"}),
            (2, {"config_sha256": "sha256:" + "0" * 64}),
            (2, {"registry_layers": ["sha256:" + "0" * 64]}),
            (2, {"acr_manifest_sha256": "sha256:" + "0" * 64}),
            (2, {"manifest_comparison": "unknown"}),
            (3, {"status": "failed"}),
            (4, {"status": "active"}), (5, {"status": "failed"}),
            (4, {"image_reference": IMAGE + "stale"}),
            (4, {"entry_point": "azd"}),
            (5, {"smoke": {"status": "failed"}}),
        ):
            with self.subTest(index=index, changes=changes):
                invalid = list(records)
                invalid[index] = {**invalid[index], **changes}
                project = MagicMock()
                with self.assertRaises(VerificationBlocked):
                    deploy.deploy_container(project, config, new_record(config), invalid)
                project.agents.create_version.assert_not_called()
                project.connections.get.assert_not_called()
        for count in (3, 4, 5):
            with self.subTest(count=count), self.assertRaises(VerificationBlocked):
                require_publication(config, *records[:count])
        different_image = IMAGE.split("@")[0] + "@sha256:" + "f" * 64
        different = {
            **jfrog, "image_reference": different_image, "manifest_sha256": different_image.split("@")[1],
            "manifest_comparison": "different_representation_matching_config_and_ordered_layers",
        }
        require_publication(replace(config, image=different_image), self.zip, self.local, different, acr, sdk, azd)


if __name__ == "__main__":
    unittest.main()
