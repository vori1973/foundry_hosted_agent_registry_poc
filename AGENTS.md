# Repository Instructions

## Project context

This POC lets developers and platform operators compare one model-backed
Responses agent deployed to Microsoft Foundry from ZIP, ACR, and directly from
JFrog. APIM and MCP are excluded from the current change.

- **Architecture:** `agent/` owns runtime model interaction; `scripts/` owns
  packaging, preflight, deployment and verification; `deploy/` owns azd
  configuration. Runtime code must not depend on deployment helpers or another
  local checkout. CLI and SDK paths share verification and evidence rules.
- **Technology:** Python 3.13, Linux x86_64 containers, Responses 2.0.0, Microsoft
  Agent Framework Foundry hosting, Azure AI Projects SDK, Azure Identity, Bash,
  Azure CLI, and Azure Developer CLI. Pin compatible dependencies before use.
- **Commands:** Use a local Python 3.13 virtual environment. Install with
  `python -m pip install -r requirements-dev.txt`. Run application checks with
  `python -m unittest discover -s tests -p 'test_*.py'` and
  `python -m compileall -q agent scripts tests`. Once shell helpers exist, check
  them with `bash -n scripts/publish.sh scripts/deploy_azd.sh`. Validate planning
  with `npx --yes @fission-ai/openspec@1.7.0 validate --all --strict --no-interactive`.
  Run the application with `python agent/main.py`; README documents prerequisites.
- **Constraints:** Use an explicitly selected existing Foundry project and model.
  Require approved network paths and Azure identity authentication. Never store
  credentials, tokens, customer prompts, or raw authentication responses in
  source, artifacts, images, logs, or evidence. Never disable TLS verification.
  Use the same source/dependencies/model across methods; ZIP and local smoke
  precede ACR, and successful ACR precedes JFrog. Do not copy JFrog images to ACR
  as a deployment fallback.
- **Ownership:** Identity/RBAC, OIDC trust, registry connections, networking,
  evidence redaction, and cleanup need platform/security-owner review. Obtain
  explicit target selection and approval before billable cloud mutations or
  destructive cleanup. An apply request alone does not choose cloud targets.

Tasks remain incomplete until their specified tests or operational evidence
exist. Unavailable live checks are blockers, not successful acceptance. Do not
redeclare Foundry's reserved platform-injected variables in hosted definitions;
local configuration may supply the project endpoint for development.

## Source of truth

- GitHub issues define the problem, motivation, and ownership.
- `openspec/specs/` defines accepted product behavior.
- `openspec/changes/` contains proposed behavioral changes and implementation
  tasks.
- The codebase and automated tests demonstrate the current implementation.

If these sources disagree, stop and surface the conflict rather than silently
choosing one.

## Change workflow

1. Read this file, `openspec/config.yaml`, and relevant accepted specifications.
2. Inspect related GitHub issues and open pull requests before proposing work.
3. Use `/opsx-explore` for investigation that should not yet create artifacts.
4. Use `/opsx-propose` for substantive features, behavior changes, migrations,
   or architectural changes.
5. Review and approve the proposal and acceptance scenarios before applying it.
6. Use `/opsx-apply` and keep `tasks.md` accurate as work progresses.
7. Validate the exact acceptance scenarios and run the smallest relevant
   repository checks.
8. Open a pull request linking both the issue and OpenSpec change.
9. Archive the OpenSpec change only after the implementation is accepted.

Small documentation corrections, formatting-only edits, and clearly
non-behavioral maintenance may proceed without a new OpenSpec change.

## GitHub conventions

- Prefer an existing issue over creating a duplicate.
- Use one OpenSpec change for one cohesive outcome.
- When practical, name changes `<issue-number>-<short-description>`.
- Use `Closes #<issue>` only when the pull request fully resolves that issue.
- Never claim validation that was not run.
- Record intentional deviations from the approved proposal in the pull request.

## Engineering expectations

- Make focused changes and preserve unrelated behavior.
- Reuse established patterns before introducing abstractions or dependencies.
- Add or update tests for changed behavior and acceptance scenarios.
- Handle failures explicitly; do not hide errors behind success-shaped defaults.
- Keep credentials, tokens, personal data, and environment-specific values out
  of source control.
