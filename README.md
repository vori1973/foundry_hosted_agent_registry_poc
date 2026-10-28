# Foundry Hosted Agent Registry POC

## Overview

Compare the same model-backed Microsoft Foundry Hosted Agent deployed from a
source ZIP, Azure Container Registry, and directly from JFrog Artifactory.
The agent interprets natural-language requests through Responses 2.0.0.
APIM and MCP are not part of this POC.

Implementation is tracked by [#1](https://github.com/vori1973/foundry_hosted_agent_registry_poc/issues/1)
and [the OpenSpec change](openspec/changes/hosted-agent-three-method-deployment/).
This repository is being implemented in stages; a plan or successful offline
test is not evidence that a cloud deployment has succeeded.

## Getting started

Use Python 3.13 and an isolated virtual environment:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

The verified dependency set uses `agent-framework-foundry==1.10.1`,
`agent-framework-foundry-hosting==1.0.0b261022`,
`azure-ai-projects==2.8.0`, and `azure-identity==1.27.0`.
Both lock files pin the same runtime graph. To update dependencies, resolve the
deployment and runtime inputs together before constraining the runtime lock:

```bash
uv pip compile --prerelease=allow --python python3.13 --python-platform x86_64-manylinux2014 requirements-dev.in --output-file requirements-dev.txt
uv pip compile --prerelease=allow --python python3.13 --python-platform x86_64-manylinux2014 --constraint requirements-dev.txt agent/requirements.in --output-file agent/requirements.txt
```

On WSL, package installation is substantially faster in a virtual environment on
the Linux filesystem than on a Windows/OneDrive mount. Such an environment may
be activated in place of `.venv`; do not commit its path or contents.

Application and helper files are added as their implementation tasks complete.
Do not run a later stage until its documented prerequisites and matching
baseline evidence exist.

For live execution, select an existing Foundry project, supported region and
model deployment. Ensure sufficient hosting/inference capacity, project
deployment permissions, and approved connectivity. The hosted model-calling
identity and registry pull identity are separate concerns.

Use local environment configuration only; never commit populated `.env` files.
Runtime model access uses an approved Azure identity, not an embedded API key.
Foundry supplies its reserved project/agent context variables to the hosted
runtime; do not redeclare them in deployment definitions.

### Operator preflight checklist

Before any live deployment, record the following checks outside source control:

| Input | Required check |
|---|---|
| Project | Confirm the exact project ARM ID and `/api/projects/<project>` endpoint refer to the same account/project |
| Region and capacity | Confirm Hosted Agents and Python 3.13 are supported in the selected region and the project has hosting capacity for CPU `0.5`/memory `1Gi` |
| Model | Select an existing Responses-capable model deployment; confirm inference quota and an authorized synthetic inference request |
| Deployment identity | Confirm Foundry Project Manager or equivalent approved deployment permissions at the selected project scope |
| Model identity | Verify the platform-created hosted agent identity can invoke the selected model; do not confuse it with the registry pull identity |
| Network | Verify client-to-project, hosted-runtime-to-model, and platform-to-registry/token HTTPS paths, DNS, routing, firewall rules and certificate trust |
| ACR | Inspect the registry authorization mode and project pull identity; record the narrowest applicable pull role/repository scope separately from publisher push permissions |
| JFrog | Obtain administrator confirmation of compatible token exchange, expected issuer/audience/identity claims, provider name, repository, and read/pull-only mapping |
| JFrog connection | Confirm the connection exists in this project with the correct HTTPS target and token-exchange metadata; never dump its credentials |
| Test ownership | Select isolated POC agent names and test resources; obtain explicit approval for billable mutations and permission-changing negative tests |

Older projects and private registries have additional compatibility restrictions;
verify them against the current
[hosted-agent prerequisites](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent#prerequisites)
and [external-registry guide](https://learn.microsoft.com/azure/foundry/agents/how-to/private-registry-connections).
This POC does not provision networking, a model deployment, or a new Foundry
estate. Missing approval/connectivity is a blocker, not a reason to enable public
access or disable certificate checks.

The local input checker makes no cloud mutations:

```bash
python scripts/preflight.py --method zip --name registry-hosted-agent-zip --check-tools
```

Set `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_PROJECT_ID`, and
`AZURE_AI_MODEL_DEPLOYMENT_NAME` in your local shell first. `--check-tools`
requires Python 3.13 and Azure CLI 2.80+; registry methods also check Docker server
availability, and `--entry-point azd` requires azd 1.32+. Check the installed
Foundry extension separately against the current platform documentation.
Registry deployment inputs use a fully qualified digest-pinned image with
`--image registry/repository@sha256:<digest>`; publication tags alone are not
proof of immutable identity.

JFrog CLI is optional: Docker-compatible tooling can tag, push, and pull images.
No Copilot-to-JFrog MCP connection is required. Such a connection would assist
development workflows only; it would not replace the Foundry project managed
identity, JFrog OIDC trust, or runtime registry connection.

An `inputs_valid` result is only local validation. It does not assert region,
quota, cloud permission, model access, network connectivity, registry trust, or
live deployment success.

## Architecture and progression

`agent/` contains the standalone runtime. `scripts/` contains packaging and
operational helpers. `deploy/` contains separate azd registry configurations.
No component depends on the external Echo MCP reference checkout.

The required progression is:

```text
New ZIP active + Responses smoke
  -> Same-source local container + model smoke
  -> ACR active + Responses smoke
  -> Identical image directly from JFrog + Responses smoke
```

Both ACR and JFrog must be exercised through azd and the Python SDK.
JFrog runtime pulls use project managed identity/OIDC and a same-project
registry connection, not publisher credentials or an ACR relay.
Generated local artifacts and sanitized run evidence belong under ignored
`.artifacts/<run-id>/`. Never put tokens, credential files, customer content,
or raw token-exchange responses there.

## Local Responses agent

After installation, authenticate with your approved developer identity (for
example, `az login` if permitted), then set nonsecret runtime configuration:

```bash
export FOUNDRY_PROJECT_ENDPOINT="https://<account>.services.ai.azure.com/api/projects/<project>"
export AZURE_AI_MODEL_DEPLOYMENT_NAME="<existing-model-deployment>"
export AGENT_NAME="registry-hosted-agent-local"
export DEPLOYMENT_SOURCE="zip"
python agent/main.py
```

In another terminal:

```bash
curl --fail-with-body http://localhost:8088/readiness
curl --fail-with-body http://localhost:8088/responses \
  -H 'Content-Type: application/json' \
  -d '{"input":"Explain why this deployment works.","stream":false,"store":false}'
```

The local listener is not authenticated: use it only on an approved development
machine/network and do not expose port 8088 publicly. The model call still needs
Azure authentication, inference permission, quota, and network access. Hosted
execution uses the platform's agent identity instead of your developer login.
The host forces sensitive-content telemetry off; do not enable prompt/credential
logging in surrounding infrastructure.

The common deployment smoke test asks:

```text
Give a short deployment confirmation. Include your configured agent name and
deployment source, and include this exact test marker: <fresh-random-marker>.
```

The helper generates a fresh marker and requires a completed, nonempty model
response containing it and the expected labels. Refusal, incomplete output,
model errors, missing labels, or readiness alone do not pass. Evidence retains
only the validated synthetic fields and safe correlation identifiers, not
arbitrary model output. Offline tests exercise the real Responses host against
a stub model; they do not prove live Foundry model connectivity.

## Container build

After the live ZIP baseline passes, build once for Linux x86_64:

```bash
LOCAL_IMAGE="foundry-registry-poc:$(date -u +%Y%m%d%H%M%S)"
python scripts/build_container.py \
  --zip .artifacts/zip-baseline/agent.zip --tag "$LOCAL_IMAGE"
docker image inspect "$LOCAL_IMAGE" --format '{{.Id}} {{.Os}}/{{.Architecture}} {{json .RootFS.Layers}}'
```

The Dockerfile pins the Python 3.13 base image by digest. The helper validates
the ZIP against current source/lock files, extracts its already bundled
dependencies to a temporary named build context, and runs
`docker build --platform linux/amd64 --build-context runtime=<temporary-path>`.
No package download or separate dependency resolution happens inside Docker;
normal certificate verification remains enabled for ZIP packaging and base-image
downloads. Docker with BuildKit named-context support is required.

The main build context allows only the Dockerfile and the two runtime files;
the additional context contains the validated ZIP payload. Credentials, local
state, tests, and deployment helpers are excluded. The application runs as an
unprivileged user on port 8088.
`AGENTSERVER_STATE_ROOT=/tmp/agentserver` gives the hosting library an ephemeral
writable state directory; it initializes this directory even for `store:false`.
Local read-only execution supplies `/tmp` as an in-memory mount.
No project/model settings or credentials belong in build arguments or image
layers. The helper refuses an existing tag, checks installed pins and source
identity in a network-disabled container, and records the immutable local image ID,
ordered uncompressed layer identities, platform, source/dependency hashes, ZIP
hash, and Dockerfile/context-policy hashes in unique ignored build evidence.
Keep that record and reuse this image rather than rebuilding for each registry.

An image build does not prove local model access. The local-container smoke
additionally requires an explicitly approved short-lived developer identity
outside the image and approval for synthetic model inference. Do not mount your
whole Azure CLI credential cache, bake credentials into the image, or publish a
local unauthenticated listener beyond loopback. Registry publication remains
blocked until matching ZIP and local-container smoke evidence exists.

### Local container model smoke

After approving one synthetic inference request against the selected project
and model, use the successful live ZIP and container build records:

```bash
python scripts/local_smoke.py --name registry-hosted-agent-local \
  --zip-evidence .artifacts/<zip-run>/deployment.json \
  --build-evidence .artifacts/<build-run>/build.json \
  --timeout 60 --approve-cloud
```

The helper validates the current source, build definition, baseline fingerprint,
and immutable local image before inference. On the host, your existing Azure
CLI login obtains one short-lived token for `https://ai.azure.com`. It passes
the token through standard input into an in-memory container mount, never
through build arguments, environment variables, a host credential file, or
console output. No Azure CLI credential cache is mounted.

The temporary `scripts/local_azure_cli.py` adapter serves only the Azure
Identity SDK's `account get-access-token` operation for that audience. It is
injected at runtime, excluded from the image, cannot refresh tokens, and rejects
expired tokens. Local `DefaultAzureCredential` is restricted to that adapter
using `AZURE_TOKEN_CREDENTIALS=AzureCliCredential`. This is a local-test mechanism,
not the hosted model identity or a general Azure CLI installation.
The identity tmpfs explicitly allows execution of this adapter; the separate
`/tmp` state mount stays `noexec`. The helper checks the pinned SDK can obtain
the scoped token inside the container before attempting model inference.

The application still executes the image's unchanged `main.py`, noninteractively,
as its unprivileged user with a read-only root filesystem. Only loopback exposes
the unauthenticated local Responses endpoint. The helper waits for readiness,
sends the common smoke exactly once, retains only sanitized evidence, and
stops/removes the temporary container and its token mount even on failure. It
does not retry model generations or create a Foundry version.

### Registry baseline gate

Registry input preflight additionally requires both successful predecessor
records, even when tool checks are omitted:

```bash
python scripts/preflight.py --method acr --name registry-hosted-agent-acr \
  --image "<registry>/<repository>@sha256:<manifest-digest>" \
  --zip-evidence .artifacts/<zip-run>/deployment.json \
  --local-evidence .artifacts/<local-run>/local-smoke.json --check-tools
```

Missing, failed, or stale model/configuration/source evidence blocks progression.
The gate checks completed model-smoke assertions, ZIP identity, immutable local
image and layer identities, current Dockerfile/context policy, and local
readiness/cleanup. It does not create an agent version. Registry deployment
entry points must enforce this shared check themselves before mutation; passing
preflight alone is not authorization or proof of registry pull permissions.
ZIP verification-resume evidence includes the artifact SHA-256 reported by the
retained version. If that digest is unavailable, resume is blocked rather than
producing a baseline that cannot identify its artifact.

## ACR publication

Use an explicitly selected existing registry/repository. The publisher identity
must be different from the Foundry project managed identity. Publisher access
needs `AcrPush` for legacy registries, or the appropriate repository writer role
for ABAC mode. Runtime pulls need the project's `AcrPull` assignment for legacy
mode, or `Container Registry Repository Reader` for ABAC mode. Conditional ABAC
assignments require administrator validation; this helper fails closed rather
than guessing that a condition covers the repository.

Check `az acr show` for the registry authorization mode and network policy, and
`az acr config authentication-as-arm show --registry <registry>` for an already
enabled ARM-token policy. Inspect project identity with
`az resource show --ids "$FOUNDRY_PROJECT_ID" --query identity.principalId`.
Record publisher and runtime assignments separately. Role assignments, registry
connections, and policy/network changes are separate approved operator actions,
not publication side effects. For azd, verify a same-project `ContainerRegistry`
connection targets the selected ACR and uses the existing project identity.

After explicit approval for image publication:

```bash
bash scripts/publish.sh --method acr --registry "<existing-acr-name>" \
  --repository "foundry-hosted-agent-registry-poc" \
  --zip-evidence .artifacts/<zip-run>/deployment.json \
  --local-evidence .artifacts/<local-run>/local-smoke.json --approve-cloud
```

Activate the Python 3.13 environment first, or set `PYTHON` to its executable.
The helper enforces both predecessor gates, audits the two permission sets,
authenticates using the current Azure CLI publisher identity with temporary
Docker credential state outside `.artifacts`, and tags/pushes the immutable
verified image ID. It never rebuilds or imports an image.

The unique publication tag is not the deployment identity. Docker's local image
ID may identify an OCI index rather than a config. The helper exports that exact
local image, hashes its config bytes, and verifies its platform and ordered
uncompressed layers. It resolves the single Linux amd64 registry manifest,
checks its config against the local export, and records both identities,
the digest-qualified reference, and remote compressed layer
digests separately from local uncompressed layer identities. Retain the printed
publication evidence, including failures; retrying publication uses another
unique tag and the same build. No static pull credentials or registry policy
changes are performed.

If publication was interrupted after pushing, inspect the retained tag first.
Add `--existing-tag "<retained-tag>"` to the same command to produce a fresh
verification-only record without another push. Never overwrite the failed record.

### ACR deployment through azd and SDK

The ACR SDK and azd paths have both passed live model smokes against the same
published image. The verified azd combination is core `1.37.1`, agent extension
`1.0.0-beta.22`, and project extension `1.0.0-beta.15`; the template declares
these minimum versions. Updating just the two extensions does not require
updating the core CLI or every other Foundry extension.

The initializer's generated-template copy can fail with an empty git pathspec,
even after updating extensions. This wrapper does not use it: it renders the
repository template and invokes the supported **local existing-project binding**
command, `azd ai project add --project-id ...`. Setting endpoint variables alone
is insufficient for service dependency resolution. The binding selects the
Foundry infrastructure provider and records existing-project metadata; it does
not provision resources. The helper checks the resulting configuration before
deployment and rejects extra model/resource declarations.

Export the selected project/model settings as in the ZIP baseline section.
Select the successful ZIP, local smoke, and publication records. Use the
publication's exact `image_reference`, not its mutable tag:

```bash
ZIP_EVIDENCE=".artifacts/<zip-run>/deployment.json"
LOCAL_EVIDENCE=".artifacts/<local-run>/local-smoke.json"
PUBLICATION_EVIDENCE=".artifacts/<publication-run>/publication.json"
IMAGE="$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["image_reference"])' "$PUBLICATION_EVIDENCE")"

ACR_AZD_AGENT="registry-acr-azd-$(date -u +%Y%m%d%H%M%S)"
AZURE_DEV_USER_AGENT=microsoft_foundry_skill bash scripts/deploy_azd.sh \
  --method acr --name "$ACR_AZD_AGENT" --image "$IMAGE" \
  --zip-evidence "$ZIP_EVIDENCE" --local-evidence "$LOCAL_EVIDENCE" \
  --publication-evidence "$PUBLICATION_EVIDENCE" --timeout 600 --approve-cloud

ACR_SDK_AGENT="registry-acr-sdk-$(date -u +%Y%m%d%H%M%S)"
python scripts/deploy.py --method acr --name "$ACR_SDK_AGENT" --image "$IMAGE" \
  --zip-evidence "$ZIP_EVIDENCE" --local-evidence "$LOCAL_EVIDENCE" \
  --publication-evidence "$PUBLICATION_EVIDENCE" --timeout 600 --approve-cloud
```

Both entry points enforce the predecessor and publication gates before creating
a version, use CPU `0.5`/memory `1Gi`, Responses `2.0.0`, and the same model
settings. They verify the returned container definition, poll the exact created
version, explicitly bind its endpoint to that version, and send the common smoke
once. SDK creation uses `ContainerConfiguration` without `CodeConfiguration` or
static pull credentials.

The azd wrapper renders `deploy/acr/azure.yaml` into a fresh ignored
`.artifacts/<run-id>/azd/` workspace, with the service key equal to the selected
agent name. It initializes only local azd environment state, links the existing
project through `uses`, verifies an existing AAD/project-identity registry
connection, binds it locally with `azd ai project add --project-id`, and sets
image passthrough with remote build disabled. It never
runs `azd provision`, `up`, `down`, or an image build/push. No Dockerfile or
application source is copied into its workspace. Keep that workspace for
diagnosis; do not copy credentials into it.

Use the
[hosted-agent permissions reference](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agent-permissions)
to check the documented **project managed identity** for ACR pulls. Some private
ACR guidance instead names the agent identity; record actual activation evidence
and this documentation discrepancy rather than granting extra identities broad
roles. Model calls use the hosted agent identity independently of image pull
authorization. Inspect role definitions/scopes for the selected mode:

```bash
az acr show --name "<registry>" \
  --query '{id:id,loginServer:loginServer,mode:roleAssignmentMode,publicNetworkAccess:publicNetworkAccess,networkRuleSet:networkRuleSet}'
az acr config authentication-as-arm show --registry "<registry>"
az role assignment list --scope "<registry-arm-id>" --include-inherited \
  --query '[].{role:roleDefinitionName,scope:scope,principalId:principalId,condition:condition}'
az role definition list --name AcrPull --query '[].permissions'
```

For legacy mode, assign the project `AcrPull` at the selected registry scope,
not Contributor/Owner or publisher credentials. For ABAC mode, use repository
reader with an administrator-reviewed repository condition; the current helper
blocks conditional-role validation until that handoff is implemented. Do not
silently replace it with a broad role. Publication and deployment do not grant
roles, create connections, change firewall rules, or enable public access.

On timeout/failure, retain the evidence and inspect the named agent/version
before doing anything that could create another version. To verify an explicit
retained version without creating a version or changing routing:

```bash
python scripts/deploy.py --method acr --name "<retained-agent>" --version "<version>" \
  --image "$IMAGE" --zip-evidence "$ZIP_EVIDENCE" --local-evidence "$LOCAL_EVIDENCE" \
  --publication-evidence "$PUBLICATION_EVIDENCE" --approve-cloud
```

Resume is still an inference request requiring approval. It validates POC
metadata, the current workload/image, and exclusive endpoint binding; it never
repairs routing or retries a failed generation automatically. Direct-JFrog
deployment additionally requires the ACR evidence described below.

## JFrog administrator handoff and publication

JFrog publication, independent authenticated content download, connection
preflight, and both deployment entry points are implemented. The published
image has been live verified against ACR, and one isolated JFrog/azd version
has reached active with its exact image/connection and new-agent endpoint
binding read back. No model request was made for that activation-only run.
JFrog/SDK live activation, both JFrog model smokes, and runtime pull/push
authorization audit acceptance remain incomplete.
Neither a saved OIDC mapping nor a successful publisher login proves that
Foundry can exchange its project identity for pull credentials.

### Administrator-owned trust and permissions

Confirm that the selected JFrog tenant supports inbound OIDC token exchange,
not just SSO. JFrog documents this feature for Enterprise X/Enterprise+;
confirm the actual trial/license entitlement before proceeding. No JFrog CLI
or Copilot JFrog MCP connection is required.

1. With separate operator approval, create/reuse an Entra application as the
   audience. No client secret, API permissions, or Azure role assignment is
   needed for this audience-only application. Record its application/client ID.
2. Read the selected Foundry project's `identity.principalId` and tenant ID.
   The project identity pulls the image; the hosted agent identity calls the
   model. Do not substitute the developer/publisher identity for either.
3. In JFrog **Administration > General Management > Manage Integrations**, add
   an Azure OIDC provider. Use the exact name accepted by the UI; an
   alphanumeric name avoids provider-name validation differences. Configure
   the audience above and tenant-specific provider discovery URL. Match the
   token issuer to the resource's actual token version: default v1 resource
   tokens use `https://sts.windows.net/<tenant-id>/`, with discovery under
   `https://login.microsoftonline.com/<tenant-id>/.well-known/openid-configuration`.
   Do not assume v2 tokens or borrow a developer token as project-identity proof.
   Azure App Id is only needed for custom signing keys, not this default setup.
4. Create an isolated **Local Docker** repository. Read Docker **Set Me Up**
   to establish the actual registry hostname/repository prefix. The
   `/artifactory/api/docker/<repository>` URL is an API endpoint, not the
   Docker image reference.
5. Create a dedicated runtime group with no administrative roles, no Auto Join,
   and no human/anonymous members. Grant **Read only** on the exact POC
   repository, not Any Local/Remote Repository. Do not reuse the broad `readers`
   group or grant Deploy/Cache, Delete/Overwrite, Annotate, or Manage.
6. Create an identity mapping with exact `tid`, `oid` (project principal ID),
   and `aud` claims. Select **Group**, only the dedicated runtime group, no
   username or additional user/admin scope, Artifactory service only, and a
   short expiration such as 15 minutes. A blank username avoids Auto Join
   expansion. Preserve the exact provider name for `body.provider_name`.
7. Retain administrator-confirmed effective pull success and push denial in the
   isolated POC repository, without token bodies. Runtime OIDC exchange and
   Foundry pull evidence remain separate from publisher success. If those
   checks are unavailable, the trust handoff remains incomplete.

The JFrog token-exchange endpoint is `/access/api/v1/oidc/token`. Both it and
the registry must be reachable over approved HTTPS paths from Foundry.
Independent blob verification can follow HTTPS storage redirects, dropping
authorization on a different origin; permit only approved backing-storage
network paths. Do not disable TLS, enable public exceptions, grant broad roles,
or copy the image into ACR as a workaround.

### Explicit Foundry connection setup and preflight

Connection creation is a separate approved operation, not a deployment side
effect. Compare any existing connection first; stop on conflicts rather than
using `--force`. Set the nonsecret values in `.env.example` in your own shell.
After approval, the documented connection shape can be created with:

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd ai connection create "<connection-name>" \
  --project-endpoint "$FOUNDRY_PROJECT_ENDPOINT" \
  --kind custom-keys --auth-type custom-keys --target "$JFROG_REGISTRY_ORIGIN" \
  --custom-key "audience=$JFROG_AUDIENCE" \
  --custom-key "tokenEndpoint=$JFROG_TOKEN_ENDPOINT" \
  --custom-key "body.provider_name=$JFROG_OIDC_PROVIDER_NAME" \
  --metadata "type=registry_connection" --metadata "mode=oauth_token_exchange" \
  --no-prompt
```

Do not dump connection credentials. `scripts/preflight.py --method jfrog`
checks the exact same-project connection ID/name, CustomKeys type, registry
origin/image hostname, audience, provider, exchange endpoint and metadata.
It first checks metadata, then reads only this connection's nonsecret OIDC
configuration into memory using the SDK credential-read endpoint. The pinned
SDK flattens custom keys and lowercases their names; the checker accounts for
that representation but rejects missing, additional, duplicate or different
keys without printing their values. It neither creates nor repairs connections:

```bash
python scripts/preflight.py --method jfrog --name registry-jfrog-preflight \
  --image "$JFROG_IMAGE" --zip-evidence "$ZIP_EVIDENCE" \
  --local-evidence "$LOCAL_EVIDENCE" --check-tools
```

This is a configuration check, not an image-existence, exchange, or inference
test. Use the selected digest-qualified JFrog reference; before publication,
the known ACR manifest digest may identify the intended image for this
metadata-only check.

### Separate short-lived publisher access

Create a separate publisher group, without administrative roles or Auto Join.
Grant it **Read + Deploy/Cache only** on the isolated Docker repository. Do not
add write access to the runtime group or attach publisher credentials to the
Foundry connection.

In **User Management > Access Tokens > Generate Token**, choose Group scope,
only the publisher group, Artifactory service only, no refresh, and at most
one-hour lifetime. Generate the **full JWT access token**, not a reference
token, only when ready to run publication. Do not put the token in chat,
screenshots, shell arguments/history, `.env`, source, or evidence.

Run the helper in your own interactive terminal using the Python 3.13
environment. It prompts with echo disabled; there is no command-line argument
or environment variable containing the token value:

```bash
bash scripts/publish.sh --method jfrog --registry "<registry-host>" \
  --repository "<docker-repository>/foundry-hosted-agent-registry-poc" \
  --publisher-group "<separate-publisher-group>" \
  --zip-evidence "$ZIP_EVIDENCE" --local-evidence "$LOCAL_EVIDENCE" \
  --acr-publication-evidence "$PUBLICATION_EVIDENCE" --approve-cloud
```

If hidden terminal pasting does not work, add
`--publisher-token-file "/absolute/path/to/temporary-token"` to that command.
Create the file outside the repository and `.artifacts`, owned by your user
with permissions `0600` (for example, using `mktemp` under `/tmp`). Paste only
the full token into that file using a local editor, not an assignment such as
`TOKEN=...`. The helper rejects relative paths, symlinks, non-regular files,
other owners, group/other access and oversized files. It does not echo the
contents, and the same expiry/group-scope checks still apply. The file remains
yours: remove that exact file after the command finishes, including on failure.
Do not use the repository's `.env`, commit the file, or send its contents here.

Before prompting, the helper enforces current ZIP/local gates, validates the
successful ACR publication against this build, checks the existing Foundry
connection, and verifies the local config/platform/layers. It locally rejects
expired, over-one-hour, user/admin-scoped or wrong-group tokens. Local JWT
decoding is a handling constraint, not signature verification; the registry
authenticates and authorizes the credential.

Docker login receives the token only through standard input. Its isolated
temporary credential directory is outside the repository/artifacts, restricted
to the current user, and removed on success or failure. Docker credential files
are not encryption; cleanup and short expiration are required. No global
Docker login/cache configuration is changed.

The helper tags/pushes the existing immutable local image, without rebuilding,
importing or relaying through ACR. It compares the selected Linux amd64 config
and ordered compressed layers with ACR, recording equal manifest digests or an
explicit representation-only difference. It then independently authenticates
to JFrog with pull-only registry scope and downloads/hashes the manifest,
config, and every compressed layer through HTTPS, outside Docker's cache.
This additional pull uses the publisher's read permission; it is **not**
proof of the runtime project's OIDC mapping or denied push.

Retain the unique publication evidence, including partial failures. A failed
pull cannot produce passing publication evidence. If pushing already finished,
add `--existing-tag "<retained-tag>"` to verify that tag without another push;
the content and independent-pull checks still run. The helper does not create
agents, perform model calls, create trust/roles, or change network policy.

### Direct-JFrog deployment

Use the digest-qualified `image_reference` from the successful JFrog publication
record, not its temporary tag or the Artifactory API URL. Set the approved
nonsecret project, model, connection and JFrog settings from `.env.example`.
No publisher token or local Docker daemon is needed for hosted deployment.

Both entry points require the matching ZIP/local smoke, JFrog and ACR
publications, and successful ACR SDK and azd exact-version model smokes.
They compare the JFrog config and ordered compressed layers with ACR and
require the independent publisher-authenticated download to have passed.
They also recheck the same-project OIDC connection before creation. Passing
those checks does not prove that the runtime identity can pull.

After explicit approval for deployment, new-agent endpoint binding and one
model smoke per command:

```bash
JFROG_AZD_AGENT="registry-jfrog-azd-$(date -u +%Y%m%d%H%M%S)"
JFROG_SDK_AGENT="registry-jfrog-sdk-$(date -u +%Y%m%d%H%M%S)"
AZURE_DEV_USER_AGENT=microsoft_foundry_skill bash scripts/deploy_azd.sh \
  --method jfrog --name "$JFROG_AZD_AGENT" --image "$JFROG_IMAGE" \
  --zip-evidence "$ZIP_EVIDENCE" --local-evidence "$LOCAL_EVIDENCE" \
  --publication-evidence "$JFROG_PUBLICATION_EVIDENCE" \
  --acr-publication-evidence "$PUBLICATION_EVIDENCE" \
  --acr-sdk-evidence "$ACR_SDK_EVIDENCE" --acr-azd-evidence "$ACR_AZD_EVIDENCE" \
  --approve-cloud
python scripts/deploy.py --method jfrog --name "$JFROG_SDK_AGENT" --image "$JFROG_IMAGE" \
  --zip-evidence "$ZIP_EVIDENCE" --local-evidence "$LOCAL_EVIDENCE" \
  --publication-evidence "$JFROG_PUBLICATION_EVIDENCE" \
  --acr-publication-evidence "$PUBLICATION_EVIDENCE" \
  --acr-sdk-evidence "$ACR_SDK_EVIDENCE" --acr-azd-evidence "$ACR_AZD_EVIDENCE" \
  --approve-cloud
```

azd uses `deploy/jfrog/azure.yaml` in an isolated generated workspace. Its
agent service has `registryConnectionId` beside `image`, never in `uses`.
The SDK places `registry_connection_id` inside `ContainerConfiguration`.
Both reference the JFrog image directly, with no build, push, ACR lookup,
import or credential fallback. Creating the version triggers Foundry's image
acquisition; Foundry, not the application, exchanges the project identity
token and obtains short-lived read-only registry credentials.

On failure, retain the exact version and evidence. A failed azd command also
retains its workspace and attempts to discover any already-created version;
do not rerun creation blindly. SDK verification resume uses `--version` with
the same image and all six evidence arguments above; it does not recreate
the version or repair routing, and its smoke still requires inference approval.

For `registry_preflight`, check project/connection selection and the exact
target, audience, provider and endpoint without dumping credential values.
For image acquisition/activation failures, have the administrator inspect
sanitized OIDC audit events for issuer, audience and project `oid` match,
mapping selection, token lifetime and repository read permission. Check
approved DNS/HTTPS access from Foundry to both the registry and exchange
endpoint, plus any required blob-storage origins. Do not repair a runtime
failure using publisher credentials, broader permissions or an ACR relay.
For a version that activates but fails smoke, investigate the separate
hosted model identity and model access rather than assuming a registry problem.

Correlate the run/version and UTC times with JFrog token-exchange and registry
pull audit events. Activation alone is not proof of a fresh OIDC exchange
or download: Foundry can cache the already-known image. Explicitly record
unavailable audit evidence and separately obtain runtime push-denial proof;
publisher push/pull success cannot satisfy either runtime acceptance check.

## ZIP baseline

The build downloads the pinned binary wheels from your approved package
source; it does not invoke Azure or require a model identity.

```bash
python scripts/build_zip.py --output .artifacts/zip-baseline/agent.zip
```

The ZIP contains `main.py`, `requirements.txt`, and extracted Linux x86_64
Python 3.13 dependencies under `packages/`. The builder verifies integrity,
current source/lock identity, the 250 MiB limit, safe paths and excluded local
state, then writes `agent.zip.sha256`. Existing ZIPs and digest files are never
overwritten: choose a new output directory for another build.

Before deploying, complete the operator checklist, authenticate with the
approved deployment identity, and export the selected project's nonsecret
settings. Copy the exact ARM ID from your project; do not infer permissions
from being able to sign in.

```bash
export FOUNDRY_PROJECT_ENDPOINT="https://<account>.services.ai.azure.com/api/projects/<project>"
export FOUNDRY_PROJECT_ID="/subscriptions/<subscription>/resourceGroups/<group>/providers/Microsoft.CognitiveServices/accounts/<account>/projects/<project>"
export AZURE_AI_MODEL_DEPLOYMENT_NAME="<existing-model-deployment>"
ZIP_AGENT="registry-zip-$(date -u +%Y%m%d%H%M%S)"
python scripts/preflight.py --method zip --name "$ZIP_AGENT" --check-tools
```

The [source deployment API](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent-code#create-the-agent)
creates the initial hosted version through `create_version_from_code`; there
is no separate SDK `agents.create` call. Use a fresh, isolated name. The helper
refuses an existing agent unless its latest version carries this POC's ownership
metadata. It never converts an unrelated prompt/Invocations agent, provisions a
project/model, or silently overwrites another agent's endpoint configuration.
Service availability and creation permissions still require live validation.

After explicit approval for that name/project, version creation, endpoint
routing, and synthetic inference charges:

```bash
python scripts/deploy.py --method zip --name "$ZIP_AGENT" \
  --zip .artifacts/zip-baseline/agent.zip --timeout 600 --approve-cloud
```

The helper revalidates the ZIP before any cloud call, creates a bundled
`python_3_13` Responses 2.0.0 version with CPU `0.5`/memory `1Gi`, and polls that
exact version. After activation it routes the POC endpoint exclusively to that
version and verifies the binding both before and after the single smoke call.
It never treats another version's successful response as this run's result.
`--approve-cloud` is an explicit confirmation, not a bypass for missing RBAC,
networking, model authorization, or platform capacity.

Each invocation writes a unique ignored `.artifacts/<run-id>/deployment.json`;
`--evidence <new-filename>` selects a different destination without allowing
overwrites. Records include stage outcomes, UTC times, tool/runtime versions,
source/dependency/ZIP hashes, shared configuration fingerprint, model deployment,
created version, and allowlisted smoke assertions/correlation. They omit raw
model/error text and credentials. A nonzero exit means blocked or failed, even
if a version was created.

### Inspection and verification recovery

Keep the printed agent/version and evidence after failure or timeout. Inspect
that exact version in the selected project's Foundry agent list. An approved
read-only SDK check can also print only its identity and provisioning state:

```bash
export INSPECT_AGENT="$ZIP_AGENT"
export INSPECT_VERSION="<version-from-evidence>"
python - <<'PY'
import os
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

with DefaultAzureCredential() as credential, AIProjectClient(
    endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=credential,
    allow_preview=True, retry_total=0, connection_timeout=10, read_timeout=30,
) as project:
    agent = project.agents.get_version(
        agent_name=os.environ["INSPECT_AGENT"],
        agent_version=os.environ["INSPECT_VERSION"],
    )
    print({"name": agent.name, "version": agent.version, "status": agent.status})
PY
```

Correct the cause without weakening TLS/network policy. To retry activation
checks and one synthetic smoke against the retained version, keep the same
source, lock files, project/model settings and name:

```bash
python scripts/deploy.py --method zip --name "$INSPECT_AGENT" \
  --version "$INSPECT_VERSION" --timeout 600 --approve-cloud
```

This resume path does **not** upload code, create a version, or change endpoint
routing. It checks POC ownership and the current workload fingerprint, then
requires an already-exclusive route to that version. A missing/mismatched route
is blocked; after resolving it through an explicitly approved operator action,
resume again. Failed provisioning cannot pass smoke. Do not rerun creation
automatically after timeout: a new deployment command may create a new version.
There is no automatic deletion/rollback; retain evidence and confirm POC
ownership before any separate cleanup.

## Development

Activate the virtual environment before running application checks:

```bash
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q agent scripts tests
npx --yes @fission-ai/openspec@1.7.0 validate --all --strict --no-interactive
```

When the relevant files are implemented, start the agent with
`python agent/main.py` and check shell helpers with
`bash -n scripts/publish.sh scripts/deploy_azd.sh`. There is no separate
application formatter/linter configured; follow `.editorconfig`.

Deployment, publication, OIDC administration, and cleanup require explicit
operator approval and exact resource selection. Do not weaken network/TLS
policy to pass a test, and do not delete shared projects or registries.

Repository architecture, engineering constraints, and agent guidance are
documented in [`AGENTS.md`](AGENTS.md).

## Specifications and changes

This project uses OpenSpec for spec-driven development:

- Accepted behavior: `openspec/specs/`
- Proposed changes: `openspec/changes/`
- Project context and artifact rules: `openspec/config.yaml`

Start a substantive change from Copilot Chat with:

```text
/opsx-propose "describe the change"
```

Every implementation pull request should link its GitHub issue and corresponding
OpenSpec change.

## Contributing

Before contributing:

1. Read `AGENTS.md`.
2. Create or select the relevant GitHub issue.
3. Follow the OpenSpec workflow for substantive behavioral changes.
4. Use the pull request template and report validation actually performed.
