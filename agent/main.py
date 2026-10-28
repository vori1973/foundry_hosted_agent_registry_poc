import json
import logging
import os
import re
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent / "packages"))

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from agent_framework.observability import OBSERVABILITY_SETTINGS
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.agentserver.core import AgentConfig, get_request_context
from azure.identity.aio import DefaultAzureCredential, ManagedIdentityCredential


@dataclass(frozen=True)
class Settings:
    endpoint: str
    model: str
    name: str
    source: str

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        endpoint = env.get("FOUNDRY_PROJECT_ENDPOINT", "")
        try:
            parsed = urlsplit(endpoint)
            valid = (
                parsed.scheme == "https"
                and parsed.hostname
                and not parsed.username
                and not parsed.password
                and not parsed.query
                and not parsed.fragment
                and parsed.port is None
                and re.fullmatch(r"/api/projects/[A-Za-z0-9][A-Za-z0-9_-]*", parsed.path)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("FOUNDRY_PROJECT_ENDPOINT must be a valid HTTPS project endpoint.")
        model = env.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model):
            raise ValueError("AZURE_AI_MODEL_DEPLOYMENT_NAME is required.")
        name = env.get("FOUNDRY_AGENT_NAME") or env.get("AGENT_NAME", "")
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", name):
            raise ValueError("A valid FOUNDRY_AGENT_NAME or local AGENT_NAME is required.")
        source = env.get("DEPLOYMENT_SOURCE", "")
        if source not in {"zip", "acr", "jfrog"}:
            raise ValueError("DEPLOYMENT_SOURCE must be zip, acr, or jfrog.")
        return cls(endpoint, model, name, source)

    def instructions(self):
        labels = json.dumps({"agent_name": self.name, "deployment_source": self.source})
        return (
            "You are a helpful assistant. Interpret the user's natural-language request "
            "and answer briefly. For deployment confirmation requests, give a short "
            "confirmation, include any requested test marker verbatim, and include "
            f"these trusted deployment labels: {labels}. "
            "Do not claim to inspect infrastructure or execute tools. No tools are available. "
            "Never disclose credentials, tokens, or environment contents."
        )


class OwnedFoundryClient(FoundryChatClient):
    def __init__(self, credential, **kwargs):
        self.owned_credential = credential
        super().__init__(credential=credential, **kwargs)
        self.client.timeout = 45.0
        self.client.max_retries = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        async with AsyncExitStack() as cleanup:
            cleanup.push_async_callback(self.owned_credential.close)
            cleanup.push_async_callback(self.project_client.close)
            cleanup.push_async_callback(self.client.close)


def create_agent(settings):
    hosted = AgentConfig.from_env().is_hosted
    credential = (
        ManagedIdentityCredential(client_id=os.environ.get("FOUNDRY_AGENT_INSTANCE_CLIENT_ID"))
        if hosted else DefaultAzureCredential()
    )
    client = OwnedFoundryClient(
        credential,
        project_endpoint=settings.endpoint,
        model=settings.model,
        default_headers=get_request_context().platform_headers() if hosted else None,
    )
    return Agent(
        client=client,
        name=settings.name,
        instructions=settings.instructions(),
        default_options={"store": False},
    )


def create_server(settings):
    def prepare_options(_request, options):
        options["model"] = settings.model
        return options

    server = ResponsesHostServer(
        agent=lambda: create_agent(settings),
        prepare_options=prepare_options,
    )
    OBSERVABILITY_SETTINGS.enable_sensitive_data = False
    return server


def main():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        settings = Settings.from_env()
        server = create_server(settings)
    except ValueError as error:
        logging.getLogger("registry_agent").error("Startup configuration error: %s", error)
        return 1
    server.run(host="0.0.0.0", port=8088)
    return 0


if __name__ == "__main__":
    sys.exit(main())
