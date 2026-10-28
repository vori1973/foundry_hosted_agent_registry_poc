import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.preflight import Configuration
from scripts.verify import baseline_fingerprint, new_record, safe_error, write_record
from test_preflight import ENV


class EvidenceTests(unittest.TestCase):
    def test_fingerprint_ignores_only_method_specific_labels(self):
        config = Configuration.from_env("zip", "agent-zip", env=ENV)
        expected = baseline_fingerprint(config)
        self.assertEqual(expected, baseline_fingerprint(replace(config, name="agent-acr", method="acr")))
        for change in ({"model": "other-model"}, {"cpu": "1"}, {"endpoint": config.endpoint + "-other"}):
            self.assertNotEqual(expected, baseline_fingerprint(replace(config, **change)))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "main.py").write_text("first")
            (source / "requirements.txt").write_text("dependency==1")
            before = baseline_fingerprint(config, source)
            (source / "main.py").write_text("second")
            self.assertNotEqual(before, baseline_fingerprint(config, source))
            before = baseline_fingerprint(config, source)
            (source / "requirements.txt").write_text("dependency==2")
            self.assertNotEqual(before, baseline_fingerprint(config, source))

    def test_unique_records_and_no_overwrite(self):
        first = new_record(Configuration.from_env("zip", "agent", env=ENV))
        self.assertNotEqual(first["run_id"], new_record()["run_id"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            write_record(path, first)
            self.assertEqual(json.loads(path.read_text())["status"], "blocked")
            with self.assertRaises(FileExistsError):
                write_record(path, first)

    def test_credentials_and_raw_errors_are_not_serialized(self):
        record = new_record()
        record["authorization"] = "Bearer test-secret"
        record["tools"]["password"] = "test-secret"
        record["error"] = {**safe_error(RuntimeError("test-secret")), "message": "test-secret"}
        record["smoke"] = {
            "status": "failed", "output_text": "test-secret",
            "validated_output": {"marker": "a" * 32, "token": "test-secret"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            write_record(path, record)
            self.assertNotIn("test-secret", path.read_text())
            self.assertEqual(json.loads(path.read_text())["error"]["code"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
