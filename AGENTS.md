# Repository Instructions

## Required project customization

Replace this section when creating a project from the template:

- **Purpose:** Describe the product and its users.
- **Architecture:** List the major components and dependency boundaries.
- **Technology:** List languages, frameworks, SDKs, and supported versions.
- **Commands:** Document setup, build, lint, test, and run commands.
- **Constraints:** Record security, compatibility, performance, and deployment
  requirements.
- **Ownership:** Identify sensitive areas or paths requiring specialist review.

Do not begin implementation until the commands and constraints relevant to the
requested change are known.

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

