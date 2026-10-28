# Spec Delta

## Purpose

Define a single model-backed Responses agent whose functional behavior can be compared across ZIP, ACR, and direct JFrog deployments without APIM or MCP dependencies.

## ADDED Requirements

### Requirement: Natural-language Responses execution
The agent SHALL accept natural-language input through Responses 2.0.0, execute a request against its configured Foundry model deployment, and return model-generated output. It MUST NOT require APIM or MCP.

#### Scenario: Model-backed request succeeds
- **WHEN** a caller submits a supported non-streaming Responses request with a natural-language instruction
- **THEN** the agent calls the configured model and returns a completed Responses result containing the generated answer
- **AND** no APIM endpoint, MCP connection, or subscription key is required

#### Scenario: Model call fails
- **WHEN** model access is denied, the model request times out, or the upstream service fails
- **THEN** the request fails with a sanitized diagnostic and correlation identifier
- **AND** no static confirmation is returned as a successful model response

#### Scenario: Request is invalid
- **WHEN** a request contains malformed JSON or unsupported input
- **THEN** it receives a client-visible validation error without invoking the model

### Requirement: Portable runtime configuration
The agent SHALL use the same source, instructions, dependencies, and model deployment for all three deployment methods. It MUST obtain project/model settings and nonsecret deployment labels from configuration and authenticate to the model through an approved Azure identity.

#### Scenario: Deployments share behavior
- **WHEN** ZIP, ACR, and JFrog versions are configured for comparison
- **THEN** their model deployment and application settings match apart from method-specific names, versions, registry references, and deployment labels
- **AND** no Azure API key or registry credential is embedded in the workload

#### Scenario: Required configuration is absent
- **WHEN** the server starts without its required project endpoint or model deployment name
- **THEN** startup exits nonzero and reports the missing setting without printing secrets

### Requirement: Functional comparison smoke test
The common smoke test SHALL validate completed model execution, not just readiness or activation. It MUST use the same prompt structure and assertions for ZIP, ACR, and JFrog, with a unique per-request marker and nonsecret deployment labels.

#### Scenario: Functional response passes
- **WHEN** the smoke request asks the model to include a unique marker, give a short deployment confirmation, and identify the configured agent and deployment source
- **THEN** a completed, nonempty answer containing the expected marker and labels passes
- **AND** the smoke result records response status and a correlation or request identifier

#### Scenario: Activation alone is insufficient
- **WHEN** the agent is active but the response is empty, failed, incomplete, refused, or missing an expected marker or label
- **THEN** the smoke test fails and does not qualify the deployment as a successful baseline

### Requirement: Safe local container execution
The shared container SHALL start noninteractively, listen on the hosted runtime interface and port, expose Responses and readiness endpoints, and emit sanitized startup/request diagnostics to standard output or standard error.

#### Scenario: Container runs outside Foundry
- **WHEN** the container is started locally with valid configuration and an approved model-access identity
- **THEN** readiness and the common Responses smoke test succeed without Foundry-specific manual interaction

#### Scenario: Startup fails
- **WHEN** the configured entry point or required runtime dependencies are unusable
- **THEN** the container terminates nonzero and logs a sanitized actionable startup failure
