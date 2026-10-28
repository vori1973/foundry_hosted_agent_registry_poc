# Proposal

## Why

The POC needs reproducible evidence that one functional Microsoft Foundry Hosted Agent can run from a source ZIP, ACR, and directly from JFrog without copying the JFrog image into ACR. A gated ZIP-to-ACR-to-JFrog progression separates application/runtime failures from registry identity and image-pull failures.

## What Changes

- Create a repository-local, model-backed Responses 2.0.0 agent that interprets natural-language requests using a configured Foundry model deployment, without APIM or MCP dependencies.
- Reuse applicable ZIP packaging/deployment patterns from the supplied `agentic-ai-enterprise-blueprint/samples/hosted-echo-mcp` reference, not its diagnostic runtime. Establish a **new ZIP baseline**; its original Invocations-only deployment is not Responses acceptance evidence.
- Build and locally validate one container, publish the same image content to ACR and JFrog, and require successful ACR activation and functional smoke testing before JFrog deployment.
- Support Azure Developer CLI and Python SDK deployment of both prebuilt registry images, bounded status polling, a common Responses smoke test, negative tests, and sanitized evidence.
- Configure JFrog pull access using the Foundry project managed identity, an Entra application audience, an administrator-managed OIDC mapping, and a same-project registry connection. Separate publisher credentials from pull-only runtime identity.
- Document prerequisites, exact commands, compatibility checks, operator handoffs, cleanup, and an initial CI/CD design.

Scope clarification: after inspecting the supplied model-free Invocations sample, the user explicitly excluded APIM/MCP from this POC and requested a model-backed Responses agent that interprets natural-language requests. All three methods use that new agent and the same model deployment. The sample is a packaging/deployment reference only.

Non-goals: changing the upstream sample, retaining its Invocations API, APIM/MCP integration, unrelated tools, provisioning networking or a new Foundry estate/model deployment, automated JFrog administration, enterprise approvals/scanning integrations, production monitoring, multi-region support, production rollback automation, or a full enterprise pipeline.

## Capabilities

### New Capabilities

- `responses-agent`: Shared model-backed Responses workload, runtime configuration, and functional smoke-test contract.
- `hosted-agent-deployment`: Ordered ZIP, ACR, and direct-JFrog deployment, artifact identity, and registry authentication.
- `deployment-automation`: CLI/SDK orchestration, bounded verification, repeatability, diagnostics, and evidence.

### Modified Capabilities

None. The accepted specification inventory is empty.

## Impact

- Repository baseline: only template guidance and the untracked `Foundry_Hosted_Agent_Registry_POC.md` exist; no local agent, build, application tests, or accepted specifications exist. The supplied document ends mid-sentence in section 27. Remaining automation details are proposed from its stated scope and success criteria, as authorized by the user.
- Related GitHub issue: [#1](https://github.com/vori1973/foundry_hosted_agent_registry_poc/issues/1), created when implementation began to track the approved model-backed scope and explicit APIM/MCP exclusion. No open pull request existed at implementation start.
- Proposed additions: local Python agent and packaging, Dockerfile, isolated azd deployment configurations, Python/Bash operational helpers, dependency manifests, focused tests, and operator documentation. Customize the existing template README, AGENTS, and OpenSpec context during implementation.
- Compatibility: Python 3.13/Linux x86_64 preserves the supplied ZIP baseline's runtime target; validate and pin a Responses-capable hosting library and deployment SDK. The upstream Invocations API remains untouched; new agents use distinct names and Responses contracts.
- Security: model access uses an approved Azure identity, registry pull uses managed identity/OIDC, and secrets never enter source, ZIPs, images, logs, or evidence. Approved client, model, and registry network access are prerequisites, not bypassed by the POC.
- Operations: deployment creates billable versions and publishes images. Reuse explicitly selected projects/registries, preserve failed versions for inspection, and require deliberate cleanup of POC-owned resources. No data migration is required.
- Platform-dependent gates: verify actual Foundry region/runtime support, CLI extensions, SDK serialization, pull identity/RBAC mode, JFrog OIDC capabilities and claims, registry/token reachability, and version-targeted invocation. Documentation establishes a supported pattern, not proof for the user's environment.

Implementation remains gated on proposal review and a separate apply request. No cloud deployment is authorized by this planning change.
