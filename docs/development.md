# Development and Contributions

[Overview](../README.md) | [Lab](lab.md) | [Identity and OIDC](identity-and-oidc.md) | [Operations](operations.md) | [Development](development.md)

Run all shell commands from the repository root, not from `docs/`.

Install the pinned environment using the [lab setup](lab.md#getting-started)
before the checks below.

## Development

Activate the virtual environment before running application checks:

```bash
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q agent scripts tests
npx --yes @fission-ai/openspec@1.7.0 validate --all --strict --no-interactive
```

When the relevant files are implemented, start the agent with
`python agent/main.py` and check shell helpers with
`bash -n scripts/publish.sh scripts/deploy_azd.sh`. There is no separate
application formatter/linter configured; follow `.editorconfig`.

The [application CI workflow](../.github/workflows/test-application.yml) runs
these offline tests, Python compilation and shell syntax checks on Python 3.13
for relevant pull requests and pushes to `main`, or by manual dispatch.
It uses mocked model/cloud/registry interfaces, no Azure/JFrog credentials,
and does not build/publish images or create cloud resources. The separate
[OpenSpec workflow](../.github/workflows/validate-openspec.yml) validates
planning changes. Live acceptance remains an explicitly approved operator
step, not a result of green offline CI.

Deployment, publication, OIDC administration, and cleanup require explicit
operator approval and exact resource selection. Do not weaken network/TLS
policy to pass a test, and do not delete shared projects or registries.

Repository architecture, engineering constraints, and agent guidance are
documented in [`AGENTS.md`](../AGENTS.md).

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

## Updating dependency locks

Both lock files pin the same runtime graph. To update dependencies, resolve the
deployment and runtime inputs together before constraining the runtime lock:

```bash
uv pip compile --prerelease=allow --python python3.13 --python-platform x86_64-manylinux2014 requirements-dev.in --output-file requirements-dev.txt
uv pip compile --prerelease=allow --python python3.13 --python-platform x86_64-manylinux2014 --constraint requirements-dev.txt agent/requirements.in --output-file agent/requirements.txt
```
