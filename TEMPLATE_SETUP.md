# Copilot OpenSpec Project Template

Use this repository as a GitHub template for projects that follow a
GitHub Issue -> OpenSpec change -> pull request workflow.

This setup guide is copied into repositories created from the template. Delete
it after completing the project customization steps below.

## Publish this repository as a GitHub template

This is a one-time setup for the repository that contains this template:

1. Create an empty GitHub repository, for example
   `copilot-openspec-project-template`.
2. Push this repository to GitHub:

   ```bash
   git add .
   git commit -m "Create Copilot OpenSpec project template"
   git remote add origin https://github.com/OWNER/copilot-openspec-project-template.git
   git push -u origin main
   ```

3. On GitHub, open **Settings > General** for the repository.
4. Enable **Template repository**.

Replace `OWNER` with your GitHub user or organization.

## Create a project from the template

### GitHub website

1. Open the template repository on GitHub.
2. Select **Use this template > Create a new repository**.
3. Choose the owner, repository name, visibility, and description.
4. Select **Create repository**.
5. Clone the new repository:

   ```bash
   git clone https://github.com/OWNER/NEW-PROJECT.git
   cd NEW-PROJECT
   ```

### GitHub CLI

If the GitHub CLI is installed and authenticated, create and clone the project
with:

```bash
gh repo create OWNER/NEW-PROJECT \
  --template OWNER/copilot-openspec-project-template \
  --private \
  --clone
cd NEW-PROJECT
```

Use `--public` instead of `--private` when appropriate.

## Customize the new project

1. Replace the placeholders in `README.md` with the project name, purpose,
   setup, and usage instructions.
2. Update `AGENTS.md` with the project's purpose, architecture, commands, and
   constraints.
3. Replace the template context in `openspec/config.yaml` with project-specific
   information.
4. Replace `OWNER/REPOSITORY` in
   `.github/ISSUE_TEMPLATE/config.yml`.
5. Refresh the generated OpenSpec integrations:

   ```bash
   openspec update
   ```

6. Remove this template-only setup guide:

   ```bash
   rm TEMPLATE_SETUP.md
   ```

7. Commit the project-specific customization:

   ```bash
   git add .
   git commit -m "Configure project instructions"
   git push
   ```

8. Create the first OpenSpec change from Copilot Chat:

   ```text
   /opsx-propose "describe the change"
   ```

## Workflow

1. Create or select a GitHub issue.
2. Explore the problem with `/opsx-explore` when requirements are unclear.
3. Create an OpenSpec proposal with `/opsx-propose`.
4. Review the proposal, design, specifications, and task list.
5. Implement with `/opsx-apply`.
6. Open a pull request that links the issue and OpenSpec change.
7. Validate the implementation and archive the accepted change with
   `/opsx-archive`.

OpenSpec-generated prompts and skills are under `.github/prompts/` and
`.github/skills/`. Refresh them with `openspec update`; do not customize
generated files directly.
