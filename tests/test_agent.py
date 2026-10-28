import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["OTEL_SDK_DISABLED"] = "true"

import httpx
from agent_framework import Agent, BaseChatClient, ChatResponse, ChatResponseUpdate, Content, Message, ResponseStream
from agent import main


ENV = {
    "FOUNDRY_PROJECT_ENDPOINT": "https://account.services.ai.azure.com/api/projects/project",
    "AZURE_AI_MODEL_DEPLOYMENT_NAME": "test-model",
    "AGENT_NAME": "test-agent",
    "DEPLOYMENT_SOURCE": "zip",
}


class StubModel(BaseChatClient):
    def __init__(self, error=None):
        super().__init__()
        self.calls = []
        self.error = error

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        self.calls.append((messages, options))

        async def generate():
            if self.error:
                raise self.error
            yield ChatResponseUpdate(
                role="assistant", contents=[Content.from_text("Model answered the natural-language request.")],
                response_id="model-test-response",
            )

        if stream:
            return ResponseStream(generate(), finalizer=ChatResponse.from_updates)

        async def respond():
            if self.error:
                raise self.error
            return ChatResponse(
                messages=[Message("assistant", ["Model answered the natural-language request."])],
                response_id="model-test-response",
            )
        return respond()


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, payload, model=None):
        settings = main.Settings.from_env(ENV)
        model = model or StubModel()
        with patch.object(main, "create_agent", side_effect=lambda _: Agent(
            client=model, instructions=settings.instructions()
        )):
            server = main.create_server(settings)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server), base_url="http://localhost"
            ) as client:
                response = await client.post("/responses", json=payload)
        return response, model

    async def test_real_host_returns_model_output(self):
        response, model = await self.request({
            "input": "Explain why this deployment works.",
            "stream": False, "store": False,
            "model": "untrusted-caller-model",
        })
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertIn("Model answered", str(body["output"]))
        self.assertEqual(len(model.calls), 1)
        messages, options = model.calls[0]
        self.assertIn("Explain why", " ".join(message.text for message in messages))
        self.assertIn("test-agent", options["instructions"])
        self.assertEqual(options["model"], "test-model")

    async def test_invalid_request_never_calls_model(self):
        response, model = await self.request({"input": {"unsupported": True}, "stream": False})
        self.assertGreaterEqual(response.status_code, 400, response.text)
        self.assertEqual(model.calls, [])

    async def test_model_failure_never_becomes_success_or_leaks_error(self):
        for error in (
            PermissionError("test-secret-denied"),
            TimeoutError("test-secret-timeout"),
            RuntimeError("test-secret-upstream"),
        ):
            with self.subTest(error=type(error).__name__):
                with self.assertLogs("agent_framework_foundry_hosting", level="ERROR") as logs:
                    response, model = await self.request(
                        {"input": "Confirm deployment.", "stream": False, "store": False},
                        StubModel(error),
                    )
                self.assertNotIn("test-secret", response.text)
                self.assertNotIn("test-secret", " ".join(logs.output))
                self.assertTrue(model.calls)
                if response.status_code < 400:
                    self.assertNotEqual(response.json()["status"], "completed")

    async def test_readiness(self):
        with patch.object(main, "create_agent", return_value=Agent(client=StubModel())):
            server = main.create_server(main.Settings.from_env(ENV))
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server), base_url="http://localhost"
            ) as client:
                self.assertEqual((await client.get("/readiness")).status_code, 200)

    async def test_owned_client_closes_all_resources(self):
        client = object.__new__(main.OwnedFoundryClient)
        client.owned_credential = MagicMock(close=AsyncMock())
        client.project_client = MagicMock(close=AsyncMock())
        client.client = MagicMock(close=AsyncMock())
        await client.__aexit__(None, None, None)
        for resource in (client.owned_credential, client.project_client, client.client):
            resource.close.assert_awaited_once()

    def test_agent_factory_uses_configured_foundry_client_and_identity(self):
        settings = main.Settings.from_env(ENV)
        credential = MagicMock()
        with (
            patch.object(main.AgentConfig, "from_env", return_value=MagicMock(is_hosted=False)),
            patch.object(main, "DefaultAzureCredential", return_value=credential),
            patch.object(main, "OwnedFoundryClient", return_value=StubModel()) as factory,
        ):
            agent = main.create_agent(settings)
        self.assertIsInstance(agent, Agent)
        factory.assert_called_once_with(
            credential, project_endpoint=settings.endpoint,
            model=settings.model, default_headers=None,
        )

    def test_startup_rejects_missing_or_unsafe_settings(self):
        for key in ENV:
            with self.subTest(key=key), self.assertRaises(ValueError):
                main.Settings.from_env({**ENV, key: ""})
        for endpoint in (
            "http://account/api/projects/project",
            ENV["FOUNDRY_PROJECT_ENDPOINT"] + "?key=secret",
            "https://user:secret@account/api/projects/project",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                main.Settings.from_env({**ENV, "FOUNDRY_PROJECT_ENDPOINT": endpoint})
        with patch.dict(os.environ, {}, clear=True), patch.object(main, "create_server") as server:
            self.assertEqual(main.main(), 1)
            server.assert_not_called()


if __name__ == "__main__":
    unittest.main()
