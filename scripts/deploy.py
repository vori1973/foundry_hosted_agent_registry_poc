import argparse
import re
import sys
import time
from pathlib import Path
from zipfile import BadZipFile

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    CodeConfiguration,
    ContainerConfiguration,
    FixedRatioVersionSelectionRule,
    HostedAgentDefinition,
    ProtocolVersionRecord,
    VersionSelector,
)
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential

try:
    from .build_zip import ROOT, validate_zip
    from .preflight import Configuration, InputError, check_jfrog_connection, positive_timeout, tool_versions
    from .verify import (
        CHANGE, VerificationBlocked, field, new_record, read_record, require_publication, safe_error, start_stage,
        utc_now, validate_resume, verify_deployment, wait_for_active, write_record,
    )
except ImportError:
    from build_zip import ROOT, validate_zip
    from preflight import Configuration, InputError, check_jfrog_connection, positive_timeout, tool_versions
    from verify import (
        CHANGE, VerificationBlocked, field, new_record, read_record, require_publication, safe_error, start_stage,
        utc_now, validate_resume, verify_deployment, wait_for_active, write_record,
    )


def deployment_definition(config):
    config.validate()
    source = {
        "code_configuration": CodeConfiguration(
            runtime="python_3_13", entry_point=["python", "main.py"], dependency_resolution="bundled",
        )
    } if config.method == "zip" else {"container_configuration": ContainerConfiguration(
        image=config.image,
        **({"registry_connection_id": config.registry_connection} if config.method == "jfrog" else {}),
    )}
    return HostedAgentDefinition(
        cpu=config.cpu,
        memory=config.memory,
        **source,
        protocol_versions=[ProtocolVersionRecord(protocol="responses", version="2.0.0")],
        environment_variables={
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": config.model,
            "DEPLOYMENT_SOURCE": config.method,
            "PYTHONNOUSERSITE": "1",
        },
    )


def verify_ownership(project, config):
    try:
        existing = project.agents.get(agent_name=config.name)
    except ResourceNotFoundError:
        return
    latest = field(field(existing, "versions", {}), "latest", {})
    metadata = field(latest, "metadata", {}) or {}
    if metadata.get("poc_change") != CHANGE:
        raise ValueError("Agent name is already in use outside this POC; choose a fresh name.")


def bind_version(project, name, version):
    project.agents.update_details(
        agent_name=name,
        agent_endpoint=AgentEndpointConfig(
            version_selector=VersionSelector(version_selection_rules=[
                FixedRatioVersionSelectionRule(
                    agent_version=version,
                    traffic_percentage=100,
                )
            ])
        ),
    )


def deploy_zip(project, config, zip_path, record):
    start_stage(record, "ownership")
    verify_ownership(project, config)
    start_stage(record, "creation")
    with zip_path.open("rb") as code:
        created = project.agents.create_version_from_code(
            agent_name=config.name,
            definition=deployment_definition(config),
            code=code,
            code_zip_sha256=record["zip_sha256"],
            description="Model-backed Responses registry deployment POC; bundled source ZIP.",
            metadata={
                "poc_change": CHANGE,
                "poc_baseline": record["baseline_fingerprint"],
                "poc_method": config.method,
                "poc_run": record["run_id"],
            },
        )
    return activate_version(project, config, created, record)


def activate_version(project, config, created, record):
    version = str(field(created, "version", ""))
    if not version.isalnum() or len(version) > 64 or field(created, "name") != config.name:
        raise RuntimeError("Creation returned an invalid agent/version identity.")
    record["agent_version"] = version
    start_stage(record, "activation")
    wait_for_active(project, config.name, version, config.timeout)
    start_stage(record, "endpoint_binding")
    bind_version(project, config.name, version)
    return version


def registry_evidence(config, args, record):
    if not all((args.zip_evidence, args.local_evidence, args.publication_evidence)):
        raise InputError("baseline", "Registry deployment requires ZIP, local, and publication evidence.")
    paths = (
        args.zip_evidence, args.local_evidence, args.publication_evidence,
    )
    if config.method == "jfrog":
        predecessors = (
            args.acr_publication_evidence, args.acr_sdk_evidence, args.acr_azd_evidence,
        )
        if not all(predecessors):
            raise InputError("baseline", "JFrog requires ACR publication, SDK and azd evidence.")
        paths += predecessors
    records = tuple(read_record(path) for path in paths)
    publication = require_publication(config, *records)
    for key in (
        "zip_sha256", "image_id", "platform", "layers", "dockerfile_sha256", "dockerignore_sha256",
        "config_sha256", "image_reference", "manifest_sha256", "registry_layers",
        "registry", "registry_authorization_mode", "runtime_pull_identity", "runtime_pull_roles", "publisher_roles",
        "registry_connection", "acr_manifest_sha256", "manifest_comparison", "independent_pull",
    ):
        if key in publication:
            record[key] = publication[key]
    return records


def validate_container_state(state, config):
    definition = field(state, "definition", {})
    desired = deployment_definition(config).as_dict()
    actual = definition.as_dict() if hasattr(definition, "as_dict") else definition
    if any(actual.get(key) != value for key, value in desired.items()) or actual.get("code_configuration"):
        raise VerificationBlocked("The deployed container definition differs from the selected workload/image.")


def deploy_container(project, config, record, records):
    require_publication(config, *records)
    if config.method == "jfrog":
        start_stage(record, "registry_preflight")
        record.update(check_jfrog_connection(config, project=project))
    start_stage(record, "ownership")
    verify_ownership(project, config)
    start_stage(record, "creation")
    created = project.agents.create_version(
        agent_name=config.name, definition=deployment_definition(config),
        description=f"Model-backed Responses POC; verified prebuilt {config.method.upper()} image.",
        metadata={
            "poc_change": CHANGE, "poc_baseline": record["baseline_fingerprint"],
            "poc_method": config.method, "poc_run": record["run_id"],
        },
    )
    record["agent_version"] = str(field(created, "version", ""))
    validate_container_state(created, config)
    return activate_version(project, config, created, record)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deploy or verify a ZIP, ACR or direct-JFrog Responses agent.")
    parser.add_argument("--method", choices=["zip", "acr", "jfrog"], required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--image", help="Digest-qualified verified registry image.")
    parser.add_argument("--zip-evidence", type=Path)
    parser.add_argument("--local-evidence", type=Path)
    parser.add_argument("--publication-evidence", type=Path)
    parser.add_argument("--acr-publication-evidence", type=Path)
    parser.add_argument("--acr-sdk-evidence", type=Path)
    parser.add_argument("--acr-azd-evidence", type=Path)
    parser.add_argument("--version", help="Verify an existing matching version without redeploying or changing routing.")
    parser.add_argument("--timeout", type=positive_timeout, default=600)
    parser.add_argument("--evidence", type=Path, help="New evidence filename; existing files are never overwritten.")
    parser.add_argument("--approve-cloud", action="store_true", help="Confirm selected cloud operations and inference charges.")
    args = parser.parse_args(argv)
    if args.method == "zip" and bool(args.zip) == bool(args.version):
        parser.error("Choose exactly one of --zip or --version.")
    if args.method != "zip" and (args.zip or not args.image):
        parser.error("Registry deployment requires --image and forbids --zip.")
    if args.version and not args.version.isalnum():
        parser.error("--version must be an alphanumeric version identifier.")
    record = new_record()
    started = time.monotonic()
    path = args.evidence or ROOT / ".artifacts" / record["run_id"] / "deployment.json"
    if path.exists() or path.is_symlink():
        parser.error("Evidence path already exists; choose a new path.")
    try:
        if not args.approve_cloud:
            raise InputError("approve_cloud", "Explicit cloud approval is required.")
        config = Configuration.from_env(args.method, args.name, args.image, timeout=args.timeout)
        context = new_record(config)
        context["run_id"], context["started_at"] = record["run_id"], record["started_at"]
        record.update(context)
        record["tools"].update(tool_versions())
        records = registry_evidence(config, args, record) if config.method != "zip" else None
        if args.zip:
            try:
                record["zip_sha256"] = validate_zip(args.zip)
            except (OSError, ValueError, BadZipFile):
                raise InputError("zip", "ZIP validation failed; rebuild from the current source.") from None
        with DefaultAzureCredential() as credential, AIProjectClient(
            endpoint=config.endpoint, credential=credential, allow_preview=True,
            retry_total=0, connection_timeout=10, read_timeout=30,
        ) as project:
            if config.method == "jfrog" and args.version:
                start_stage(record, "registry_preflight")
                record.update(check_jfrog_connection(config, project=project))
            if args.version:
                record["agent_version"] = args.version
                start_stage(record, "resume_validation")
                retained = validate_resume(project, config, args.version)
                if config.method == "zip":
                    code = field(field(retained, "definition", {}), "code_configuration", {})
                    digest = field(code, "content_hash", "")
                    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                        raise VerificationBlocked("The retained ZIP artifact digest is unavailable.")
                    record["zip_sha256"] = digest
                else:
                    validate_container_state(retained, config)
                version = args.version
            elif config.method == "zip":
                version = deploy_zip(project, config, args.zip, record)
            else:
                version = deploy_container(project, config, record, records)
            start_stage(record, "verification")
            record["smoke"] = verify_deployment(project, config, version)
            record["stages"]["verification"] = "passed"
            record["status"] = "passed"
    except Exception as error:
        record["status"] = (
            "blocked" if record["stage"] == "preflight" or isinstance(error, VerificationBlocked) else "failed"
        )
        record["stages"][record["stage"]] = record["status"]
        record["error"] = safe_error(error)
    finally:
        record["finished_at"] = utc_now()
        record["duration_seconds"] = round(time.monotonic() - started, 3)
        write_record(path, record)
    print(f"{args.method.upper()} deployment {record['status']}; stage={record['stage']}; evidence={path}")
    if record.get("agent_version"):
        print(f"Inspect agent={record['agent_name']} version={record['agent_version']} before retrying.")
    if record.get("error"):
        print(f"Error code: {record['error']['code']}; run preflight and inspect the failing stage.", file=sys.stderr)
        if record["error"].get("field"):
            print(f"Invalid or missing input: {record['error']['field']}", file=sys.stderr)
    return 0 if record["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
