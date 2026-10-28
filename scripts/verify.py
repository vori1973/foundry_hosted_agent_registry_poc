import hashlib
import json
import re
import time
from datetime import datetime, timezone
from dataclasses import replace
from importlib.metadata import version as package_version
from uuid import uuid4

try:
    from .preflight import InputError, positive_timeout
    from .build_zip import ROOT, SOURCE, source_digest
except ImportError:
    from preflight import InputError, positive_timeout
    from build_zip import ROOT, SOURCE, source_digest


SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,200}")
CHANGE = "hosted-agent-three-method-deployment"


class VerificationBlocked(RuntimeError):
    pass


def smoke_payload(name, source, marker=None):
    marker = marker or uuid4().hex
    if not re.fullmatch(r"[a-f0-9]{32}", marker):
        raise ValueError("Smoke marker must be a 32-character hexadecimal value.")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,63}", name) or source not in {"zip", "acr", "jfrog"}:
        raise ValueError("Smoke requires a valid agent name and deployment source.")
    return {
        "input": (
            "Give a short deployment confirmation. Include your configured agent name "
            f"and deployment source, and include this exact test marker: {marker}."
        ),
        "stream": False,
        "store": False,
    }, marker


def assert_smoke(response, name, source, marker):
    body = response.model_dump() if hasattr(response, "model_dump") else response
    if not isinstance(body, dict) or body.get("status") != "completed" or body.get("error"):
        raise RuntimeError("Smoke failed: response did not complete successfully.")
    text = []
    for item in body.get("output") or []:
        if item.get("type") == "refusal":
            raise RuntimeError("Smoke failed: model refused the request.")
        for content in item.get("content") or []:
            if content.get("type") == "refusal":
                raise RuntimeError("Smoke failed: model refused the request.")
            if content.get("type") == "output_text":
                text.append(content.get("text", ""))
    output = "\n".join(text)
    if not output.strip() or any(value not in output for value in (name, source, marker)):
        raise RuntimeError("Smoke failed: missing model output, test marker, or deployment labels.")
    response_id = body.get("id")
    if not isinstance(response_id, str) or not SAFE_ID.fullmatch(response_id):
        raise RuntimeError("Smoke failed: no safe response correlation identifier.")
    return {
        "status": "passed",
        "response_status": "completed",
        "response_id": response_id,
        "assertions": {"nonempty": True, "marker": True, "name": True, "source": True},
        "validated_output": {"marker": marker, "agent_name": name, "deployment_source": source},
    }


def smoke(client, name, source):
    payload, marker = smoke_payload(name, source)
    response = client.responses.create(**payload)
    return assert_smoke(response, name, source, marker)


def field(value, name, default=None):
    return value.get(name, default) if hasattr(value, "get") else getattr(value, name, default)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def safe_error(error):
    code = type(error).__name__
    result = {"code": code if SAFE_ID.fullmatch(code) else "UnhandledError"}
    if isinstance(error, InputError) and SAFE_ID.fullmatch(error.field):
        result["field"] = error.field
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}
    request_id = headers.get("x-ms-request-id") or headers.get("apim-request-id")
    if isinstance(request_id, str) and SAFE_ID.fullmatch(request_id):
        result["request_id"] = request_id
    return result


def wait_for_active(project, name, version, timeout, *, clock=time.monotonic, sleep=time.sleep, on_status=None):
    deadline = clock() + positive_timeout(timeout)
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError("Activation deadline expired; retain and inspect this version.")
        state = project.agents.get_version(
            agent_name=name, agent_version=version,
            connection_timeout=min(10, remaining), read_timeout=min(30, remaining),
            retry_total=0,
        )
        if clock() >= deadline:
            raise TimeoutError("Activation deadline expired; retain and inspect this version.")
        if field(state, "name") != name or str(field(state, "version")) != str(version):
            raise RuntimeError("The service returned a different agent/version.")
        status = field(state, "status")
        if status not in {"creating", "active", "failed", "deleting", "deleted"}:
            raise RuntimeError("The agent returned an unrecognized provisioning state.")
        if on_status:
            on_status(status)
        if status == "active":
            return state
        if status != "creating":
            raise RuntimeError("Agent provisioning terminated without activation.")
        sleep(min(5, max(0, deadline - clock())))


def verify_binding(project, name, version):
    details = project.agents.get(agent_name=name)
    if field(details, "name") != name or field(details, "state") != "enabled":
        raise VerificationBlocked("The agent endpoint is missing, disabled, or mismatched.")
    endpoint = field(details, "agent_endpoint", {})
    selector = field(endpoint, "version_selector", {})
    rules = field(selector, "version_selection_rules", []) or []
    if (
        len(rules) != 1
        or field(rules[0], "type") != "FixedRatio"
        or str(field(rules[0], "agent_version")) != str(version)
        or field(rules[0], "traffic_percentage") != 100
    ):
        raise VerificationBlocked("Exact-version endpoint binding is not proven.")


def validate_resume(project, config, version):
    state = project.agents.get_version(agent_name=config.name, agent_version=version)
    metadata = field(state, "metadata", {}) or {}
    if (
        metadata.get("poc_change") != CHANGE
        or metadata.get("poc_baseline") != baseline_fingerprint(config)
        or metadata.get("poc_method") != config.method
    ):
        raise VerificationBlocked("The version does not match this POC's current source/configuration.")
    return state


def verify_deployment(project, config, version):
    wait_for_active(project, config.name, version, config.timeout)
    verify_binding(project, config.name, version)
    with project.get_openai_client(
        agent_name=config.name, timeout=min(config.timeout, 60), max_retries=0,
    ) as client:
        result = smoke(client, config.name, config.method)
    verify_binding(project, config.name, version)
    return result


def baseline_fingerprint(config, source=SOURCE):
    content = {
        "source_sha256": source_digest(source),
        "project_id": config.project_id,
        "project_endpoint": config.endpoint,
        "model": config.model,
        "cpu": config.cpu,
        "memory": config.memory,
        "protocol": "responses/2.0.0",
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def read_record(path):
    try:
        if path.stat().st_size > 1024 * 1024:
            raise VerificationBlocked("Baseline evidence is too large.")
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        raise VerificationBlocked("Baseline evidence is missing or unreadable.") from None
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise VerificationBlocked("Baseline evidence has an unsupported schema.")
    return record


def completed_smoke(record):
    smoke = record.get("smoke")
    return (
        isinstance(smoke, dict) and smoke.get("status") == "passed"
        and smoke.get("response_status") == "completed"
        and isinstance(smoke.get("assertions"), dict)
        and all(smoke["assertions"].get(key) is True for key in ("nonempty", "marker", "name", "source"))
    )


def require_zip_baseline(config, record):
    if (
        record.get("method") != "zip" or record.get("status") != "passed"
        or record.get("baseline_fingerprint") != baseline_fingerprint(config)
        or record.get("stage") != "verification"
        or not record.get("agent_version") or not completed_smoke(record)
        or record.get("source_sha256") != source_digest()
        or record.get("dependencies_sha256") != hashlib.sha256((SOURCE / "requirements.txt").read_bytes()).hexdigest()
        or not re.fullmatch(r"[a-f0-9]{64}", str(record.get("zip_sha256", "")))
    ):
        raise VerificationBlocked("A matching successful live ZIP baseline is required.")


def require_artifact(zip_record, build):
    if (
        build.get("source_sha256") != source_digest()
        or build.get("source_sha256") != zip_record.get("source_sha256")
        or build.get("dependencies_sha256") != zip_record.get("dependencies_sha256")
        or build.get("zip_sha256") != zip_record.get("zip_sha256")
        or build.get("platform") != "linux/amd64"
        or not isinstance(build.get("image_id"), str)
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", build["image_id"])
        or not isinstance(build.get("layers"), list) or not build["layers"]
        or any(not isinstance(layer, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", layer) for layer in build["layers"])
    ):
        raise VerificationBlocked("A matching immutable container artifact is required.")
    for key, name in (("dockerfile_sha256", "Dockerfile"), ("dockerignore_sha256", ".dockerignore")):
        if build.get(key) != hashlib.sha256((ROOT / name).read_bytes()).hexdigest():
            raise VerificationBlocked("The container definition changed after its build.")


def require_build(config, zip_record, build):
    require_zip_baseline(config, zip_record)
    if build.get("method") != "local" or build.get("status") != "passed" or build.get("stage") != "image_build":
        raise VerificationBlocked("A successful container build is required.")
    require_artifact(zip_record, build)


def require_baselines(config, zip_record, local_record):
    require_zip_baseline(config, zip_record)
    if (
        local_record.get("method") != "local" or local_record.get("status") != "passed"
        or local_record.get("baseline_fingerprint") != baseline_fingerprint(config)
        or local_record.get("stage") != "verification"
        or local_record.get("stages", {}).get("readiness") != "passed"
        or local_record.get("cleanup_status") != "passed"
        or not completed_smoke(local_record)
    ):
        raise VerificationBlocked("A matching successful local-container model smoke is required.")
    require_artifact(zip_record, local_record)
    return local_record


def require_publication(config, zip_record, local_record, publication, acr_publication=None, acr_sdk=None, acr_azd=None):
    require_baselines(config, zip_record, local_record)
    require_artifact(zip_record, publication)
    if (
        config.method not in {"acr", "jfrog"} or publication.get("method") != config.method
        or publication.get("status") != "passed" or publication.get("stage") != "publication"
        or publication.get("baseline_fingerprint") != baseline_fingerprint(config)
        or publication.get("image_id") != local_record.get("image_id")
        or publication.get("layers") != local_record.get("layers")
        or publication.get("image_reference") != config.image
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", str(publication.get("config_sha256", "")))
        or not isinstance(publication.get("registry_layers"), list)
        or len(publication["registry_layers"]) != len(local_record["layers"])
        or any(not re.fullmatch(r"sha256:[a-f0-9]{64}", str(layer)) for layer in publication["registry_layers"])
        or not config.image.endswith("@" + str(publication.get("manifest_sha256")))
    ):
        raise VerificationBlocked("A matching verified immutable registry publication is required.")
    if config.method == "jfrog":
        if not all(isinstance(item, dict) for item in (acr_publication, acr_sdk, acr_azd)):
            raise VerificationBlocked("JFrog requires ACR publication and successful SDK/azd model baselines.")
        acr_config = replace(
            config, method="acr", image=acr_publication.get("image_reference"), registry_connection=None,
        ).validate()
        require_publication(acr_config, zip_record, local_record, acr_publication)
        if (
            publication.get("independent_pull") != "passed"
            or publication.get("registry_connection") != config.registry_connection
            or publication.get("acr_manifest_sha256") != acr_publication.get("manifest_sha256")
            or publication.get("config_sha256") != acr_publication.get("config_sha256")
            or publication.get("registry_layers") != acr_publication.get("registry_layers")
            or publication.get("manifest_comparison") != (
                "identical" if publication["manifest_sha256"] == acr_publication["manifest_sha256"]
                else "different_representation_matching_config_and_ordered_layers"
            )
        ):
            raise VerificationBlocked("JFrog publication must prove independent pull and identical ACR image content.")
        for entry_point, baseline in (("sdk", acr_sdk), ("azd", acr_azd)):
            require_artifact(zip_record, baseline)
            if (
                baseline.get("method") != "acr" or baseline.get("entry_point") != entry_point
                or baseline.get("status") != "passed" or baseline.get("stage") != "verification"
                or baseline.get("baseline_fingerprint") != baseline_fingerprint(config)
                or not baseline.get("agent_version") or not completed_smoke(baseline)
                or any(baseline.get(key) != acr_publication.get(key) for key in (
                    "image_reference", "image_id", "layers", "config_sha256", "manifest_sha256", "registry_layers",
                ))
            ):
                raise VerificationBlocked("Both matching ACR entry points must have passed exact-version model smokes.")
    return publication


def new_record(config=None, source=SOURCE):
    record = {
        "schema_version": 1,
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12],
        "started_at": utc_now(),
        "status": "blocked",
        "stage": "preflight",
        "stages": {"preflight": "running"},
        "entry_point": "sdk",
        "tools": {
            "azure-ai-projects": package_version("azure-ai-projects"),
            "azure-identity": package_version("azure-identity"),
        },
    }
    if config:
        record.update({
            "method": config.method,
            "agent_name": config.name,
            "baseline_fingerprint": baseline_fingerprint(config, source),
            "source_sha256": source_digest(source),
            "dependencies_sha256": hashlib.sha256((source / "requirements.txt").read_bytes()).hexdigest(),
            "cpu": config.cpu,
            "memory": config.memory,
            "protocol": "responses/2.0.0",
            "runtime": "python_3_13",
            "model_deployment": config.model,
        })
    return record


def start_stage(record, stage):
    record["stages"][record["stage"]] = "passed"
    record["stage"] = stage
    record["stages"][stage] = "running"


def write_record(path, record):
    keys = {
        "schema_version", "run_id", "started_at", "finished_at", "duration_seconds",
        "status", "stage", "entry_point", "method", "agent_name", "agent_version",
        "baseline_fingerprint", "source_sha256", "dependencies_sha256", "zip_sha256",
        "cpu", "memory", "protocol", "runtime", "model_deployment",
        "image_tag", "image_id", "platform", "layers",
        "dockerfile_sha256", "dockerignore_sha256",
        "container_id", "identity_type", "deployment_source", "cleanup_status",
        "registry", "registry_authorization_mode", "runtime_pull_identity",
        "publisher_roles", "runtime_pull_roles", "image_reference", "publication_tag",
        "manifest_sha256", "registry_layers",
        "config_sha256", "publication_action",
        "registry_connection", "connection_preflight", "publisher_group",
        "acr_manifest_sha256", "manifest_comparison", "independent_pull",
        "azd_workspace", "azd_environment",
        "version_discovery_status",
    }
    output = {key: value for key, value in record.items() if key in keys}
    output["tools"] = {
        key: value for key, value in record.get("tools", {}).items()
        if key in {"python", "az", "azd", "docker", "azure-ai-projects", "azure-identity",
                   "azure.ai.agents", "azure.ai.projects"}
    }
    output["stages"] = {
        key: value for key, value in record.get("stages", {}).items()
        if key in {"preflight", "ownership", "creation", "activation", "endpoint_binding",
                   "resume_validation", "verification", "image_build", "local_identity", "readiness",
                   "registry_preflight", "publisher_auth", "publication", "azd_preparation", "independent_pull"}
        and value in {"passed", "failed", "blocked", "running"}
    }
    if record.get("error"):
        output["error"] = {
            key: value for key, value in record["error"].items()
            if key in {"code", "request_id", "field"} and isinstance(value, str) and SAFE_ID.fullmatch(value)
        }
    if record.get("smoke"):
        result = record["smoke"]
        output["smoke"] = {
            key: result[key] for key in ("status", "response_status", "response_id", "assertions")
            if key in result
        }
        output["smoke"]["validated_output"] = {
            key: value for key, value in result.get("validated_output", {}).items()
            if key in {"marker", "agent_name", "deployment_source"}
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(output, stream, indent=2, sort_keys=True)
        stream.write("\n")
