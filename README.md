# PROJECT_NAME

## Overview

Describe the project, its users, and the problem it solves.

## Getting started

Document prerequisites, installation, configuration, and the commands needed to
run the project locally.

```bash
# Add project setup commands
```

## Development

Document the primary development commands.

```bash
# Build

# Test

# Lint
```

Repository architecture, engineering constraints, and agent guidance are
documented in [`AGENTS.md`](AGENTS.md).

## Specifications and changes

This project uses OpenSpec for spec-driven development:

- Accepted behavior: `openspec/specs/`
- Proposed changes: `openspec/changes/`
- Project context and artifact rules: `openspec/config.yaml`

Start a substantive change from Copilot Chat with:

```text
/opsx-propose "describe the change"
```

Every implementation pull request should link its GitHub issue and corresponding
OpenSpec change.

## Contributing

Before contributing:

1. Read `AGENTS.md`.
2. Create or select the relevant GitHub issue.
3. Follow the OpenSpec workflow for substantive behavioral changes.
4. Use the pull request template and report validation actually performed.

