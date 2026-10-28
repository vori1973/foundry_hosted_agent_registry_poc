import unittest
from unittest.mock import MagicMock, Mock

from scripts.verify import verify_binding, verify_deployment, wait_for_active
from scripts.preflight import Configuration
from test_preflight import ENV


def state(status="active", version="1"):
    return {"name": "agent", "version": version, "status": status}


def binding(version="1", percentage=100):
    return {
        "name": "agent", "state": "enabled",
        "agent_endpoint": {"version_selector": {"version_selection_rules": [{
            "type": "FixedRatio", "agent_version": version, "traffic_percentage": percentage,
        }]}},
    }


class VerificationTests(unittest.TestCase):
    def test_waits_until_exact_version_active(self):
        project = Mock()
        project.agents.get_version.side_effect = [state("creating"), state()]
        now = [0]
        result = wait_for_active(
            project, "agent", "1", 10, clock=lambda: now[0],
            sleep=lambda duration: now.__setitem__(0, now[0] + duration),
        )
        self.assertEqual(result["status"], "active")
        self.assertEqual(project.agents.get_version.call_count, 2)

    def test_terminal_unknown_mismatched_and_transport_failure(self):
        for value in (state("failed"), state("deleted"), state("deleting"), state("other"),
                      state(version="2")):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                project = Mock()
                project.agents.get_version.return_value = value
                wait_for_active(project, "agent", "1", 10)
        project = Mock()
        project.agents.get_version.side_effect = ConnectionError("test-secret")
        with self.assertRaises(ConnectionError):
            wait_for_active(project, "agent", "1", 10)
        project.agents.create_version.assert_not_called()

    def test_deadline_and_invalid_timeout(self):
        project = Mock()
        project.agents.get_version.return_value = state("creating")
        now = [0]
        with self.assertRaises(TimeoutError):
            wait_for_active(project, "agent", "1", 2, clock=lambda: now[0],
                            sleep=lambda duration: now.__setitem__(0, now[0] + duration))
        self.assertEqual(now[0], 2)
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                wait_for_active(project, "agent", "1", timeout)
        project.agents.create_version.assert_not_called()

    def test_requires_exclusive_matching_endpoint_route(self):
        project = Mock()
        project.agents.get.return_value = binding()
        verify_binding(project, "agent", "1")
        for details in (binding("2"), binding(percentage=50), {"name": "agent", "state": "enabled"}):
            project.agents.get.return_value = details
            with self.assertRaises(RuntimeError):
                verify_binding(project, "agent", "1")

    def test_checks_binding_before_and_after_smoke(self):
        project = MagicMock()
        project.agents.get_version.return_value = state()
        project.agents.get.side_effect = [binding(), binding("2")]
        client = project.get_openai_client.return_value.__enter__.return_value

        def create(**payload):
            marker = payload["input"].rsplit(" ", 1)[1].rstrip(".")
            return {
                "id": "test-response", "status": "completed",
                "output": [{"content": [{"type": "output_text", "text": f"agent zip {marker}"}]}],
            }
        client.responses.create.side_effect = create
        config = Configuration.from_env("zip", "agent", env=ENV)
        with self.assertRaises(RuntimeError):
            verify_deployment(project, config, "1")
        self.assertEqual(project.agents.get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
