# Tasks

Planning is complete; all boxes below track future implementation or operational acceptance. Apply requires reviewed proposal approval and a separate user request. Cloud/resource changes additionally require explicit target selection and approval.

## 1. Establish project and compatibility prerequisites

- [x] 1.1 Identify or create the repository tracking issue and record the approved change scope; verify it links this change and explicitly excludes APIM/MCP.
- [x] 1.2 Replace template project context in `AGENTS.md`, `README.md`, and `openspec/config.yaml` with the approved purpose, architecture, Python 3.13 target, commands, security constraints, and review boundaries; verify no template placeholders remain in those relevant sections.
- [x] 1.3 Add runtime/development manifests and resolve compatible pinned Responses hosting, Foundry model client, Projects SDK, and Identity dependencies; verify clean-environment installation and imports on Python 3.13, and document exact versions.
- [x] 1.4 Implement `scripts/preflight.py` for explicit project/model, tool versions, finite timeouts, supported compute/runtime, and method-specific inputs; verify invalid or missing configuration fails before mutation using `tests/test_preflight.py`.
- [x] 1.5 Add placeholder-only `.env.example` and ignore rules for local environments, `.azure/`, `.artifacts/`, caches, and credentials; verify representative local state is ignored and the example is tracked.
- [x] 1.6 Document the operator preflight checklist for existing project/model access, actual model identity, ACR mode/pull identity, JFrog feature availability, and approved networking; verify each unresolved environment input has a concrete check and no networking bypass.

## 2. Implement the shared model-backed Responses agent

- [x] 2.1 Implement `agent/main.py` using the pinned Responses host and Foundry model client with natural-language instructions and nonsecret name/source labels; verify `tests/test_agent.py` proves a model call supplies the successful response and no APIM/MCP setting is required.
- [x] 2.2 Add startup configuration validation, Azure identity authentication, safe lifecycle handling, and sanitized failures; verify missing settings, malformed requests, model denial/timeouts, and upstream errors cannot yield synthetic success.
- [x] 2.3 Implement the common one-shot smoke request/assertions in `scripts/verify.py`; verify completed/nonempty output, marker/name/source checks, refusal/incomplete failure, and safe correlation capture with `tests/test_smoke.py`.
- [x] 2.4 Document local agent launch, approved model authentication, Responses request shape, and the synthetic smoke prompt in README; verify the documented local request against a stub model and record the separate live prerequisites.

## 3. Package and establish the new ZIP baseline

- [x] 3.1 Implement `scripts/build_zip.py` for the shared source and pinned bundled Linux x86_64 Python 3.13 wheels; verify ZIP integrity, SHA-256, size limit, flat layout, dependency inclusion, forbidden-state exclusion, and no-overwrite behavior in `tests/test_packaging.py`.
- [x] 3.2 Implement SDK ZIP deployment in `scripts/deploy.py` with mutually exclusive code/container configuration; verify the real pinned SDK serializes Responses 2.0.0, runtime, bundled entry point, SHA-256, and shared model settings using a mocked transport in `tests/test_deploy.py`.
- [x] 3.3 Implement bounded exact-version polling and safe verification resume in `scripts/verify.py`; verify creating-to-active, failed/deleted/unknown states, transport failures, positive finite deadlines, no automatic redeploy, and endpoint/version mismatch in `tests/test_verification.py`.
- [x] 3.4 Implement unique JSON evidence and shared source/dependency/configuration fingerprints; verify redaction, stage outcomes, no-overwrite, baseline invalidation, and no secret-bearing logs in `tests/test_evidence.py`.
- [x] 3.5 Document ZIP packaging/deployment, agent creation prerequisites, version inspection, and failure recovery; verify CLI help and examples match the implemented arguments.
- [x] 3.6 With approved live targets, deploy the new ZIP agent and pass the common Responses smoke against the exact created version; retain sanitized artifact/version/model evidence and do not reuse the upstream Invocations result.

## 4. Build and locally validate one container

- [x] 4.1 Add Dockerfile and `.dockerignore` using the shared source and pinned runtime graph; verify `docker build` succeeds for Linux x86_64, source/dependency identities match the ZIP baseline, and image content/layers contain no local state or credentials.
- [x] 4.2 Document and configure an approved short-lived local model identity outside the image; run the container noninteractively, verify readiness and the common live model smoke, and record image/platform/config/layer identities.
- [x] 4.3 Enforce matching ZIP and local-container evidence before ACR deployment; verify missing, failed, or stale evidence blocks progression without creating a version in `tests/test_gates.py`.

## 5. Publish and deploy the ACR baseline

- [x] 5.1 Implement the ACR branch of `scripts/publish.sh` for an explicitly selected registry and existing validated image; verify mocked CLI failures propagate, no rebuild occurs, immutable remote identity is recorded, and document publisher-versus-runtime permissions.
- [x] 5.2 Add `deploy/acr/azure.yaml` and the ACR branch of `scripts/deploy_azd.sh` with isolated generated workspaces, existing-project linkage, image passthrough, and no code/remote build; verify rendered configuration, safe shell argument handling, and nonzero error propagation in `tests/test_azd.py`.
- [x] 5.3 Add SDK ACR deployment using the shared image/configuration and verifier; verify actual SDK wire serialization and parity with azd for project, Responses protocol, compute, model settings, and image in `tests/test_deploy.py`.
- [x] 5.4 Document existing-registry setup, actual runtime pull identity, authorization-mode-specific least-privilege roles/scopes, and exact ACR publication/CLI/SDK commands; verify examples against helper help and safe metadata queries.
- [x] 5.5 With approved targets, publish once to ACR and execute ACR/azd and ACR/SDK activation plus exact-version smoke; retain separate publisher/runtime permission evidence and both run outcomes.

## 6. Configure JFrog trust and direct deployment

- [ ] 6.1 Document and complete the administrator handoff for a compatible JFrog tenant, Entra audience application without secret, project managed identity, issuer/identity claims, provider, repository, and token endpoint; verify administrator-confirmed pull success and push denial in an isolated POC scope.
- [x] 6.2 Document an explicit operator-approved registry-connection setup/reuse step and implement metadata-only preflight; verify same-project HTTPS target, audience/provider/token metadata, missing connection, and configuration conflict handling without printing credentials.
- [x] 6.3 Add JFrog publication of the same local build and independent pull to `scripts/publish.sh`; verify manifest/config/layer equivalence, missing/different content rejection, and no ACR import or rebuild in `tests/test_publication.py`.
- [x] 6.4 Add `deploy/jfrog/azure.yaml`, azd and SDK JFrog paths with the existing registry connection and ACR/content gates; verify connection placement, real SDK serialization, equivalent model/runtime settings, and absence of an ACR relay in the offline deployment tests.
- [x] 6.5 Document direct-JFrog CLI/SDK commands, immutable image references, OIDC diagnostics, and registry/token networking prerequisites; verify examples and metadata checks match implemented arguments.
- [ ] 6.6 With approved targets, execute JFrog/azd and JFrog/SDK activation plus exact-version smoke; retain matching image evidence and sanitized registry/OIDC audit corroboration, explicitly recording any caching or audit limitation.

## 7. Complete integration and operational acceptance

- [ ] 7.1 Run isolated negative cases for wrong audience/provider/identity mapping, missing runtime pull permission, denied runtime push, missing/misplaced connection, missing image, model denial, unreachable endpoints, and polling timeout; verify nonzero outcomes, correct stage attribution, no credentials/fallback, and closed progression gates.
- [ ] 7.2 Repeat registry publication/deployment from the already verified build and resume verification of an explicit version; verify no rebuild, unchanged shared resources, isolated azd state, distinct run records, and honest version creation reporting.
- [ ] 7.3 Finish README's manual rollback/cleanup and initial CI/CD design with stage dependencies, separate short-lived identities, approvals, and evidence retention; verify cleanup references only confirmed POC-owned resources and never a shared project/registry.
- [ ] 7.4 Add offline application CI and run `python -m unittest discover -s tests -p 'test_*.py'`, `python -m compileall -q agent scripts tests`, `bash -n scripts/publish.sh scripts/deploy_azd.sh`, and `npx --yes @fission-ai/openspec@1.7.0 validate --all --strict --no-interactive`; record exact results and resolve change-related failures.
- [ ] 7.5 Review the acceptance matrix for new ZIP, local container, and all four registry/entry-point combinations against the three delta specs; verify each scenario has test/evidence coverage and explicitly mark unavailable live checks blocked rather than passed.

## Workflow follow-up

- Prepare the implementation PR using the repository PR template; link the tracking issue and this change, summarize the new model-backed baseline and APIM/MCP exclusion, and report actual validation, deviations, risks, and outstanding environment blockers.
- Archive only after the implementation and resulting specifications are accepted; do not archive as part of proposal generation or initial apply.
