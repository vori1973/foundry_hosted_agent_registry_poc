import argparse
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")
PROJECT_ID = re.compile(
    r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/"
    r"Microsoft\.CognitiveServices/accounts/([^/]+)/projects/([^/]+)",
    re.IGNORECASE,
)
IMAGE = re.compile(
    r"[a-z0-9][a-z0-9.-]+(?::[0-9]+)?/"
    r"[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}"
)


class InputError(ValueError):
    def __init__(self, field, message):
        self.field = field
        super().__init__(message)


def positive_timeout(value):
    try:
        timeout = float(value)
    except (ValueError, TypeError):
        raise InputError("timeout", "Timeout must be a positive finite number.") from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise InputError("timeout", "Timeout must be a positive finite number.")
    return timeout


def project_endpoint(value):
    message = "Set a valid HTTPS Foundry project endpoint without credentials or query parameters."
    try:
        parsed = urlsplit(value)
        has_port = parsed.port is not None
    except ValueError:
        raise InputError("FOUNDRY_PROJECT_ENDPOINT", message) from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or has_port
        or not re.fullmatch(r"/api/projects/[A-Za-z0-9][A-Za-z0-9_-]*", parsed.path)
    ):
        raise InputError("FOUNDRY_PROJECT_ENDPOINT", message)
    return value


@dataclass(frozen=True)
class Configuration:
    method: str
    name: str
    endpoint: str
    project_id: str
    model: str
    image: str | None = None
    registry_connection: str | None = None
    timeout: float = 600
    cpu: str = "0.5"
    memory: str = "1Gi"
    qualification: bool = False

    def validate(self):
        if self.method not in {"zip", "acr", "jfrog", "gar"}:
            raise InputError("method", "Method must be zip, acr, jfrog, or qualification-only gar.")
        if self.qualification is not False and self.method != "gar":
            raise InputError("qualification", "Qualification mode is only available for GAR.")
        if self.method == "gar" and self.qualification is not True:
            raise InputError("qualification", "GAR is unqualified; explicit qualification mode is required.")
        if not NAME.fullmatch(self.name):
            raise InputError("name", "Agent name must be 1-63 alphanumeric/hyphen characters.")
        project_endpoint(self.endpoint)
        resource = PROJECT_ID.fullmatch(self.project_id)
        if not resource:
            raise InputError("FOUNDRY_PROJECT_ID", "Set FOUNDRY_PROJECT_ID to the selected project's ARM resource ID.")
        parsed = urlsplit(self.endpoint)
        if (
            resource[1].lower() != parsed.hostname.split(".")[0].lower()
            or resource[2] != parsed.path.rsplit("/", 1)[1]
        ):
            raise InputError("FOUNDRY_PROJECT_ID", "Project ARM ID and endpoint identify different projects.")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", self.model):
            raise InputError("AZURE_AI_MODEL_DEPLOYMENT_NAME", "Set AZURE_AI_MODEL_DEPLOYMENT_NAME to an existing deployment name.")
        positive_timeout(self.timeout)
        if self.cpu != "0.5" or self.memory != "1Gi":
            raise InputError("compute", "This POC uses CPU 0.5 and memory 1Gi consistently across methods.")
        if self.method == "zip":
            if self.image or self.registry_connection:
                raise InputError("method", "ZIP deployment must not specify a container or registry connection.")
        elif not self.image or not IMAGE.fullmatch(self.image):
            raise InputError("image", "Use a fully qualified digest-pinned image: registry/repository@sha256:<digest>.")
        if self.method == "acr" and self.registry_connection:
            raise InputError("REGISTRY_CONNECTION_NAME", "The ACR path must not use a JFrog registry connection.")
        if self.method == "jfrog":
            if not self.registry_connection or not re.fullmatch(
                r"[A-Za-z0-9_-]+", self.registry_connection
            ):
                raise InputError("REGISTRY_CONNECTION_NAME", "JFrog requires a same-project registry connection name.")
        if self.method == "gar" and (
            not self.registry_connection or not re.fullmatch(r"[A-Za-z0-9_-]+", self.registry_connection)
        ):
            raise InputError("REGISTRY_CONNECTION_NAME", "GAR qualification requires a same-project connection name.")
        return self

    @classmethod
    def from_env(cls, method, name, image=None, timeout=600, env=None, *, qualification=False):
        env = os.environ if env is None else env
        return cls(
            method=method,
            name=name,
            endpoint=env.get("FOUNDRY_PROJECT_ENDPOINT", ""),
            project_id=env.get("FOUNDRY_PROJECT_ID", ""),
            model=env.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", ""),
            image=image,
            registry_connection=(
                env.get("REGISTRY_CONNECTION_NAME") if method in {"jfrog", "gar"} else None
            ),
            timeout=positive_timeout(timeout),
            qualification=qualification,
        ).validate()


def tool_versions(entry_point="sdk", container=False, runner=subprocess.run):
    if sys.version_info[:2] != (3, 13):
        raise InputError("python", "Run deployment helpers with Python 3.13.")
    if entry_point not in {"sdk", "azd"}:
        raise InputError("entry_point", "Entry point must be sdk or azd.")
    commands = {"az": (["az", "version", "--output", "json"], (2, 80, 0))}
    if entry_point == "azd":
        commands["azd"] = (["azd", "version"], (1, 32, 0))
    if container:
        commands["docker"] = (["docker", "version", "--format", "{{.Server.Version}}"], None)
    versions = {"python": ".".join(map(str, sys.version_info[:3]))}
    for name, (command, minimum) in commands.items():
        try:
            result = runner(command, check=True, capture_output=True, text=True, timeout=30)
            output = json.loads(result.stdout)["azure-cli"] if name == "az" else result.stdout
            match = re.search(r"(\d+)\.(\d+)\.(\d+)", output)
            if not match or (minimum and tuple(map(int, match.groups())) < minimum):
                raise InputError(name, f"{name} is missing a supported version.")
            versions[name] = match[0]
        except (OSError, subprocess.SubprocessError, KeyError, json.JSONDecodeError):
            raise InputError(name, f"{name} is unavailable; check the documented tool prerequisites.") from None
    return versions


def check_baselines(config, zip_evidence, local_evidence):
    if not zip_evidence or not local_evidence:
        raise InputError("baseline", "Registry progression requires --zip-evidence and --local-evidence.")
    try:
        try:
            from .verify import VerificationBlocked, read_record, require_baselines
        except ImportError:
            from verify import VerificationBlocked, read_record, require_baselines
        return require_baselines(config, read_record(zip_evidence), read_record(local_evidence))
    except VerificationBlocked as error:
        raise InputError("baseline", str(error)) from None


def jfrog_settings(env=None):
    env = os.environ if env is None else env
    origin = env.get("JFROG_REGISTRY_ORIGIN", "").rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
        or not re.fullmatch(r"[a-z0-9][a-z0-9.-]+(?::[0-9]+)?", parsed.netloc)
    ):
        raise InputError("JFROG_REGISTRY_ORIGIN", "Use the approved HTTPS registry origin without a path.")
    audience = env.get("JFROG_AUDIENCE", "")
    provider = env.get("JFROG_OIDC_PROVIDER_NAME", "")
    endpoint = env.get("JFROG_TOKEN_ENDPOINT", "")
    if not re.fullmatch(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", audience):
        raise InputError("JFROG_AUDIENCE", "Use the approved Entra application client ID.")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", provider):
        raise InputError("JFROG_OIDC_PROVIDER_NAME", "Set the exact administrator-confirmed provider name.")
    if endpoint not in {"/access/api/v1/oidc/token", origin + "/access/api/v1/oidc/token"}:
        raise InputError("JFROG_TOKEN_ENDPOINT", "Use the approved JFrog OIDC exchange endpoint.")
    return {
        "origin": origin, "audience": audience,
        "provider": provider, "token_endpoint": endpoint,
    }


def validate_jfrog_connection(config, connection, settings, *, credentials=False):
    expected_id = config.project_id + "/connections/" + config.registry_connection
    metadata = connection.get("metadata") or {}
    if (
        connection.get("id", "").lower() != expected_id.lower()
        or connection.get("name") != config.registry_connection
        or connection.get("type") != "CustomKeys"
        or connection.get("target", "").rstrip("/") != settings["origin"]
        or metadata.get("type") != "registry_connection"
        or metadata.get("mode") != "oauth_token_exchange"
        or urlsplit(settings["origin"]).netloc != config.image.split("/", 1)[0]
    ):
        raise InputError("registry_connection", "The connection must match the selected project, registry and exchange mode.")
    if credentials:
        values = connection.get("credentials") or {}
        values = values.as_dict() if hasattr(values, "as_dict") else values
        # The pinned SDK flattens custom keys and normalizes their names to lowercase.
        normalized = {key.lower(): value for key, value in values.items()}
        if (
            len(normalized) != len(values)
            or normalized != {
                "type": "CustomKeys", "audience": settings["audience"],
                "tokenendpoint": settings["token_endpoint"], "body.provider_name": settings["provider"],
            }
        ):
            raise InputError("registry_connection", "The connection's OIDC configuration differs; do not overwrite it.")


def check_jfrog_connection(config, env=None, project=None):
    settings = jfrog_settings(env)
    if config.method != "jfrog":
        raise InputError("method", "JFrog connection checks require JFrog configuration.")
    config.validate()
    if project is None:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
        with DefaultAzureCredential() as credential, AIProjectClient(
            endpoint=config.endpoint, credential=credential, allow_preview=True,
            retry_total=0, connection_timeout=10, read_timeout=30,
        ) as client:
            return check_jfrog_connection(config, env, client)
    try:
        connection = project.connections.get(config.registry_connection)
        validate_jfrog_connection(config, connection, settings)
        connection = project.connections.get(config.registry_connection, include_credentials=True)
        validate_jfrog_connection(config, connection, settings, credentials=True)
    except InputError:
        raise
    except Exception:
        raise InputError("registry_connection", "The connection could not be read; check existence, access and networking.") from None
    return {"registry_connection": config.registry_connection, "connection_preflight": "passed"}


def gar_settings(env=None):
    env = os.environ if env is None else env
    fields = {
        "GAR_PROJECT_ID": r"[a-z][a-z0-9-]{4,28}[a-z0-9]",
        "GAR_LOCATION": r"[a-z]+(?:-[a-z]+)*[0-9]*",
        "GAR_REPOSITORY": r"[a-z][a-z0-9_-]{0,62}",
        "GAR_ENTRA_AUDIENCE": r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}",
        "GAR_WORKLOAD_IDENTITY_PROVIDER": (
            r"//iam\.googleapis\.com/projects/[1-9][0-9]*/locations/global/"
            r"workloadIdentityPools/[a-z0-9-]{4,32}/providers/[a-z0-9-]{4,32}"
        ),
    }
    values = {}
    for key, pattern in fields.items():
        value = env.get(key, "")
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise InputError(key, "Set the exact approved GAR qualification input.")
        values[key] = value
    provider = values["GAR_WORKLOAD_IDENTITY_PROVIDER"]
    if any(part.startswith("gcp-") for part in (provider.split("/")[-3], provider.split("/")[-1])):
        raise InputError("GAR_WORKLOAD_IDENTITY_PROVIDER", "Google reserves the gcp- pool/provider prefix.")
    origin = env.get("GAR_REGISTRY_ORIGIN", "")
    if origin != f"https://{values['GAR_LOCATION']}-docker.pkg.dev":
        raise InputError("GAR_REGISTRY_ORIGIN", "Use the exact HTTPS GAR origin for the selected location.")
    return {
        "origin": origin,
        "project_id": values["GAR_PROJECT_ID"],
        "location": values["GAR_LOCATION"],
        "repository": values["GAR_REPOSITORY"],
        "audience": values["GAR_ENTRA_AUDIENCE"],
        "provider": provider,
        "token_endpoint": "https://sts.googleapis.com/v1/token",
        "keys": {
            "type": "CustomKeys",
            "audience": values["GAR_ENTRA_AUDIENCE"],
            "tokenendpoint": "https://sts.googleapis.com/v1/token",
            "body.audience": provider,
            "body.requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "body.scope": "https://www.googleapis.com/auth/cloud-platform",
        },
    }


def validate_gar_target(config, settings):
    config.validate()
    if config.method != "gar":
        raise InputError("method", "GAR checks require qualification-only GAR configuration.")
    prefix = f"{urlsplit(settings['origin']).netloc}/{settings['project_id']}/{settings['repository']}/"
    if (
        not config.image.startswith(prefix)
        or any(part in {"", ".", ".."} for part in config.image.split("@", 1)[0].split("/"))
    ):
        raise InputError("image", "The immutable image must select the approved GAR project and repository.")


def validate_gar_connection(config, connection, settings, *, credentials=False):
    validate_gar_target(config, settings)
    expected_id = config.project_id + "/connections/" + config.registry_connection
    metadata = connection.get("metadata") or {}
    if (
        connection.get("id", "").lower() != expected_id.lower()
        or connection.get("name") != config.registry_connection
        or connection.get("type") != "CustomKeys"
        or connection.get("target") != settings["origin"]
        or metadata.get("type") != "registry_connection"
        or metadata.get("mode") != "oauth_token_exchange"
    ):
        raise InputError("registry_connection", "The GAR connection must match the selected project, origin and mode.")
    if credentials:
        values = connection.get("credentials") or {}
        values = values.as_dict() if hasattr(values, "as_dict") else values
        if not isinstance(values, dict) or any(not isinstance(key, str) for key in values):
            raise InputError("registry_connection", "The GAR candidate requires exact nonsecret custom keys.")
        normalized = {key.lower(): value for key, value in values.items()}
        if len(normalized) != len(values) or normalized != settings["keys"]:
            raise InputError("registry_connection", "The GAR experimental candidate differs; do not overwrite it.")


def check_gar_connection(config, env=None, project=None):
    settings = gar_settings(env)
    validate_gar_target(config, settings)
    if project is None:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
        with DefaultAzureCredential() as credential, AIProjectClient(
            endpoint=config.endpoint, credential=credential, allow_preview=True,
            retry_total=0, connection_timeout=10, read_timeout=30,
        ) as client:
            return check_gar_connection(config, env, client)
    try:
        connection = project.connections.get(config.registry_connection)
        validate_gar_connection(config, connection, settings)
        connection = project.connections.get(config.registry_connection, include_credentials=True)
        validate_gar_connection(config, connection, settings, credentials=True)
    except InputError:
        raise
    except Exception:
        raise InputError("registry_connection", "The GAR connection could not be read; check selection and access.") from None
    return {
        "registry_connection": config.registry_connection, "connection_preflight": "passed",
        "qualification_only": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate POC inputs without creating cloud resources.")
    parser.add_argument("--method", choices=["zip", "acr", "jfrog", "gar"], required=True)
    parser.add_argument("--qualification", action="store_true", help="Validate the unqualified GAR candidate only.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--image")
    parser.add_argument("--timeout", type=positive_timeout, default=600)
    parser.add_argument("--entry-point", choices=["sdk", "azd"], default="sdk")
    parser.add_argument("--check-tools", action="store_true")
    parser.add_argument("--zip-evidence", type=Path)
    parser.add_argument("--local-evidence", type=Path)
    args = parser.parse_args(argv)
    try:
        config = Configuration.from_env(
            args.method, args.name, args.image, args.timeout, qualification=args.qualification,
        )
        if args.method != "zip":
            check_baselines(config, args.zip_evidence, args.local_evidence)
        if args.method == "jfrog":
            check_jfrog_connection(config)
        if args.method == "gar":
            check_gar_connection(config)
        versions = tool_versions(args.entry_point, args.method != "zip") if args.check_tools else {}
    except ValueError as error:
        parser.exit(1, f"Preflight failed: {error}\n")
    output = {"status": "inputs_valid", "method": config.method, "tools": versions}
    if config.method == "gar":
        output["qualification_only"] = True
    print(json.dumps(output))
    print("Cloud region/capacity, permissions, model access and network approval still require operator checks.")


if __name__ == "__main__":
    main()
