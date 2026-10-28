import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml
from azure.ai.projects import AIProjectClient
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential

try:
    from .build_zip import ROOT
    from .deploy import activate_version, registry_evidence, validate_container_state
    from .preflight import Configuration, InputError, check_jfrog_connection, positive_timeout, tool_versions
    from .verify import (
        CHANGE, VerificationBlocked, field, new_record, safe_error, start_stage,
        utc_now, verify_deployment, write_record,
    )
except ImportError:
    from build_zip import ROOT
    from deploy import activate_version, registry_evidence, validate_container_state
    from preflight import Configuration, InputError, check_jfrog_connection, positive_timeout, tool_versions
    from verify import (
        CHANGE, VerificationBlocked, field, new_record, safe_error, start_stage,
        utc_now, verify_deployment, write_record,
    )


def render(config, record):
    config.validate()
    template = yaml.safe_load((ROOT / f"deploy/{config.method}/azure.yaml").read_text())
    template["services"]["ai-project"]["endpoint"] = config.endpoint
    service = template["services"].pop("agent")
    service["name"], service["image"] = config.name, config.image
    service["env"]["AZURE_AI_MODEL_DEPLOYMENT_NAME"] = config.model
    if config.method == "jfrog":
        service["registryConnectionId"] = config.registry_connection
    service["metadata"] = {
        "poc_change": CHANGE, "poc_baseline": record["baseline_fingerprint"],
        "poc_method": config.method, "poc_run": record["run_id"],
    }
    template["services"][config.name] = service
    return template


def run_azd(config, record, workspace, runner=subprocess.run):
    workspace.mkdir(parents=True, exist_ok=False)
    (workspace / "azure.yaml").write_text(yaml.safe_dump(render(config, record), sort_keys=False))
    environment = "poc-" + record["run_id"].lower()
    record.update({"azd_workspace": str(workspace), "azd_environment": environment})
    subscription, group, account, project_name = (
        config.project_id.split("/")[index] for index in (2, 4, 8, 10)
    )

    def run(command, timeout=60):
        return runner(command, cwd=workspace, check=True, capture_output=True, text=True, timeout=timeout)

    extensions = json.loads(run(["azd", "extension", "list", "--output", "json"]).stdout)
    if not isinstance(extensions, list) or any(not isinstance(item, dict) for item in extensions):
        raise InputError("extensions", "Foundry extension metadata is invalid.")
    for extension in extensions:
        if extension.get("id") in {"azure.ai.agents", "azure.ai.projects"}:
            version = extension.get("installedVersion", "")
            if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", version):
                raise InputError("extensions", "A required Foundry extension is not installed.")
            record["tools"][extension["id"]] = version
    if not {"azure.ai.agents", "azure.ai.projects"}.issubset(record["tools"]):
        raise InputError("extensions", "Both Foundry agent and project extensions are required.")
    target = json.loads(run(["az", "resource", "show", "--ids", config.project_id, "--query",
                             "{location:location,tenant:identity.tenantId}", "--output", "json"]).stdout)
    if not target.get("tenant"):
        raise InputError("project", "The selected project managed identity metadata is unavailable.")
    registry_settings = {}
    if config.method == "acr":
        registry = json.loads(run([
            "az", "acr", "show", "--name", config.image.split(".", 1)[0], "--output", "json",
        ]).stdout)
        if registry.get("loginServer") != config.image.split("/", 1)[0]:
            raise InputError("registry", "The selected registry/project metadata is inconsistent.")
        connections = json.loads(run([
            "az", "rest", "--method", "get", "--url",
            f"https://management.azure.com{config.project_id}/connections?api-version=2025-06-01",
            "--query", "value[].properties.{category:category,target:target,authType:authType,useWorkspaceManagedIdentity:useWorkspaceManagedIdentity,metadata:metadata}",
            "--output", "json",
        ]).stdout)
        if not any(
            item.get("category") == "ContainerRegistry"
            and item.get("target", "").rstrip("/") == "https://" + registry["loginServer"]
            and item.get("authType") == "AAD" and item.get("useWorkspaceManagedIdentity") is True
            and (item.get("metadata") or {}).get("ResourceId") == registry["id"]
            for item in connections
        ):
            raise InputError("acr_connection", "A matching secretless project registry connection must already exist.")
        registry_settings = {
            "AZURE_CONTAINER_REGISTRY_NAME": registry["name"],
            "AZURE_CONTAINER_REGISTRY_ENDPOINT": registry["loginServer"],
            "AZURE_CONTAINER_REGISTRY_RESOURCE_ID": registry["id"],
        }
    run([
        "azd", "env", "new", environment, "--subscription", subscription,
        "--location", target["location"], "--no-prompt",
    ])
    settings = {
        "AZURE_AI_PROJECT_ENDPOINT": config.endpoint, "AZURE_AI_PROJECT_ID": config.project_id,
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": config.model, "AZURE_TENANT_ID": target["tenant"],
        "AZURE_RESOURCE_GROUP": group, "AZURE_AI_ACCOUNT_NAME": account, "AZURE_AI_PROJECT_NAME": project_name,
        **registry_settings, "AZD_AGENT_SKIP_ACR": "true",
    }
    for key, value in settings.items():
        run(["azd", "env", "set", key, value, "--environment", environment, "--no-prompt"])
    run([
        "azd", "ai", "project", "add", "--project-id", config.project_id,
        "--environment", environment, "--no-prompt",
    ])
    if yaml.safe_load((workspace / "azure.yaml").read_text()) != render(config, record):
        raise InputError("project", "Project binding changed the selected deployment configuration.")
    start_stage(record, "creation")
    run(["azd", "deploy", config.name, "--environment", environment, "--no-prompt",
         "--timeout", str(max(1, int(config.timeout)))], timeout=config.timeout + 120)


def discover_version(project, config, record):
    details = project.agents.get(agent_name=config.name)
    state = field(field(details, "versions", {}), "latest", {})
    metadata = field(state, "metadata", {}) or {}
    version = str(field(state, "version", ""))
    if (
        metadata.get("poc_run") != record["run_id"] or metadata.get("poc_change") != CHANGE
        or metadata.get("poc_baseline") != record["baseline_fingerprint"]
        or not re.fullmatch(r"[A-Za-z0-9]{1,64}", version)
    ):
        raise VerificationBlocked("The azd-created version cannot be attributed to this run.")
    record["agent_version"] = version
    return project.agents.get_version(agent_name=config.name, agent_version=version)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deploy a verified ACR or JFrog image through isolated azd state.")
    parser.add_argument("--method", choices=["acr", "jfrog"], required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--zip-evidence", type=Path, required=True)
    parser.add_argument("--local-evidence", type=Path, required=True)
    parser.add_argument("--publication-evidence", type=Path, required=True)
    parser.add_argument("--acr-publication-evidence", type=Path)
    parser.add_argument("--acr-sdk-evidence", type=Path)
    parser.add_argument("--acr-azd-evidence", type=Path)
    parser.add_argument("--timeout", type=positive_timeout, default=600)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--approve-cloud", action="store_true")
    args = parser.parse_args(argv)
    record = new_record()
    record["entry_point"] = "azd"
    path = args.evidence or ROOT / ".artifacts" / record["run_id"] / "deployment.json"
    if path.exists() or path.is_symlink():
        parser.error("Evidence already exists; choose a new path.")
    started = time.monotonic()
    try:
        if not args.approve_cloud:
            raise InputError("approve_cloud", "Explicit deployment and inference approval is required.")
        config = Configuration.from_env(args.method, args.name, args.image, args.timeout)
        context = new_record(config)
        context["run_id"], context["started_at"] = record["run_id"], record["started_at"]
        record.update(context)
        record["entry_point"] = "azd"
        registry_evidence(config, args, record)
        record["tools"].update(tool_versions("azd"))
        with DefaultAzureCredential() as credential, AIProjectClient(
            endpoint=config.endpoint, credential=credential, allow_preview=True,
            retry_total=0, connection_timeout=10, read_timeout=30,
        ) as project:
            if config.method == "jfrog":
                start_stage(record, "registry_preflight")
                record.update(check_jfrog_connection(config, project=project))
            start_stage(record, "ownership")
            try:
                project.agents.get(agent_name=config.name)
            except ResourceNotFoundError:
                pass
            else:
                raise InputError("name", "azd requires a fresh isolated agent name; inspect existing versions.")
            start_stage(record, "azd_preparation")
            workspace = ROOT / ".artifacts" / record["run_id"] / "azd"
            try:
                run_azd(config, record, workspace)
            except Exception:
                if record["stage"] == "creation":
                    try:
                        discover_version(project, config, record)
                    except Exception:
                        record["version_discovery_status"] = "unavailable"
                raise
            created = discover_version(project, config, record)
            validate_container_state(created, config)
            version = activate_version(project, config, created, record)
            start_stage(record, "verification")
            record["smoke"] = verify_deployment(project, config, version)
            record["stages"]["verification"] = "passed"
            record["status"] = "passed"
    except Exception as error:
        record["status"] = "blocked" if isinstance(error, (InputError, VerificationBlocked)) or record["stage"] == "preflight" else "failed"
        record["stages"][record["stage"]] = record["status"]
        record["error"] = safe_error(error)
    finally:
        record["finished_at"] = utc_now()
        record["duration_seconds"] = round(time.monotonic() - started, 3)
        write_record(path, record)
    print(f"{args.method.upper()}/azd {record['status']}; stage={record['stage']}; evidence={path}")
    if record.get("agent_version"):
        print(f"Inspect agent={record['agent_name']} version={record['agent_version']} before retrying.")
    if record.get("error"):
        print(f"Error code: {record['error']['code']}; retain the workspace and inspect this run.", file=sys.stderr)
        if record["error"].get("field"):
            print(f"Invalid or missing input: {record['error']['field']}", file=sys.stderr)
    return 0 if record["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
