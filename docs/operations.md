# Operations and Recovery

[Overview](../README.md) | [Lab](lab.md) | [Identity and OIDC](identity-and-oidc.md) | [Operations](operations.md) | [Development](development.md)

Run all shell commands from the repository root, not from `docs/`.

Use the selected project/model settings, agent/version and evidence paths from
the [lab walkthrough](lab.md). Recovery examples assume those shell variables
are still set; in a new terminal, restore them from the selected run's nonsecret
configuration and sanitized evidence before executing a command.

## Evidence and completion signals

Each invocation writes a unique ignored `.artifacts/<run-id>/deployment.json`;
`--evidence <new-filename>` selects a different destination without allowing
overwrites. Records include stage outcomes, UTC times, tool/runtime versions,
source/dependency/ZIP hashes, shared configuration fingerprint, model deployment,
created version, and allowlisted smoke assertions/correlation. They omit raw
model/error text and credentials. A nonzero exit means blocked or failed, even
if a version was created.

## Inspection and verification recovery

Keep the printed agent/version and evidence after failure or timeout. Inspect
that exact version in the selected project's Foundry agent list. An approved
read-only SDK check can also print only its identity and provisioning state:

```bash
export INSPECT_AGENT="$ZIP_AGENT"
export INSPECT_VERSION="<version-from-evidence>"
python - <<'PY'
import os
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

with DefaultAzureCredential() as credential, AIProjectClient(
    endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=credential,
    allow_preview=True, retry_total=0, connection_timeout=10, read_timeout=30,
) as project:
    agent = project.agents.get_version(
        agent_name=os.environ["INSPECT_AGENT"],
        agent_version=os.environ["INSPECT_VERSION"],
    )
    print({"name": agent.name, "version": agent.version, "status": agent.status})
PY
```

Correct the cause without weakening TLS/network policy. To retry activation
checks and one synthetic smoke against the retained version, keep the same
source, lock files, project/model settings and name:

```bash
python scripts/deploy.py --method zip --name "$INSPECT_AGENT" \
  --version "$INSPECT_VERSION" --timeout 600 --approve-cloud
```

This resume path does **not** upload code, create a version, or change endpoint
routing. It checks POC ownership and the current workload fingerprint, then
requires an already-exclusive route to that version. A missing/mismatched route
is blocked; after resolving it through an explicitly approved operator action,
resume again. Failed provisioning cannot pass smoke. Do not rerun creation
automatically after timeout: a new deployment command may create a new version.
There is no automatic deletion/rollback; retain evidence and confirm POC
ownership before any separate cleanup.

## ACR recovery

On timeout/failure, retain the evidence and inspect the named agent/version
before doing anything that could create another version. To verify an explicit
retained version without creating a version or changing routing:

```bash
python scripts/deploy.py --method acr --name "<retained-agent>" --version "<version>" \
  --image "$IMAGE" --zip-evidence "$ZIP_EVIDENCE" --local-evidence "$LOCAL_EVIDENCE" \
  --publication-evidence "$PUBLICATION_EVIDENCE" --approve-cloud
```

Resume is still an inference request requiring approval. It validates POC
metadata, the current workload/image, and exclusive endpoint binding; it never
repairs routing or retries a failed generation automatically. Direct-JFrog
deployment additionally requires the [ACR evidence in the lab](lab.md#direct-jfrog-deployment).

## JFrog recovery and runtime audit

On failure, retain the exact version and evidence. A failed azd command also
retains its workspace and attempts to discover any already-created version;
do not rerun creation blindly. SDK verification resume uses `--version` with
the same image and all six [evidence arguments from the lab](lab.md#direct-jfrog-deployment); it does not recreate
the version or repair routing, and its smoke still requires inference approval.

For `registry_preflight`, check project/connection selection and the exact
target, audience, provider and endpoint without dumping credential values.
For image acquisition/activation failures, have the administrator inspect
sanitized OIDC audit events for issuer, audience and project `oid` match,
mapping selection, token lifetime and repository read permission. Check
approved DNS/HTTPS access from Foundry to both the registry and exchange
endpoint, plus any required blob-storage origins. Do not repair a runtime
failure using publisher credentials, broader permissions or an ACR relay.
For a version that activates but fails smoke, investigate the separate
hosted model identity and model access rather than assuming a registry problem.

Correlate the run/version and UTC times with JFrog token-exchange and registry
pull audit events. Activation alone is not proof of a fresh OIDC exchange
or download: Foundry can cache the already-known image. Explicitly record
unavailable audit evidence and separately obtain runtime push-denial proof;
publisher push/pull success cannot satisfy either runtime acceptance check.

## Updating an existing agent from an approved JFrog artifact

Foundry agent versions are immutable. Updating the container image, runtime
configuration or model settings means **creating a new version under the
existing agent name**, not editing an already-deployed version. The logical
agent and its stable endpoint can remain the same. Changing the endpoint's
version selector is a separate operation that selects which version is served.

Pushing or promoting an image in JFrog does not update an existing Foundry
version. An operator or deployment pipeline must submit the new image digest
and registry connection. Foundry then handles image acquisition using the
project managed identity and JFrog OIDC exchange. There is no separate pull
button, and caching means activation does not prove a fresh layer download.
Do not use a mutable tag such as `latest` as the deployment identity.

### Manual update using the repository SDK helper

For an explicitly approved update to an **existing POC-owned test agent**,
set `JFROG_IMAGE` to the newly approved digest-qualified reference. Retain the
same project, agent name and compatible existing registry connection, and
supply evidence for the selected build:

```bash
UPDATE_AGENT="<existing-POC-owned-test-agent>"
python scripts/deploy.py --method jfrog --name "$UPDATE_AGENT" --image "$JFROG_IMAGE" \
  --zip-evidence "$ZIP_EVIDENCE" --local-evidence "$LOCAL_EVIDENCE" \
  --publication-evidence "$JFROG_PUBLICATION_EVIDENCE" \
  --acr-publication-evidence "$PUBLICATION_EVIDENCE" \
  --acr-sdk-evidence "$ACR_SDK_EVIDENCE" --acr-azd-evidence "$ACR_AZD_EVIDENCE" \
  --approve-cloud
```

Omitting `--version` creates a new version; capture its actual ID from the
result instead of assuming it is the previous ID plus one. The SDK helper
permits an existing name only when its latest version carries this POC's
ownership metadata. It refuses to adopt an unrelated customer agent. General
customer update automation should use the supported SDK/API with the customer's
own ownership and approval controls.

The POC still requires matching ZIP/local smoke, ACR publication and both ACR
model-smoke baselines for this build. A source/dependency/shared-configuration
change invalidates earlier baselines; regenerate the affected evidence rather
than reusing results from the previous artifact. Reuse the registry connection
only if its project, target, audience, provider and repository permissions
remain correct; changes to trust or access need separate approval.

**Routing caution:** the current SDK helper waits for activation, switches the
selected agent endpoint to 100% of the new version, and then runs its smoke.
It is a POC deployment command, not a production validate-before-promotion
pipeline. The azd helper deliberately requires a fresh agent name for isolated
comparison runs; it is not an existing-agent update wrapper. `--version`
on the SDK helper only resumes verification: it neither updates the image nor
changes routing.

### CI/CD-neutral release and rollout design

Customers can implement the same contract with **GitHub Actions, Azure DevOps
Pipelines, GitLab CI/CD, Jenkins, or another approved orchestrator**. GitHub is
an example, not a requirement. The deployment boundary is a supported Foundry
SDK/API call or an azd deployment of the approved prebuilt image, not a
particular source-control or CI/CD product.

```text
Build once -> Test/scan -> Push to JFrog -> Approve exact artifact digest
    -> Authenticated release trigger or manual pipeline run
    -> Validate isolated candidate -> Approve production promotion
    -> Create new production agent version -> Wait for Active
    -> Select version on stable endpoint -> Smoke -> Retain rollback target
```

An organization may scan after upload or promote into a release repository;
in either case, verify approval and policy results against the final selected
digest before deployment. Ensure the runtime mapping has read-only access to
that exact release repository; do not broaden permissions automatically.

1. **Trigger:** start from an approved release/promotion, not every artifact
   upload. Use an authenticated JFrog event integration supported by the
   customer's installation, or a manual release run initially. Where needed,
   an authenticated bridge translates the event into the orchestrator's
   trigger API. Treat the event as a notification: recheck the approval,
   allowlisted registry/repository and digest against trusted release records.
2. **Inputs:** carry the immutable image reference, source/build identity,
   approval reference, project, logical agent name, registry connection and
   runtime configuration. Preserve required test/publication evidence in
   controlled pipeline artifacts, not just workstation `.artifacts` files.
3. **Identity:** keep publisher-to-JFrog, pipeline-to-Azure and Foundry-to-JFrog
   identities separate. Prefer workload federation/OIDC or an approved runner
   managed identity for Azure deployment. The existing audience-only Entra
   application is not the pipeline deployment identity. Never pass the
   publisher token to Foundry or store permanent registry pull credentials.
4. **Validate and deploy:** test an isolated candidate using the approved
   image/configuration. Before creating a production version, explicitly pin
   its stable endpoint to the current known-good version; Foundry's default
   "Always use latest" can otherwise advance traffic when a version is created.
   Record the old version/selector, create the new version under the existing
   production agent name and wait with a finite timeout. Do not rebuild,
   silently create shared resources, copy to ACR or change routing on failure.
5. **Promote:** after candidate validation and production-version activation,
   require the customer's environment/release approval before changing the
   production endpoint selector. Read back the selected version, run one
   approved exact-version model smoke and retain the result. Candidate testing
   does not replace the production post-promotion smoke. This staged routing
   controller is a customer pipeline responsibility, not implemented by the
   current POC helper.
6. **Recover and audit:** serialize releases per project/agent and correlate
   duplicate events with the existing run/version before submitting again.
   A repeated creation command can create another immutable version. Retain
   digest, approval, created version, routing changes, timing and sanitized
   outcome; never save tokens or raw authentication responses.

For rollback, an authorized operator selects the retained known-good version
on the same agent endpoint instead of repushing an old image or editing a
version. In Foundry, open the agent's **Publish** dropdown and version selector;
choose the known-good version and confirm the endpoint routing. SDK automation
can use `agents.update_details` with an explicit `VersionSelector` and
`FixedRatioVersionSelectionRule`. Read back the binding and verify recovery;
retain the failed version for diagnosis. Existing sessions can remain bound
to their original version, so changing the selector is not a guarantee of
migrating every in-flight session. Do not delete shared projects or registries.

For example, GitHub Actions can use environment approvals, Azure DevOps can
use environment approvals/checks, GitLab can use protected environments and
deployment approvals where available, and Jenkins can use a controlled approval
stage. Configure equivalent controls for the customer's platform and license.
These are design options, not claims that live CD or production rollback is
already configured in this repository. Full operational acceptance remains
tracked by the open OpenSpec tasks.

References:
[manage hosted agents and create versions](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-agent),
[select the active version](https://learn.microsoft.com/azure/foundry/agents/how-to/configure-agent),
[direct private-registry deployment](https://learn.microsoft.com/azure/foundry/agents/how-to/private-registry-connections),
and [Microsoft's GitHub Actions example](https://learn.microsoft.com/azure/foundry/agents/quickstarts/set-up-cicd-hosted-agent).

## Manual cleanup

Cleanup is a separate, destructive operator action, not part of a deployment
or verification-resume command. Retain failed versions and sanitized evidence
until diagnosis and the retention period are complete. No automated cleanup
or live cleanup success is claimed here.

### Inventory and confirmation

Select one deployment evidence file and restore its selected project endpoint
from your approved target inventory. Evidence does not store the endpoint;
do not infer the project from an agent name. This read-only check correlates
the exact retained version with the evidence and POC ownership metadata:

```bash
export CLEANUP_EVIDENCE=".artifacts/<selected-run>/deployment.json"
python - <<'PY'
import os
from pathlib import Path
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from scripts.verify import CHANGE, read_record

record = read_record(Path(os.environ["CLEANUP_EVIDENCE"]))
name, version = record["agent_name"], record["agent_version"]
endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
with DefaultAzureCredential() as credential, AIProjectClient(
    endpoint=endpoint, credential=credential, allow_preview=True,
    retry_total=0, connection_timeout=10, read_timeout=30,
) as project:
    state = project.agents.get_version(agent_name=name, agent_version=version)
    metadata = state.metadata or {}
    if (
        state.name != name or str(state.version) != str(version)
        or metadata.get("poc_change") != CHANGE
        or metadata.get("poc_baseline") != record["baseline_fingerprint"]
        or metadata.get("poc_method") != record["method"]
    ):
        raise SystemExit("Ownership mismatch: stop cleanup.")
    print({
        "project_endpoint": endpoint, "agent_name": name,
        "agent_version": version, "status": state.status,
        "image_reference": record.get("image_reference"),
        "registry_connection": record.get("registry_connection"),
    })
PY
```

Missing evidence, a missing version or an ownership mismatch is a stop, not
permission to delete a similarly named resource. A failed azd run without a
version requires separate administrator discovery and ownership confirmation.
Record the following allowlisted inventory outside source control and obtain
owner approval for the exact items selected for deletion:

| Resource | Required confirmation |
|---|---|
| Agent version | Selected project ARM ID/endpoint, exact agent/version, POC ownership, endpoint routing and retained rollback dependencies |
| Registry artifact | Exact registry/repository/digest and publication tag from publication evidence; confirm no retained version or another workload references the digest |
| Registry connection | Exact same-project connection ID/name, owner and every remaining consumer; retain the connection by default |
| Trust and permissions | Exact JFrog provider/mapping/group/permission or Azure role-assignment ID, owner and other consumers; retain by default |
| Local generated state | Exact run workspace, local container/image ID and temporary credential-file path; confirm the process has stopped and evidence has been retained |

### Remove only approved POC resources

1. **Agent versions:** first inspect the agent's endpoint selector and dependent
   sessions. Never delete the selected active or retained rollback version.
   Any routing change needs separate approval and read-back verification.
   After an unused version is explicitly approved for removal, use the Foundry
   version-management interface or the pinned SDK's
   `project.agents.delete_version(agent_name=name, agent_version=version, force=False)`.
   Do not use a whole-agent delete or force deletion to bypass dependencies.
   Confirm that the exact version is absent; distinguish NotFound from access
   denial or network errors.
2. **Registry artifacts:** remove only an explicitly approved publication tag
   or unused manifest using the registry's management interface. A manifest
   deletion can affect multiple tags; inspect references first. Never delete
   the Docker repository or registry as a shortcut. Keep artifacts required
   by retained versions and rollback.
3. **Connections and trust:** retain reused connections, Entra audience apps,
   managed identities, role assignments and JFrog trust by default. Only their
   platform/security owner may remove an exact POC-only object after proving
   it has no other consumers. Never delete a shared Foundry project, account,
   model deployment, ACR or JFrog repository, or alter shared network policy.
4. **Local state:** the local-smoke helper stops/removes its temporary container
   and in-memory identity mount; publisher helpers remove their own temporary
   Docker auth directory. Verify the recorded cleanup outcome. If an operator
   supplied a token file, remove only that exact file, including after failure.
   After evidence retention, remove only individually reviewed run workspaces
   and unused local image/container IDs. Do not remove all `.artifacts` or
   another user's Docker state.
5. **Record the outcome:** retain approval, selected identifiers, UTC time and
   deletion/read-back outcome without credentials or raw authentication
   responses. Stop and record partial cleanup if any dependency or ownership
   check fails.

Never run `azd down`, delete a resource group, or use a bulk registry/Docker
prune as cleanup for this existing-resource lab. These instructions describe
the manual procedure; executing it needs a separate explicit approval.
