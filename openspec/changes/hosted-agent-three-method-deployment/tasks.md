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
- [x] 7.3 Finish README-linked `docs/operations.md` manual rollback/cleanup and initial CI/CD design with stage dependencies, separate short-lived identities, approvals, and evidence retention; verify cleanup references only confirmed POC-owned resources and never a shared project/registry.
- [x] 7.4 Add offline application CI and run `python -m unittest discover -s tests -p 'test_*.py'`, `python -m compileall -q agent scripts tests`, `bash -n scripts/publish.sh scripts/deploy_azd.sh`, and `npx --yes @fission-ai/openspec@1.7.0 validate --all --strict --no-interactive`; record exact results and resolve change-related failures.
- [x] 7.5 Review the acceptance matrix for new ZIP, local container, and all four registry/entry-point combinations against the three delta specs; verify each scenario has test/evidence coverage and explicitly mark unavailable live checks blocked rather than passed.

## Implementation notes

- 6.1: Audience app, JFrog provider/claim mapping, dedicated runtime group and
  repository permission have been configured. The checkbox remains open for
  administrator-confirmed runtime pull success and push-denial evidence, not
  missing setup. Publisher pull evidence is not runtime identity evidence.
- 6.6: Both JFrog versions passed exact-version Responses smokes on 2026-10-28:
  the retained azd-created version via SDK verification resume, and a fresh
  SDK-created version. Image/connection and matching predecessor evidence
  passed validation. No second azd deployment, image rebuild, publication,
  role/trust/network change or cleanup was performed. The checkbox remains
  open for sanitized runtime exchange/pull audit corroboration; no fresh
  exchange/download is claimed because caching cannot be ruled out.
- Baseline recovery: the original ZIP evidence omitted its artifact hash.
  An explicitly approved verification resume read the retained version's
  service-reported ZIP digest and passed a new model smoke, writing a fresh
  record without editing historical evidence. The successful local-container
  record is `identityfix-local-smoke.json`, not the earlier failed
  `local-smoke.json`. Existing consistency gates were preserved.
- 7.1: Offline failures are covered by the passing suite, but the specified
  isolated live negatives have not been executed. Permission/trust changes,
  runtime push-denial checks and fault induction require separate approval
  and administrator coordination; the task remains incomplete.
- 7.2: Verification resume was exercised against retained ZIP and JFrog
  versions with fresh run records and no new versions/routing changes.
  Full repeat publication/deployment acceptance and shared-resource/state
  comparison remain incomplete; no additional publication or deployment
  was authorized by the two JFrog smoke approvals.
- 7.3: The README links `docs/operations.md` for manual rollback, owner-approved
  exact-version cleanup, resource inventory and CI/CD design. Documentation
  links, embedded Python syntax and the pinned SDK delete-version signature
  were checked. No destructive cleanup or production rollback was executed.
- 7.4: Added `.github/workflows/test-application.yml` with read-only repository
  permissions, Python 3.13, pinned dependencies and offline checks; existing
  OpenSpec CI remains separate. GitHub-hosted execution has not yet been run.
  The local checks below passed on 2026-10-28 using a clean Python 3.13 virtual
  environment after the existing environment failed to import an incomplete
  OpenAI package. The first suite run exposed a wall-clock-dependent startup
  failure test; its clock is now mocked without changing runtime behavior.

| Validation command | Local result (2026-10-28) |
|---|---|
| `python -m unittest discover -s tests -p 'test_*.py'` | Passed: 84 tests |
| `python -m compileall -q agent scripts tests` | Passed |
| `bash -n scripts/publish.sh scripts/deploy_azd.sh` | Passed |
| `npx --yes @fission-ai/openspec@1.7.0 validate --all --strict --no-interactive` | Passed: 1 change, 0 failures |

## Acceptance review (2026-10-28)

This completes the coverage review in 7.5, not overall implementation
acceptance. All 36 scenarios below have an identified test/evidence source or
an explicit blocked/manual requirement. Offline mocks are not live registry,
identity, networking or production-rollback proof. Paths are relative to the
repository root. Evidence stays in ignored local `.artifacts/`; its filenames
identify records, not a portable enterprise audit store.

### Live evidence index

| ID | Evidence record | What is established |
|---|---|---|
| Z | `.artifacts/zip-reverify-20261028172613/deployment.json` | Retained ZIP version, service-reported artifact SHA-256, exact-version Responses smoke |
| L | `.artifacts/container-20261027T231555Z/identityfix-local-smoke.json` | Immutable local container, model smoke, readiness and cleanup |
| PA | `.artifacts/20261027T235900Z-a5e21d04e6fa/publication.json` | Verified immutable ACR publication and publisher/runtime permission metadata |
| AS | `.artifacts/20261028T000314Z-5d8621736dbd/deployment.json` | ACR/SDK activation and exact-version model smoke |
| AA | `.artifacts/20261028T001734Z-a95f7b954429/deployment.json` | ACR/azd activation and exact-version model smoke |
| PJ | `.artifacts/20261028T020647Z-4dc2019f888b/publication.json` | JFrog publication, matching ACR content and independent publisher-authenticated pull |
| JA | `.artifacts/20261028T021557Z-bca67ecb2ae9/deployment.json` plus `.artifacts/20261028T172713Z-94a906f18e00/deployment.json` | azd-created JFrog version activated; subsequent SDK resume passed exact-version model smoke without redeployment |
| JS | `.artifacts/20261028T172735Z-affe60b898f6/deployment.json` | Fresh JFrog/SDK version activated, endpoint binding checked and model smoke passed |

### responses-agent

| Scenario | Coverage | Review outcome |
|---|---|---|
| Model-backed request succeeds | `tests/test_agent.py`; Z, L, AS, AA, JA, JS | Offline and live functional checks passed |
| Model call fails | `tests/test_agent.py`, `tests/test_smoke.py`, `tests/test_local_smoke.py` | Offline passed; isolated live model denial/timeout blocked pending approval |
| Request is invalid | `tests/test_agent.py` | Offline unsupported-input rejection passed |
| Deployments share behavior | `tests/test_deploy.py`, `tests/test_azd.py`, `tests/test_gates.py`; Z, L, PA, PJ, AS, AA, JA, JS | Offline parity and live shared-workload/content gates passed |
| Required configuration is absent | `tests/test_agent.py`, `tests/test_preflight.py` | Offline fail-closed startup/input checks passed |
| Functional response passes | `tests/test_smoke.py`; Z, L, AS, AA, JA, JS | Offline and live assertions passed |
| Activation alone is insufficient | `tests/test_smoke.py`, `tests/test_gates.py` | Offline empty/incomplete/refusal/marker and active-only gate checks passed |
| Container runs outside Foundry | `tests/test_local_smoke.py`; L | Local live readiness/model smoke and cleanup passed |
| Startup fails | `tests/test_agent.py`, `tests/test_local_smoke.py`, `tests/test_packaging.py` | Offline startup/build failure and cleanup handling passed; no new live fault induced |

### hosted-agent-deployment

| Scenario | Coverage | Review outcome |
|---|---|---|
| ZIP baseline succeeds | `tests/test_deploy.py`; Z | Exact-version smoke and artifact hash passed |
| ZIP packaging excludes local state | `tests/test_packaging.py` | Offline integrity, layout, excluded-state and unsafe-path checks passed |
| Missing predecessor blocks progression | `tests/test_gates.py`; initial live preflight stopped on missing ZIP hash | Passed without weakening evidence gates or creating a version |
| Shared workload changes invalidate baseline | `tests/test_gates.py`, `tests/test_evidence.py` | Offline model/source/dependency/artifact invalidation passed |
| One build is published twice | `tests/test_publication.py`, `tests/test_gates.py`; PA, PJ | Registry content equivalence and independent JFrog publisher pull passed |
| Content cannot be verified | `tests/test_publication.py`, `tests/test_gates.py` | Offline mismatch/corrupt-layer/failed-pull rejection passed |
| ACR baseline succeeds | `tests/test_publication.py`, `tests/test_deploy.py`; PA, AS, AA | Live ACR permission metadata, activation and both smokes passed |
| Publisher can push but runtime cannot pull | `tests/test_publication.py` | Offline permission-separation gate passed; isolated live runtime-pull denial blocked |
| Direct JFrog deployment succeeds | `tests/test_deploy.py`, `tests/test_azd.py`, `tests/test_gates.py`; PJ, JA, JS | Both created versions passed model smokes; fresh runtime exchange/download audit proof blocked |
| Audience or identity mapping is wrong | `tests/test_preflight.py`, `tests/test_deploy.py` | Offline audience/provider connection conflicts passed; live issuer/mapping rejection and no-fallback proof blocked |
| Registry connection is invalid | `tests/test_preflight.py`, `tests/test_deploy.py` | Offline missing/unreadable/wrong-project/type/target/mode conflicts passed; live isolated connection-negative matrix blocked |
| Pull-only mapping is verified | Configured group/repository permission; administrator runtime audit and denied-push check required | Blocked: publisher evidence and active agents do not establish effective runtime push denial |
| JFrog lacks required capabilities | `docs/identity-and-oidc.md` administrator capability gate; `tests/test_preflight.py` connection checks | Manual unsupported-tenant confirmation not available; do not infer exchange compatibility from SSO |
| Network access is unavailable | `tests/test_preflight.py`, `tests/test_verification.py`, `tests/test_publication.py` | Offline endpoint/transport/redirect handling passed; live isolated network failure blocked |

### deployment-automation

| Scenario | Coverage | Review outcome |
|---|---|---|
| Both entry points deploy both registries | `tests/test_deploy.py`, `tests/test_azd.py`; AS, AA, JA, JS | Live creation/activation/smoke covered; JA creation and later smoke are separate correlated records |
| Configuration is incomplete | `tests/test_preflight.py`, `tests/test_deploy.py`, `tests/test_gates.py` | Offline nonzero-before-mutation checks passed |
| Version becomes active | `tests/test_verification.py`; Z, AS, AA, JA, JS | Offline bounded polling and live exact-version verification passed |
| Version fails or is deleted | `tests/test_verification.py`, `tests/test_deploy.py` | Offline terminal/unknown-state rejection and retained-version behavior passed; no live deletion induced |
| Provisioning exceeds the deadline | `tests/test_verification.py` | Offline deterministic finite-deadline/no-redeploy checks passed; live induced timeout blocked |
| Endpoint targets another version | `tests/test_verification.py` | Offline missing/wrong/mixed route and post-smoke drift rejection passed |
| Registry deployment is repeated | `tests/test_publication.py`, `tests/test_azd.py`; retained-version resume in JA | Offline retained-tag/workspace behavior and live resume covered; full repeated live publication/deployment acceptance blocked |
| Existing configuration conflicts | `tests/test_preflight.py`, `tests/test_azd.py`, `tests/test_deploy.py` | Offline connection/project/ownership conflicts passed without overwrite |
| Evidence records a successful deployment | `tests/test_evidence.py`, `tests/test_smoke.py`; Z, AS, AA, JA, JS | Unique records, artifact identity and allowlisted smoke assertions passed |
| A stage is blocked or fails | `tests/test_evidence.py`, `tests/test_deploy.py`, `tests/test_gates.py`, `tests/test_local_smoke.py` | Offline failed/blocked status and gated continuation passed; live smoke failures not manufactured |
| Sensitive error content is returned | `tests/test_evidence.py`, `tests/test_agent.py`, `tests/test_deploy.py`, `tests/test_publication.py` | Offline synthetic-secret redaction/allowlisting passed; no real secret retained as test evidence |
| Administrator handoff is needed | `docs/identity-and-oidc.md`, `tests/test_preflight.py`; configured trust/connection | Setup documented and connection checked; effective runtime permission attestation remains blocked under 6.1 |
| Operator cleans up a failed run | `docs/operations.md` manual inventory/ownership/approval procedure | Documentation, embedded Python and SDK contract checked; destructive cloud cleanup not authorized or executed |

## Workflow follow-up

- Prepare the implementation PR using the repository PR template; link the tracking issue and this change, summarize the new model-backed baseline and APIM/MCP exclusion, and report actual validation, deviations, risks, and outstanding environment blockers.
- Archive only after the implementation and resulting specifications are accepted; do not archive as part of proposal generation or initial apply.
