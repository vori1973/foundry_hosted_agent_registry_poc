# Design

## Context

See `proposal.md` for motivation and user-confirmed scope. The repository has no implementation or accepted specs; README, AGENTS, and OpenSpec context remain template material. The only existing validation command is the OpenSpec workflow's `npx --yes @fission-ai/openspec@1.7.0 validate --all --strict --no-interactive`.

The supplied external reference has:

- `build_zip.py`: a flat ZIP containing `main.py`, pinned requirements, and Linux x86_64 Python 3.13 wheels under `packages/`; integrity, size, SHA-256, and no-overwrite checks.
- `deploy.py`: Projects SDK 2.8.x `create_version_from_code`, bundled Python 3.13 runtime, managed Azure authentication, and bounded polling.
- `main.py` and tests: an Invocations 2.0.0, model-free APIM MCP diagnostic, **not** a Responses agent.

Only the first two patterns are relevant. Do not copy its APIM settings, subscription-key connection, MCP dependencies, customer configuration, generated artifacts, or runtime. Inspect licensing/attribution before incorporating source; independently implementing the small packaging pattern is sufficient if reuse is not permitted.

The POC document supplies ZIP/ACR/JFrog progression and connection examples but stops in section 27. The user authorized designing the remaining automation from its success criteria and explicitly selected a model-backed natural-language agent with APIM/MCP excluded.

## Goals / Non-Goals

**Goals:** One application and dependency identity, three packaging/source methods, two registry deployment entry points, evidence-backed stage gates, and explicit failure rather than fallback.

**Non-Goals:** A general deployment framework, infrastructure provisioning engine, model evaluation platform, conversational persistence feature, or implementation of the upstream diagnostic API. Non-streaming single-turn requests are the initial acceptance surface; use one-shot requests and do not claim broader session/streaming support without tests.

## Decisions

### 1. Use the supported Responses hosting integration and an existing Foundry model

Implement a small Python agent using Agent Framework's `FoundryChatClient`, `Agent`, and `ResponsesHostServer`. This delegates Responses framing to the documented integration rather than manually returning Responses-shaped JSON. Use Python 3.13 on Linux x86_64 for ZIP and container. Resolve and pin a mutually compatible dependency graph, including the prerelease hosting integration, during implementation.

Runtime configuration consists of `FOUNDRY_PROJECT_ENDPOINT`, `AZURE_AI_MODEL_DEPLOYMENT_NAME`, `AGENT_NAME`, `DEPLOYMENT_SOURCE` (`zip`, `acr`, or `jfrog`), and `PYTHONNOUSERSITE=1`. Shared instructions tell the model to answer natural-language requests and provide the nonsecret deployment labels when asked. No tools, APIM, MCP, or model API keys are needed. Do not let request text override trusted configuration or expose environment contents.

Local development uses an approved Azure developer identity; hosted execution uses the supported hosted workload identity with least-privilege model access. Determine and record the actual model-calling identity separately from registry pull identity. Do not assume the project registry identity also authorizes model calls.

Validate endpoint/model settings before server startup. Listen on `0.0.0.0:8088`, retain the hosting library's readiness endpoint, and close model clients/credentials cleanly. Preserve sanitized failure codes and request correlation. A model error must never become a synthetic success.

Alternatives: preserving Invocations conflicts with the user's Responses requirement; a deterministic echo avoids model access but was explicitly rejected; manually implementing the protocol adds unnecessary compatibility risk.

### 2. Organize a small standalone application, not a dependency on another checkout

Proposed implementation layout:

| Path | Responsibility |
|---|---|
| `agent/main.py`, `agent/requirements.in`, `agent/requirements.txt` | Responses agent and pinned runtime graph |
| `Dockerfile`, `.dockerignore` | Same runtime, minimal build context, no credentials or deployment files |
| `scripts/build_zip.py`, `scripts/deploy.py` | Bundled ZIP construction and SDK ZIP/container version creation |
| `scripts/preflight.py`, `scripts/verify.py` | Input validation, stage gates, bounded polling, Responses smoke, evidence |
| `scripts/publish.sh`, `scripts/deploy_azd.sh` | Image publication and thin azd orchestration |
| `deploy/acr/azure.yaml`, `deploy/jfrog/azure.yaml` | Separate prebuilt-image templates; local run-specific workspaces/state |
| `requirements-dev.txt`, `tests/test_*.py` | Deployment/test dependencies and focused standard-library unittest suites |
| `.env.example`, `README.md`, `AGENTS.md`, `openspec/config.yaml` | Placeholder-only configuration, commands, constraints, architecture, handoffs |

Use ignored `.artifacts/<run-id>/` for ZIPs, sanitized JSON evidence, and generated azd workspaces; ignore `.azure/`, Python caches, and local credential state. Unique UTC timestamp/run identifiers prevent overwritten runs. If a human-readable report is generated, its filename includes `_<timestamp>`; schema-owned OpenSpec filenames remain canonical.

These are proposed paths, not files that already exist. Keep helpers small; share verification/evidence logic between CLI and SDK instead of introducing a plugin framework. External source paths are research references, never runtime inputs.

### 3. Establish a new ZIP baseline and one container build

Package only the agent source, pinned requirements, and extracted Python 3.13 Linux wheels, preserving ZIP integrity, SHA-256, maximum supported size, and refusal to overwrite. The deployment client dependencies stay outside the ZIP. Use SDK `create_version_from_code` with bundled dependencies and the Responses protocol; validate its real serialized request against the pinned SDK.

Build the container from the same source and pinned graph only after the new ZIP version passes. Use local container tooling because the POC explicitly requires local execution before publication. Do not assume a workstation's Azure CLI cache exists inside the container: document an approved short-lived local credential mechanism outside the image and fail if model authentication is unavailable. Never COPY or bake credentials into an image layer.

Run readiness plus the common model-backed smoke locally. Publish this single build to both registries without rebuilding. Capture the source tree content hash (including uncommitted source), dependency hash, shared configuration fingerprint, ZIP SHA-256, platform, image config digest, layer digests, tags, and remote manifest digests.

Require equal remote manifest digests where possible. If registry manifest representation changes, compare selected-platform config and ordered layer digests; record why top-level digests differ. Missing or divergent content blocks JFrog. Prefer digest-qualified deployment references when supported; otherwise use unique protected tags and check resolution before and after deployment. Matching tag text is never sufficient.

Alternatives: rebuilding per registry introduces a confounding variable; treating the original ZIP as baseline validates the wrong protocol; using ACR import for JFrog defeats the direct-registry objective.

### 4. Keep deployment entry points thin and their state isolated

The implementation exposes these documented entry points:

- SDK ZIP baseline through `scripts/deploy.py --method zip`.
- SDK ACR/JFrog through `scripts/deploy.py --method acr|jfrog`.
- azd ACR/JFrog through `scripts/deploy_azd.sh --method acr|jfrog`.
- Publication through `scripts/publish.sh` using the already validated build.

Both registry deployment paths consume equivalent HostedAgentDefinition settings: Responses 2.0.0, initial CPU `0.5`, memory `1Gi`, common model configuration, and immutable image identity. Validate those compute values in the target environment before mutation. SDK uses `ContainerConfiguration` and `registry_connection_id` for JFrog; ZIP uses `CodeConfiguration`, never both.

Each azd template references the explicitly selected existing project, keeps the agent's `uses` relationship to it, and selects image passthrough with remote build disabled. Container templates omit `codeConfiguration`. JFrog uses `registryConnectionId`; an existing registry connection is not a service dependency in `uses`. Generate local run-specific workspaces rather than letting one `azd init` overwrite another method's files.

Use short run-qualified agent names for ZIP and each registry/entry-point pair, within the platform's length limit. A fresh name per run prevents an older active version from satisfying a new run's smoke test. Persist created version and endpoint identity. Verify endpoint binding before and after invocation; use a documented version selector if supported. If exact binding cannot be proven, stop verification rather than infer it from a successful response.

A repeated invocation of the deploy command may create another immutable version; record it honestly. Resume verification using an explicit existing version rather than automatically redeploying after a timeout.

### 5. Treat registry trust as a separate, least-privilege prerequisite

ACR preflight identifies the supported runtime pull identity and registry authorization mode. Use the narrowest applicable pull role/scope, accounting for ABAC-enabled repositories rather than hardcoding one role for all registries. Record publisher and runtime assignments separately.

For JFrog:

1. Confirm tenant support for the documented token-exchange pattern before administrative work.
2. Obtain an Entra application audience without creating a client secret.
3. Identify the hosting project's managed identity.
4. Hand off issuer/audience/identity claims and repository scope to the JFrog administrator; the administrator configures OIDC trust and read/pull-only mapping.
5. Create or explicitly reuse the same-project CustomKeys registry connection with HTTPS target, audience, `/access/api/v1/oidc/token`, `body.provider_name`, and metadata `type=registry_connection`, `mode=oauth_token_exchange`.
6. Validate nonsecret connection metadata and administrator attestation; do not dump credential fields.

Connection creation is a separate operator-approved setup step, not an implicit side effect of deploy. Compare existing configuration and stop on mismatch. Publisher credentials remain in approved external credential tooling and are never reused for runtime pulls. Deny/omit push and administration for the runtime mapping, and retain sanitized proof of denied push in an isolated test repository.

No trust setup runs in this proposal. Networking for project access, model access, image pull, and token exchange is pre-existing and policy-approved. Do not create public exceptions or weaken TLS.

Alternative: static JFrog credentials are simpler but violate the POC's security objective.

### 6. Gate progression using evidence tied to the current workload

Use a local machine-readable evidence record per run/stage. A shared baseline fingerprint covers source, pinned dependencies, model deployment, project, protocol, compute, and common instructions/settings; exclude only documented method-specific names, versions, registry connection/image references, and deployment labels.

Sequence:

`preflight -> ZIP active + smoke -> local container ready + smoke -> ACR active + smoke -> JFrog active + smoke`

JFrog setup can be prepared early, but neither deployment entry point bypasses the matching ACR gate. Exercise the full registry matrix (ACR/azd, ACR/SDK, JFrog/azd, JFrog/SDK). JFrog publication requires the locally validated image; JFrog deployment additionally requires verified cross-registry content equivalence. Treat evidence as a consistency check, not a signed enterprise approval system.

Default polling deadline is 600 seconds with a five-second maximum polling interval and bounded individual request timeouts; expose positive finite timeout overrides. Handle active, creating, failed, deleting, deleted, unknown, and transport/authentication errors explicitly. Any terminal failure exits nonzero and preserves the version for diagnosis.

### 7. Use a model-backed smoke test with semantic invariants

Use synthetic natural-language input asking for a short confirmation, configured name/source, and a fresh random marker. Send it as a one-shot, non-streaming Responses request. Assert completed status, nonempty model output, marker/name/source presence, and recorded request correlation; do not assert identical wording across runs.

Offline tests prove the runtime actually delegates to the model client and rejects failed/incomplete output rather than returning a hardcoded success. Live smoke demonstrates model connectivity for every method/entry point. Do not silently retry generations until one passes; record the original outcome and permit an explicit new smoke attempt.

Store bounded synthetic output only. Evidence includes UTC times, durations, source/artifact identities, tool/dependency versions, registry and connection labels, version/endpoint binding, stage results, assertion outcomes, and safe correlation identifiers. Console logging uses allowlisted fields; never persist raw token-exchange bodies, authorization headers, Docker auth files, or arbitrary model/error payloads.

### 8. Validate offline contracts before authorized live execution

Use `python -m unittest discover -s tests -p 'test_*.py'` for the new suite. Focused modules cover agent/model behavior, ZIP content, definition parity, actual pinned SDK request serialization with mocked transport, azd configuration rendering, content identity, predecessor gates, bounded polling, exact-version binding, smoke assertions, and evidence redaction.

No application formatter/linter exists today. Use the project's EditorConfig and Python compile check; document exact new commands rather than pretending template commands exist. Keep the existing OpenSpec strict CI command. Application CI should initially run offline tests only; the initial live CI/CD design uses separate short-lived publisher/deployer identities, ordered gates, protected environment approval, and sanitized evidence retention, not automatic production deployment.

Live acceptance requires explicit target selection and approval for billable mutations. Run ZIP, local container, then the four registry/entry-point combinations, plus isolated wrong-audience, wrong mapping, missing pull permission, missing connection, missing model permission, unreachable endpoint, missing image, and timeout tests. Never alter shared production trust to induce a negative case.

## Risks / Trade-offs

- [Prerelease Responses hosting integration and evolving SDK/CLI contracts] -> Pin a verified compatible set, exercise offline wire serialization and real Responses hosting before cloud acceptance; do not assume the source sample's Invocations dependencies support Responses.
- [Model-generated output varies or is filtered] -> Compare semantic markers and completed status, preserve failures, and use only synthetic benign inputs.
- [A valid image still cannot access its model] -> Test local and hosted model identity/network access separately from registry pulls.
- [JFrog tenant supports OIDC but not the required exchange] -> Require administrator confirmation and an isolated live deployment before declaring success.
- [Pull succeeds through a cached image] -> Correlate registry/OIDC audit evidence with a fresh run/version and document any caching limitation; activation alone is not proof of a new exchange.
- [Tag or endpoint drift invalidates evidence] -> Verify immutable content and exact endpoint/version binding before and after smoke.
- [Unexpected cloud charges or destructive cleanup] -> Reuse selected resources, require approval for mutations, and keep a POC-owned resource inventory.

## Migration Plan

There is no persisted product data to migrate and no upstream file to modify. After proposal approval, create the local agent, validate offline, establish a new ZIP baseline, then advance through local container, ACR, and JFrog gates.

Use separate POC names so rollout cannot replace an existing agent inadvertently. Recovery is manual: stop progression, retain sanitized failure evidence, inspect the failed version, and select/redeploy a previously verified artifact only after operator confirmation. Remove only confirmed POC-owned versions, images, connections, application registrations, and role assignments; never delete a shared project or registry as cleanup.

Operational telemetry is limited to sanitized stdout/stderr, stage/status timing, smoke outcomes, correlation identifiers, and administrator-supplied audit evidence. Production alerts and rollback automation remain out of scope.

## Open Questions

These are environment inputs, not unresolved product decisions: exact project/model deployment, target region, registry/repository names, compatible pinned package/extension versions, actual pull/model identities, tenant-specific OIDC claims, and operator-approved test resources. Resolve them in the explicit preflight/compatibility tasks. If a required platform feature is unavailable, mark the affected phase blocked and surface the incompatibility rather than redesigning the POC silently.

## References

- [Foundry Responses hosting integration](https://learn.microsoft.com/agent-framework/hosting/foundry-hosted-agent)
- [Hosted-agent deployment](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent)
- [Direct external-registry deployment and JFrog OIDC](https://learn.microsoft.com/azure/foundry/agents/how-to/private-registry-connections)

Documentation was reviewed during planning; none of these references establishes that a live deployment has been tested in the selected environment.
