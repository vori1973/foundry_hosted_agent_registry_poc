# GitHub Copilot Instructions

Follow `AGENTS.md` and the OpenSpec-generated instructions in this repository.

Before changing code:

1. Identify the related GitHub issue, accepted specification, and open pull
   requests.
2. Read `openspec/config.yaml` for project context and artifact rules.
3. For substantive behavioral work, create or update an OpenSpec change before
   implementation.
4. Treat proposal approval as a gate; do not invent missing product decisions.

During implementation:

- Work from the approved OpenSpec artifacts and keep `tasks.md` current.
- Follow repository-local architecture, commands, and validation requirements.
- Keep the change scoped to the issue and proposal.
- Add tests for specified acceptance scenarios.
- Surface conflicts between the issue, specifications, tests, and code.

When preparing a pull request:

- Link the issue and OpenSpec change.
- Summarize user-visible behavior and noteworthy design decisions.
- List validation actually performed.
- Call out deviations, follow-up work, risks, and unverified assumptions.
- Do not archive the OpenSpec change until the implementation is accepted.

