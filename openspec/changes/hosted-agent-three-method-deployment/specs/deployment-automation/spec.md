# Spec Delta

## Purpose

Make registry publication and hosted-agent deployment repeatable through CLI and SDK entry points, with reliable completion signals, isolated state, and auditable nonsecret evidence.

## ADDED Requirements

### Requirement: CLI and SDK registry deployment parity
The automation SHALL expose Azure Developer CLI and Python SDK deployment paths for ACR and JFrog. Both paths MUST consume the same verified prebuilt image content and equivalent project, protocol, compute, model, and runtime configuration.

#### Scenario: Both entry points deploy both registries
- **WHEN** an operator selects each combination of azd/SDK and ACR/JFrog with valid prerequisites and baseline evidence
- **THEN** each creates and verifies a hosted Responses version using the selected registry image
- **AND** JFrog uses its registry connection without an implicit ACR build or publication

#### Scenario: Configuration is incomplete
- **WHEN** required project, model, image, connection, timeout, or prerequisite evidence is absent or invalid
- **THEN** the command exits nonzero before mutating deployment resources and identifies the invalid input

### Requirement: Bounded exact-version verification
Deployment commands SHALL poll the created version with a positive finite deadline, stop on terminal failure, and invoke only after activation. Success MUST require a passing smoke test against that version, not an unrelated active endpoint.

#### Scenario: Version becomes active
- **WHEN** polling observes active before the deadline
- **THEN** the command invokes the verified version and exits zero only after smoke assertions pass

#### Scenario: Version fails or is deleted
- **WHEN** polling observes a failed, deleting, deleted, or unrecognized state
- **THEN** the command exits nonzero with the version identity and a sanitized diagnostic

#### Scenario: Provisioning exceeds the deadline
- **WHEN** the finite deadline expires before activation
- **THEN** polling stops, the command exits nonzero, and the version is retained for inspection
- **AND** the command does not create another version automatically

#### Scenario: Endpoint targets another version
- **WHEN** the invocation endpoint cannot be bound to or verified against the newly created version
- **THEN** the command reports verification as blocked instead of attributing another version's response to the new deployment

### Requirement: Repeatable isolated execution
The automation SHALL isolate method-specific names and azd state and preserve each run's artifact identities. Repeated deployment MUST reuse the selected immutable build, record each resulting version, and avoid silently replacing mismatched shared resources.

#### Scenario: Registry deployment is repeated
- **WHEN** an operator reruns a registry deployment using the verified published build
- **THEN** no container rebuild or duplicate shared-resource creation is required
- **AND** the resulting version identity is recorded even if the platform creates a new immutable version

#### Scenario: Existing configuration conflicts
- **WHEN** an existing connection or deployment configuration differs from the requested target
- **THEN** the workflow stops for explicit correction rather than silently overwriting it

### Requirement: Sanitized evidence and truthful outcomes
Every run SHALL produce a unique, machine-readable evidence record with stage outcomes, timestamps, artifact identities, tool versions, agent/version, registry source, status, smoke assertions, and correlation identifiers. Evidence MUST omit secrets, tokens, raw credential responses, and sensitive response content.

#### Scenario: Evidence records a successful deployment
- **WHEN** activation and smoke verification succeed
- **THEN** evidence identifies the exact method, entry point, source/build identity, version, elapsed time, and passed assertions
- **AND** it stores only bounded smoke output generated from synthetic test input

#### Scenario: A stage is blocked or fails
- **WHEN** prerequisites, publication, activation, or invocation fail
- **THEN** evidence identifies the failing stage and sanitized reason
- **AND** subsequent unexecuted stages are not marked passed

#### Scenario: Sensitive error content is returned
- **WHEN** a CLI, SDK, model, or registry error contains credentials or token data
- **THEN** console output and evidence redact that content while preserving safe error codes and correlation identifiers

### Requirement: Operational handoffs and cleanup
The runbook SHALL document executable prerequisites, publication/deployment commands, administrator-owned OIDC setup, identity separation, negative tests, manual recovery/cleanup, and an initial CI/CD design. Cleanup MUST be explicit and limited to operator-confirmed POC-owned resources.

#### Scenario: Administrator handoff is needed
- **WHEN** JFrog trust or permissions are not configured
- **THEN** the runbook identifies required audience, issuer/identity mapping, provider, repository, pull-only permissions, and token endpoint
- **AND** automation does not silently administer the JFrog tenant

#### Scenario: Operator cleans up a failed run
- **WHEN** an operator follows cleanup instructions
- **THEN** the exact POC resources and versions are listed for confirmation
- **AND** unrelated existing projects, registries, applications, and role assignments are preserved
