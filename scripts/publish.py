import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from dataclasses import replace
from urllib.parse import urljoin, urlsplit

import httpx

from azure.identity import AzureCliCredential

try:
    from .build_zip import ROOT
    from .preflight import Configuration, InputError, check_jfrog_connection, jfrog_settings, tool_versions
    from .verify import (
        VerificationBlocked, new_record, read_record, require_baselines, require_publication, safe_error, start_stage,
        utc_now, write_record,
    )
except ImportError:
    from build_zip import ROOT
    from preflight import Configuration, InputError, check_jfrog_connection, jfrog_settings, tool_versions
    from verify import (
        VerificationBlocked, new_record, read_record, require_baselines, require_publication, safe_error, start_stage,
        utc_now, write_record,
    )


DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
OBJECT_ID = re.compile(r"[a-f0-9-]{36}")
PUBLISHER_AUTH_HINTS = {
    "publisher_auth": "Run this command in your own interactive WSL terminal.",
    "publisher_token_empty": "No token was received. Paste once at the hidden prompt, then press Enter.",
    "publisher_token_format": "Copy only the full JWT access token, not its reference token, ID, or a login command.",
    "publisher_token_identity": "The token must contain a usable JFrog user subject.",
    "publisher_token_scope": "Generate a Group token for only the selected publisher group, without User or Admin scope.",
    "publisher_token_expiry": "Generate a fresh token with a lifetime of at most one hour.",
    "publisher_token_file": "Use an absolute, owner-only regular file outside the repository (chmod 600), containing only the token.",
}


def command_json(command, runner, **kwargs):
    return json.loads(runner(
        command, check=True, capture_output=True, text=True, timeout=60, **kwargs,
    ).stdout)


def publisher_object_id():
    with AzureCliCredential() as credential:
        token = credential.get_token("https://management.azure.com/.default")
    encoded = token.token.split(".")[1]
    principal = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))["oid"]
    if not isinstance(principal, str) or not OBJECT_ID.fullmatch(principal):
        raise InputError("publisher", "Unable to identify the current publisher.")
    return principal


def image_config_digest(local, directory, runner, env):
    archive_path = Path(directory) / "image.tar"
    runner(
        ["docker", "image", "save", "--output", str(archive_path), local["image_id"]],
        env=env, check=True, capture_output=True, text=True, timeout=180,
    )
    with tarfile.open(archive_path) as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        if len(manifest) != 1:
            raise InputError("image", "The local export must contain exactly one selected image.")
        member = archive.getmember(manifest[0]["Config"])
        if not member.isfile() or member.size > 1024 * 1024:
            raise InputError("image", "The local image config is invalid.")
        content = archive.extractfile(member).read()
    value = json.loads(content)
    if (
        value.get("os") != "linux" or value.get("architecture") != "amd64"
        or value.get("rootfs", {}).get("diff_ids") != local["layers"]
    ):
        raise InputError("image", "The exported config differs from the verified platform/layers.")
    archive_path.unlink()
    return "sha256:" + hashlib.sha256(content).hexdigest()


def registry_image(reference, tag, config_digest, local, runner, env):
    tagged = f"{reference}:{tag}"
    descriptor = command_json([
        "docker", "buildx", "imagetools", "inspect", tagged, "--format", "{{json .Manifest}}",
    ], runner, env=env)
    if "manifests" in descriptor:
        matches = [
            item for item in descriptor["manifests"]
            if item.get("platform", {}).get("os") == "linux"
            and item.get("platform", {}).get("architecture") == "amd64"
        ]
        if len(matches) != 1:
            raise InputError("image", "Publication must identify exactly one Linux amd64 manifest.")
        digest = matches[0]["digest"]
    else:
        digest = descriptor["digest"]
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise InputError("image", "The registry did not return an immutable manifest digest.")
    immutable = f"{reference}@{digest}"
    manifest = command_json([
        "docker", "buildx", "imagetools", "inspect", immutable, "--raw",
    ], runner, env=env)
    layers = [item["digest"] for item in manifest["layers"]]
    if manifest.get("config", {}).get("digest") != config_digest or len(layers) != len(local["layers"]) or any(
        not isinstance(layer, str) or not DIGEST.fullmatch(layer) for layer in layers
    ):
        raise InputError("image", "Remote image config/content differs from the locally verified image.")
    return {
        "image_reference": immutable, "publication_tag": tagged,
        "manifest_sha256": digest, "registry_layers": layers,
    }


def publish_acr(config, registry, repository, tag, local, record, runner=subprocess.run, *, existing=False):
    if not re.fullmatch(r"[a-z0-9]{5,50}", registry):
        raise InputError("registry", "Use an existing ACR resource name.")
    if not re.fullmatch(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*", repository):
        raise InputError("repository", "Use a lowercase repository path.")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag):
        raise InputError("tag", "Choose a valid isolated publication tag.")
    start_stage(record, "registry_preflight")
    details = command_json(["az", "acr", "show", "--name", registry, "--output", "json"], runner)
    target = details["loginServer"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]+", target):
        raise InputError("registry", "The registry returned an invalid login server.")
    project = command_json(["az", "resource", "show", "--ids", config.project_id, "--output", "json"], runner)
    runtime = project["identity"]["principalId"]
    publisher = publisher_object_id()
    if not isinstance(runtime, str) or not OBJECT_ID.fullmatch(runtime) or publisher == runtime:
        raise InputError("publisher", "Publisher and project pull identities must be distinct.")
    assignments = command_json([
        "az", "role", "assignment", "list", "--scope", details["id"], "--include-inherited",
        "--query", f"[?principalId=='{runtime}' || principalId=='{publisher}'].{{principalId:principalId,role:roleDefinitionName,scope:scope,condition:condition}}",
        "--output", "json",
    ], runner)
    mode = details.get("roleAssignmentMode")
    if mode == "LegacyRegistryPermissions":
        pull_role = "AcrPull"
    elif mode == "AbacRepositoryPermissions":
        pull_role = "Container Registry Repository Reader"
    else:
        raise InputError("registry", "The registry authorization mode is unknown.")
    runtime_roles = [
        {key: item.get(key) for key in ("role", "scope", "condition")}
        for item in assignments if item.get("principalId") == runtime
    ]
    publisher_roles = [
        {key: item.get(key) for key in ("role", "scope", "condition")}
        for item in assignments if item.get("principalId") == publisher
    ]
    if not any(item["role"] == pull_role for item in runtime_roles):
        raise InputError("runtime_pull", "The project pull identity needs the authorization-mode-specific reader role.")
    if mode == "AbacRepositoryPermissions" and any(item.get("condition") for item in runtime_roles):
        raise InputError("runtime_pull", "An administrator must validate repository-scoped ABAC conditions before publication.")
    policy = command_json([
        "az", "acr", "config", "authentication-as-arm", "show", "--registry", registry, "--output", "json",
    ], runner)
    if policy.get("status") != "enabled":
        raise InputError("registry", "ACR ARM-token authentication must already be enabled.")
    record.update({
        "registry": target, "registry_authorization_mode": mode,
        "runtime_pull_roles": runtime_roles, "publisher_roles": publisher_roles,
        "runtime_pull_identity": runtime,
    })
    reference = f"{target}/{repository}"
    tagged = f"{reference}:{tag}"
    record["publication_tag"] = tagged
    record["publication_action"] = "verification_only" if existing else "push"
    with tempfile.TemporaryDirectory(prefix="foundry-publisher-") as directory:
        env = {**os.environ, "DOCKER_CONFIG": directory}
        start_stage(record, "publisher_auth")
        runner(
            ["az", "acr", "login", "--name", registry, "--output", "none"],
            env=env, check=True, capture_output=True, text=True, timeout=60,
        )
        image = command_json(["docker", "image", "inspect", local["image_id"]], runner, env=env)[0]
        if image.get("Id") != local["image_id"] or image.get("RootFS", {}).get("Layers") != local["layers"]:
            raise InputError("image", "The local image differs from the verified build.")
        record["config_sha256"] = image_config_digest(local, directory, runner, env)
        start_stage(record, "publication")
        if not existing:
            runner(
                ["docker", "tag", local["image_id"], tagged],
                env=env, check=True, capture_output=True, text=True, timeout=30,
            )
            runner(
                ["docker", "push", tagged],
                env=env, check=True, capture_output=True, text=True, timeout=600,
            )
        return registry_image(reference, tag, record["config_sha256"], local, runner, env)


def read_publisher_token(token_file=None):
    if token_file is not None:
        try:
            path = Path(token_file)
            if not path.is_absolute() or path.is_symlink():
                raise ValueError
            resolved = path.resolve(strict=True)
            if resolved == ROOT or ROOT in resolved.parents:
                raise ValueError
            descriptor = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                metadata = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(metadata.st_mode) & 0o077 or metadata.st_size > 32768
                ):
                    raise ValueError
                content = stream.read(32769)
                if len(content) > 32768:
                    raise ValueError
            return content.decode("utf-8-sig").strip()
        except (OSError, ValueError):
            raise InputError("publisher_token_file", PUBLISHER_AUTH_HINTS["publisher_token_file"]) from None
    if not sys.stdin.isatty():
        raise InputError("publisher_auth", "Run in your own interactive terminal for hidden token entry.")
    return getpass.getpass("Short-lived JFrog publisher token (never paste in chat): ").strip()


def publisher_token_identity(token, group, now=None):
    now = time.time() if now is None else now
    if not token:
        raise InputError("publisher_token_empty", PUBLISHER_AUTH_HINTS["publisher_token_empty"])
    try:
        parts = token.split(".")
        if len(parts) != 3 or len(token) > 32768:
            raise ValueError
        encoded = parts[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if not isinstance(claims, dict):
            raise ValueError
    except (ValueError, TypeError):
        raise InputError("publisher_token_format", PUBLISHER_AUTH_HINTS["publisher_token_format"]) from None
    subject = claims.get("sub")
    username = subject.split("/users/", 1)[-1] if isinstance(subject, str) and "/users/" in subject else ""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9@._+-]{0,255}", username):
        raise InputError("publisher_token_identity", PUBLISHER_AUTH_HINTS["publisher_token_identity"])
    scope_claims = [claims[key] for key in ("scp", "scope") if key in claims]
    if not scope_claims:
        raise InputError("publisher_token_scope", PUBLISHER_AUTH_HINTS["publisher_token_scope"])
    expected_group = re.escape(group)
    for scope in scope_claims:
        scope = scope.split() if isinstance(scope, str) else scope
        if not isinstance(scope, list) or not all(isinstance(item, str) and item for item in scope):
            raise InputError("publisher_token_scope", PUBLISHER_AUTH_HINTS["publisher_token_scope"])
        group_scopes = [item for item in scope if item != "api:*"]
        if (
            len(group_scopes) != 1
            or not re.fullmatch(
                rf'applied-permissions/groups:(?:"{expected_group}"|{expected_group}),?',
                group_scopes[0],
            )
        ):
            raise InputError("publisher_token_scope", PUBLISHER_AUTH_HINTS["publisher_token_scope"])
    expiry, issued = claims.get("exp"), claims.get("iat")
    if (
        not isinstance(expiry, (int, float)) or not isinstance(issued, (int, float))
        or not now < expiry <= issued + 3600 or issued > now + 60
    ):
        raise InputError("publisher_token_expiry", PUBLISHER_AUTH_HINTS["publisher_token_expiry"])
    # Claims constrain local handling; the registry, not this decoder, validates the signature.
    return username


def independent_jfrog_pull(origin, repository, publication, local, username, token, *, transport=None):
    manifest_url = f"{origin}/v2/{repository}/manifests/{publication['manifest_sha256']}"
    deadline = time.monotonic() + 600
    with httpx.Client(timeout=30, follow_redirects=False, transport=transport) as client:
        challenge = client.get(manifest_url)
        header = challenge.headers.get("www-authenticate", "")
        if challenge.status_code != 401 or not header.lower().startswith("bearer "):
            raise InputError("image_pull", "The independent pull requires an authenticated registry challenge.")
        pairs = re.findall(r'([A-Za-z_]+)="([^"]*)"', header[7:])
        parameters = dict(pairs)
        realm = urlsplit(parameters.get("realm", ""))
        scopes = {
            f"repository:{repository}:pull",
            f"repository:{repository.split('/', 1)[-1]}:pull",
        }
        if (
            len(parameters) != len(pairs) or realm.scheme != "https"
            or realm.netloc != urlsplit(origin).netloc or realm.username or realm.password
            or realm.query or realm.fragment
            or parameters.get("service") != urlsplit(origin).netloc
            or parameters.get("scope") not in scopes
        ):
            raise InputError("image_pull", "The registry returned an unapproved authentication realm or scope.")
        response = client.get(
            parameters["realm"], params={key: parameters[key] for key in ("service", "scope")},
            auth=httpx.BasicAuth(username, token),
        )
        response.raise_for_status()
        bearer = response.json().get("token") or response.json().get("access_token")
        if not isinstance(bearer, str) or not bearer or len(bearer) > 32768:
            raise InputError("image_pull", "The registry did not issue a usable pull credential.")
        headers = {
            "Authorization": "Bearer " + bearer,
            "Accept": "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json",
        }
        response = client.get(manifest_url, headers=headers)
        response.raise_for_status()
        if "sha256:" + hashlib.sha256(response.content).hexdigest() != publication["manifest_sha256"]:
            raise InputError("image_pull", "The independent manifest digest differs.")
        manifest = response.json()
        if (
            manifest.get("config", {}).get("digest") != publication["config_sha256"]
            or [item.get("digest") for item in manifest.get("layers", [])] != publication["registry_layers"]
        ):
            raise InputError("image_pull", "The independent manifest content differs.")
        descriptors = [manifest["config"], *manifest["layers"]]
        for index, descriptor in enumerate(descriptors):
            digest = descriptor["digest"]
            url = f"{origin}/v2/{repository}/blobs/{digest}"
            blob_headers = {"Authorization": headers["Authorization"]}
            hasher, size, content = hashlib.sha256(), 0, bytearray()
            for attempt in range(6):
                with client.stream("GET", url, headers=blob_headers) as blob:
                    if blob.is_redirect:
                        target = urljoin(url, blob.headers.get("location", ""))
                        parsed = urlsplit(target)
                        if (
                            attempt == 5 or parsed.scheme != "https" or not parsed.hostname
                            or parsed.username or parsed.password
                        ):
                            raise InputError("image_pull", "A blob redirect is invalid or does not preserve HTTPS.")
                        if parsed.netloc != urlsplit(url).netloc:
                            blob_headers = {}
                        url = target
                        continue
                    blob.raise_for_status()
                    for chunk in blob.iter_raw():
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Independent pull deadline expired.")
                        size += len(chunk)
                        if size > descriptor["size"] or (index == 0 and size > 1024 * 1024):
                            raise InputError("image_pull", "A registry blob exceeds its declared size.")
                        hasher.update(chunk)
                        if index == 0:
                            content.extend(chunk)
                break
            if size != descriptor["size"] or "sha256:" + hasher.hexdigest() != digest:
                raise InputError("image_pull", "An independently downloaded blob differs.")
            if index == 0:
                config = json.loads(content)
                if (
                    config.get("os") != "linux" or config.get("architecture") != "amd64"
                    or config.get("rootfs", {}).get("diff_ids") != local["layers"]
                ):
                    raise InputError("image_pull", "The independently pulled config differs from the verified build.")


def publish_jfrog(
    config, registry, repository, tag, local, record, acr_publication, publisher_group,
    runner=subprocess.run, *, existing=False, token_reader=read_publisher_token,
):
    settings = jfrog_settings()
    if registry != urlsplit(settings["origin"]).netloc:
        raise InputError("registry", "The publication registry must match the approved JFrog origin.")
    if not re.fullmatch(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*", repository) or "/" not in repository:
        raise InputError("repository", "Use the Docker repository key and image path from Set Me Up.")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag):
        raise InputError("tag", "Choose a valid isolated publication tag.")
    if not publisher_group or not re.fullmatch(r"[A-Za-z0-9_-]+", publisher_group):
        raise InputError("publisher_group", "Select the separate repository-scoped publisher group.")
    start_stage(record, "registry_preflight")
    reference = f"{registry}/{repository}"
    connection_config = replace(
        config, method="jfrog", registry_connection=os.environ.get("REGISTRY_CONNECTION_NAME"),
        image=reference + "@" + acr_publication["manifest_sha256"],
    ).validate()
    record.update(check_jfrog_connection(connection_config))
    record.update({
        "registry": registry, "publisher_group": publisher_group,
        "publication_tag": f"{reference}:{tag}",
        "publication_action": "verification_only" if existing else "push",
        "acr_manifest_sha256": acr_publication["manifest_sha256"],
    })
    with tempfile.TemporaryDirectory(prefix="foundry-jfrog-publisher-") as directory:
        env = {**os.environ, "DOCKER_CONFIG": directory}
        image = command_json(["docker", "image", "inspect", local["image_id"]], runner, env=env)[0]
        if image.get("Id") != local["image_id"] or image.get("RootFS", {}).get("Layers") != local["layers"]:
            raise InputError("image", "The local image differs from the verified build.")
        record["config_sha256"] = image_config_digest(local, directory, runner, env)
        if record["config_sha256"] != acr_publication["config_sha256"]:
            raise InputError("image", "Local and ACR image configs differ.")
        start_stage(record, "publisher_auth")
        token = token_reader()
        username = publisher_token_identity(token, publisher_group)
        runner(
            ["docker", "login", registry, "--username", username, "--password-stdin"],
            input=token, env=env, check=True, capture_output=True, text=True, timeout=60,
        )
        start_stage(record, "publication")
        if not existing:
            runner(
                ["docker", "tag", local["image_id"], record["publication_tag"]],
                env=env, check=True, capture_output=True, text=True, timeout=30,
            )
            runner(
                ["docker", "push", record["publication_tag"]],
                env=env, check=True, capture_output=True, text=True, timeout=600,
            )
        result = registry_image(reference, tag, record["config_sha256"], local, runner, env)
        if result["registry_layers"] != acr_publication["registry_layers"]:
            raise InputError("image", "JFrog and ACR compressed layer identities differ.")
        record.update(result)
        record["manifest_comparison"] = (
            "identical" if result["manifest_sha256"] == acr_publication["manifest_sha256"]
            else "different_representation_matching_config_and_ordered_layers"
        )
        start_stage(record, "independent_pull")
        independent_jfrog_pull(settings["origin"], repository, record, local, username, token)
        record["independent_pull"] = "passed"
        record["stages"]["independent_pull"] = "passed"
        record["stage"] = "publication"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Publish the already verified image without rebuilding.")
    parser.add_argument("--method", choices=["acr", "jfrog"], required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--zip-evidence", type=Path, required=True)
    parser.add_argument("--local-evidence", type=Path, required=True)
    parser.add_argument("--acr-publication-evidence", type=Path, help="JFrog requires the verified ACR content record.")
    parser.add_argument("--publisher-group", help="JFrog group with repository-scoped Read and Deploy/Cache only.")
    parser.add_argument(
        "--publisher-token-file", type=Path,
        help="Optional absolute path to an owner-only temporary token file outside the repository.",
    )
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--existing-tag", help="Verify a retained publication tag without tagging or pushing again.")
    parser.add_argument("--approve-cloud", action="store_true")
    args = parser.parse_args(argv)
    if args.publisher_token_file and args.method != "jfrog":
        parser.error("--publisher-token-file is only supported for JFrog.")
    record = new_record()
    path = args.evidence or ROOT / ".artifacts" / record["run_id"] / "publication.json"
    if path.exists() or path.is_symlink():
        parser.error("Evidence already exists; choose a new path.")
    started = time.monotonic()
    try:
        if not args.approve_cloud:
            raise InputError("approve_cloud", "Explicit registry publication approval is required.")
        config = Configuration.from_env("zip", "registry-publication")
        zip_record, local = read_record(args.zip_evidence), read_record(args.local_evidence)
        require_baselines(config, zip_record, local)
        acr_publication = None
        if args.method == "jfrog":
            if not args.acr_publication_evidence:
                raise InputError("baseline", "JFrog publication requires --acr-publication-evidence.")
            acr_publication = read_record(args.acr_publication_evidence)
            acr_config = replace(config, method="acr", image=acr_publication.get("image_reference")).validate()
            require_publication(acr_config, zip_record, local, acr_publication)
        context = new_record(config)
        context["run_id"], context["started_at"] = record["run_id"], record["started_at"]
        record.update(context)
        record.update({"method": args.method, "entry_point": "docker"})
        record["tools"].update(tool_versions(container=True))
        for key in ("image_id", "platform", "layers", "zip_sha256", "dockerfile_sha256", "dockerignore_sha256"):
            record[key] = local[key]
        if args.method == "acr":
            result = publish_acr(
                config, args.registry, args.repository, args.existing_tag or record["run_id"], local, record,
                existing=bool(args.existing_tag),
            )
        else:
            result = publish_jfrog(
                config, args.registry, args.repository, args.existing_tag or record["run_id"], local, record,
                acr_publication, args.publisher_group, existing=bool(args.existing_tag),
                token_reader=lambda: read_publisher_token(args.publisher_token_file),
            )
        record.update(result)
        record["status"] = "passed"
        record["stages"]["publication"] = "passed"
    except Exception as error:
        record["status"] = "blocked" if isinstance(error, (InputError, VerificationBlocked)) else "failed"
        record["stages"][record["stage"]] = record["status"]
        record["error"] = safe_error(error)
    finally:
        record["finished_at"] = utc_now()
        record["duration_seconds"] = round(time.monotonic() - started, 3)
        write_record(path, record)
    print(f"Publication {record['status']}; stage={record['stage']}; evidence={path}")
    if record.get("image_reference"):
        print(f"Registry image: {record['image_reference']}")
    if record.get("error"):
        print(f"Error code: {record['error']['code']}; retain this run before retrying.", file=sys.stderr)
        if record["error"].get("field"):
            print(f"Invalid or missing input: {record['error']['field']}", file=sys.stderr)
            hint = PUBLISHER_AUTH_HINTS.get(record["error"]["field"])
            if hint:
                print(hint, file=sys.stderr)
    return 0 if record["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
