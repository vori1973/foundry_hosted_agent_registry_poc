import unittest
from unittest.mock import Mock

from scripts.verify import assert_smoke, smoke, smoke_payload


MARKER = "a" * 32


def response(text=None, **changes):
    return {
        "id": "response-test",
        "status": "completed",
        "output": [{
            "type": "message",
            "content": [{"type": "output_text", "text": text or f"Confirmed agent-test zip {MARKER}"}],
        }],
        **changes,
    }


class SmokeTests(unittest.TestCase):
    def test_completed_model_response_with_expected_markers(self):
        evidence = assert_smoke(response(), "agent-test", "zip", MARKER)
        self.assertEqual(evidence["status"], "passed")
        self.assertEqual(evidence["response_id"], "response-test")

    def test_empty_incomplete_refused_and_wrong_labels_fail(self):
        for body in (
            response(status="incomplete"),
            response(status="failed"),
            response(output=[]),
            response(text=" "),
            response(text="Static health confirmation"),
            response(error={"code": "model_error", "message": "test-secret"}),
            response(output=[{"type": "message", "content": [{"type": "refusal"}]}]),
            response(id=None),
        ):
            with self.subTest(body=body), self.assertRaises(RuntimeError) as error:
                assert_smoke(body, "agent-test", "zip", MARKER)
            self.assertNotIn("test-secret", str(error.exception))

    def test_output_is_allowlisted_not_arbitrary_model_content(self):
        evidence = assert_smoke(
            response(text=f"agent-test zip {MARKER} test-secret-unexpected"),
            "agent-test", "zip", MARKER,
        )
        self.assertNotIn("test-secret", str(evidence))

    def test_smoke_uses_one_shot_request_and_fresh_marker(self):
        client = Mock()

        def create(**payload):
            marker = payload["input"].rsplit(" ", 1)[1].rstrip(".")
            return response(text=f"agent-test zip {marker}")

        client.responses.create.side_effect = create
        first = smoke(client, "agent-test", "zip")
        second = smoke(client, "agent-test", "zip")
        self.assertNotEqual(first["validated_output"]["marker"], second["validated_output"]["marker"])
        self.assertEqual(client.responses.create.call_count, 2)
        self.assertFalse(client.responses.create.call_args.kwargs["store"])
        self.assertFalse(client.responses.create.call_args.kwargs["stream"])
        for name, source, marker in (("bad;name", "zip", MARKER), ("agent", "other", MARKER),
                                     ("agent", "zip", "invalid")):
            with self.assertRaises(ValueError):
                smoke_payload(name, source, marker)


if __name__ == "__main__":
    unittest.main()
