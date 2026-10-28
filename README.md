# Hosted Agent Deployment Options: POC / Lab

## Overview

Compare the same model-backed Microsoft Foundry Hosted Agent deployed from a
source ZIP, Azure Container Registry, and directly from JFrog Artifactory.
The agent interprets natural-language requests through Responses 2.0.0.
APIM and MCP are not part of this POC.

Implementation is tracked by [#1](https://github.com/vori1973/foundry_hosted_agent_registry_poc/issues/1)
and [the OpenSpec change](openspec/changes/hosted-agent-three-method-deployment/).
This repository is being implemented in stages; a plan or successful offline
test is not evidence that a cloud deployment has succeeded.

## Start the lab

This repository contains the runtime, pinned dependencies, packaging and
deployment helpers, azd configurations and operational guides. It does not
provision a Foundry estate: bring an explicitly selected existing project,
Responses-capable model, ACR and compatible JFrog tenant. Use Python 3.13,
Bash, Azure CLI 2.80+, Docker with BuildKit and, for the azd path, Azure
Developer CLI 1.32+ with compatible Foundry extensions. Azure deployment,
model access, JFrog administration and network paths require owner approval.

**Start with the [step-by-step lab](docs/lab.md).** It covers environment
setup and executes ZIP, local container, ACR and direct JFrog in that order.
All example commands run from the repository root. Billable mutations and
inference require explicit target selection and approval; never commit
credentials or weaken TLS/network policy to complete a stage.

## Documentation

| Guide | Contents |
|---|---|
| [Lab walkthrough](docs/lab.md) | Setup, preflight, local agent, ZIP baseline, container smoke, ACR and JFrog publication/deployment through CLI and SDK |
| [Identity and OIDC](docs/identity-and-oidc.md) | Project pull identity versus model/publisher identities, value origins, JFrog trust, repository permissions and Foundry connection |
| [Operations](docs/operations.md) | Evidence, failure recovery, updates, rollout/rollback design and cleanup limitations |
| [Development](docs/development.md) | Tests, dependency locks, architecture guidance and contribution/OpenSpec workflow |

## Architecture and progression

`agent/` contains the standalone runtime. `scripts/` contains packaging and
operational helpers. `deploy/` contains separate azd registry configurations.
No component depends on the external Echo MCP reference checkout.

### Deployment method comparison

| Aspect | ZIP | ACR | JFrog |
| --- | --- | --- | --- |
| Deployment input | Source ZIP with bundled pinned Python dependencies | Verified prebuilt container image | The same verified prebuilt container image |
| Immutable artifact identity | ZIP SHA-256 | Registry image digest | Registry image digest; config/layers compared with ACR for this POC |
| Artifact delivery | Deployer uploads the ZIP to Foundry | Foundry acquires the image from ACR | Foundry acquires the image directly from JFrog; no ACR relay |
| Runtime registry authentication | No customer registry pull credentials required | Azure-native Entra/managed identity | Project managed identity token exchanged for short-lived JFrog credentials |
| Registry pull authorization | Not applicable to the uploaded ZIP | Azure RBAC/ABAC appropriate to the registry mode | JFrog OIDC identity mapping, group and repository read-only permissions |
| Registry connection | No registry connection for this path | azd helper checks an existing secretless AAD ACR connection | Explicit same-project OAuth token-exchange connection on the agent container configuration |
| Repository deployment entry points | `scripts/deploy.py --method zip` | `scripts/deploy.py --method acr` or `scripts/deploy_azd.sh --method acr` | `scripts/deploy.py --method jfrog` or `scripts/deploy_azd.sh --method jfrog` |
| Update an existing agent | Create a new version under the existing agent name using the new ZIP | Create a new version under the existing agent name using the new image digest | Create a new version under the existing agent name using the new image digest and registry connection |

All three run the same model-backed Responses workload and use a separate
approved runtime identity for model access. None updates a deployed version
in place or automatically adopts a newly published artifact. An operator or
CI/CD system must deploy a new version and explicitly control which version
the stable endpoint serves; pin production routing rather than relying on
Foundry's default "Always use latest" policy.

The update row describes Foundry's versioning model, not an unrestricted
existing-agent capability in every helper: the SDK helper checks POC ownership,
while the azd comparison helper requires a fresh agent name. See
[updating an existing agent](docs/operations.md#updating-an-existing-agent-from-an-approved-jfrog-artifact)
for executable commands, routing cautions and CI/CD-neutral rollout guidance.

### POC validation sequence

The required progression is:

```text
New ZIP active + Responses smoke
  -> Same-source local container + model smoke
  -> ACR active + Responses smoke
  -> Identical image directly from JFrog + Responses smoke
```

Both ACR and JFrog must be exercised through azd and the Python SDK.
ACR is the control test: it establishes image startup, Foundry hosting and model
access before adding external-registry trust. Once it passes, JFrog-specific
failures can be investigated separately from those shared dependencies.
This ordering is a POC comparison gate, not a Foundry requirement: a customer
can deploy directly from JFrog without first deploying from ACR.
JFrog runtime pulls use project managed identity/OIDC and a same-project
registry connection, not publisher credentials or an ACR relay.
Generated local artifacts and sanitized run evidence belong under ignored
`.artifacts/<run-id>/`. Never put tokens, credential files, customer content,
or raw token-exchange responses there.

## Current verification limits

ZIP and local-container model smokes and both ACR deployment paths have
been live verified. These results do not prove the remaining JFrog acceptance.

JFrog publication, independent authenticated content download, connection
preflight, and both deployment entry points are implemented. The published
image has been live verified against ACR. The retained azd-created JFrog
version and a fresh SDK-created JFrog version have both passed exact-version
Responses model smokes. The azd-created version was verified by SDK resume,
without rerunning azd deployment or changing its routing.
Runtime OIDC/pull audit corroboration, runtime push denial, the full isolated
negative/repeatability matrix and overall operational acceptance remain incomplete.
Neither a saved OIDC mapping nor a successful publisher login proves that
Foundry can exchange its project identity for pull credentials. Successful
activation/smoke alone does not establish a fresh exchange or download if
the image was cached.

The [OpenSpec tasks](openspec/changes/hosted-agent-three-method-deployment/tasks.md)
track remaining live checks and operational acceptance. The lab is a POC,
not a production deployment or automatic cleanup/rollback system.

## Contributing

Read [AGENTS.md](AGENTS.md) and the [development guide](docs/development.md).
Link behavioral changes to their GitHub issue and approved OpenSpec change.
