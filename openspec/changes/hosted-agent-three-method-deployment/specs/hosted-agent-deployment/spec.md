# Spec Delta

## Purpose

Provide controlled deployment of one hosted Responses agent from ZIP, ACR, and JFrog while separating application validation, image publication, and runtime pull authorization.

## ADDED Requirements

### Requirement: New ZIP baseline
The deployment workflow SHALL package the new model-backed Responses agent as a ZIP and deploy it to an explicitly selected existing Foundry project. The upstream Invocations-only sample MUST NOT count as this baseline.

#### Scenario: ZIP baseline succeeds
- **WHEN** a ZIP from the shared agent source is deployed
- **THEN** its exact version reaches active and passes the common Responses smoke test
- **AND** evidence records source identity, ZIP SHA-256, runtime, dependency identity, agent name, and version

#### Scenario: ZIP packaging excludes local state
- **WHEN** a ZIP is built
- **THEN** only required source, dependency declarations, and bundled runtime dependencies are included
- **AND** credentials, local environment files, deployment state, caches, and tests are excluded

### Requirement: Ordered baseline gates
The workflow SHALL require a successful new ZIP baseline and local container smoke test before the ACR baseline. It MUST require ACR activation and functional smoke success before direct JFrog deployment.

#### Scenario: Missing predecessor blocks progression
- **WHEN** a registry deployment is requested without matching successful predecessor evidence for the current source, dependencies, and shared runtime settings
- **THEN** the workflow stops before creating that agent version and identifies the unmet gate

#### Scenario: Shared workload changes invalidate baseline
- **WHEN** agent source, dependencies, model deployment, or shared runtime configuration changes
- **THEN** earlier comparison evidence cannot authorize later stages until the affected baseline tests pass again

### Requirement: Identical registry image content
The publication workflow SHALL build one reusable container and publish that content to ACR and JFrog without rebuilding between registries. It MUST retain immutable image identities and verify content equivalence rather than treating matching tags as proof.

#### Scenario: One build is published twice
- **WHEN** the locally validated image is tagged and pushed to both registries
- **THEN** publication evidence identifies both image references and resolved digests and verifies matching image content
- **AND** an independent authenticated JFrog pull succeeds

#### Scenario: Content cannot be verified
- **WHEN** registry content differs or equivalence cannot be established
- **THEN** direct JFrog deployment is blocked with an artifact-identity diagnostic

### Requirement: ACR runtime pull authorization
The ACR deployment SHALL use the supported Foundry runtime pull identity with least-privilege pull access for the selected registry authorization mode. Publisher access MUST NOT be accepted as proof of runtime pull access.

#### Scenario: ACR baseline succeeds
- **WHEN** the published ACR image is deployed with valid runtime authorization
- **THEN** the exact version reaches active and passes the common Responses smoke test
- **AND** evidence distinguishes the publisher from the runtime identity and records role and assignment scope

#### Scenario: Publisher can push but runtime cannot pull
- **WHEN** publisher access is valid but Foundry lacks image-pull authorization
- **THEN** deployment fails with a pull-authorization diagnostic and the JFrog gate remains closed

### Requirement: Direct JFrog token-exchange deployment
The JFrog deployment SHALL reference the JFrog image directly and use a registry connection in the hosting Foundry project. Pull authentication MUST exchange the project managed identity token for short-lived credentials using the configured audience, provider, and token endpoint; no static registry pull secret or ACR relay is permitted.

#### Scenario: Direct JFrog deployment succeeds
- **WHEN** the ACR gate and content checks pass and a compatible JFrog OIDC mapping grants repository pull access
- **THEN** Foundry deploys the JFrog image, the version reaches active, and the same Responses smoke test passes
- **AND** deployment performs no image rebuild, ACR import, or image push to ACR

#### Scenario: Audience or identity mapping is wrong
- **WHEN** JFrog rejects the audience, issuer, provider, or mapped project identity
- **THEN** deployment fails without falling back to publisher credentials or ACR

#### Scenario: Registry connection is invalid
- **WHEN** the connection is missing, belongs to another project, targets another registry, or lacks token-exchange metadata
- **THEN** preflight stops before creating the agent version and identifies the mismatch

### Requirement: Separate publisher and runtime permissions
JFrog publication SHALL use a separate authorized publisher identity. The runtime identity MUST be limited to read/pull access to the POC repository and MUST NOT have push or administration permissions.

#### Scenario: Pull-only mapping is verified
- **WHEN** the administrator validates the runtime mapping in an isolated POC repository
- **THEN** pull is allowed and push is denied
- **AND** sanitized evidence records the permission scope without tokens or credentials

### Requirement: Unsupported environments fail closed
The workflow SHALL require supported Foundry hosting, usable model access, compatible JFrog token exchange, and approved connectivity to the project, model, registries, and token service. It MUST NOT weaken network or TLS policy to make a deployment succeed.

#### Scenario: JFrog lacks required capabilities
- **WHEN** the selected tenant lacks compatible OIDC exchange or identity mapping
- **THEN** the JFrog stage is reported as blocked, not successful
- **AND** completed ZIP/ACR evidence remains distinguishable from the unproven JFrog objective

#### Scenario: Network access is unavailable
- **WHEN** required DNS, routing, HTTPS, or certificate trust is unavailable
- **THEN** the workflow stops with a sanitized network prerequisite failure rather than disabling TLS or enabling public access
