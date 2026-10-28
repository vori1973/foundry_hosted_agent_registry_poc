# Identity and JFrog OIDC Reference

[Overview](../README.md) | [Lab](lab.md) | [Identity and OIDC](identity-and-oidc.md) | [Operations](operations.md) | [Development](development.md)

Run all shell commands from the repository root, not from `docs/`.

## How the project managed identity pulls the image

The Entra app registration is an **audience**, not the identity pulling the
image. We do not give that audience-only app access to the Foundry project.
The existing **Foundry project managed identity** authenticates the pull;
JFrog grants repository access through its own identity mapping and group
permissions, not through an Azure role assignment to the audience app.

```text
Agent deployment references a JFrog image and same-project registry connection
  |
  v
Foundry obtains an Entra token using the project managed identity
  oid = project identity principal ID
  tid = project identity tenant ID
  aud = audience app's application (client) ID
  |
  v
Foundry sends the token to JFrog /access/api/v1/oidc/token
  using the connection's body.provider_name
  |
  v
JFrog validates signature, issuer, audience and matching identity claims
  |
  v
Identity mapping selects a dedicated read-only repository group
  |
  v
JFrog issues a short-lived credential; Foundry uses it to pull the image
```

Foundry performs this exchange during image acquisition; the agent application
does not implement it. The hosted agent's model-calling identity and the
publisher's push credentials are separate. A cached image can avoid a fresh
download, so activation alone does not demonstrate every step above.

## Where each OIDC value comes from

Use the explicitly selected project ARM ID, not the parent Foundry account ID.
These read-only commands retrieve the project identity without requesting or
printing a token:

```bash
az resource show --ids "$FOUNDRY_PROJECT_ID" --api-version 2025-06-01 \
  --query '{projectId:id,principalId:identity.principalId,tenantId:identity.tenantId}' \
  --output json
```

Stop if either identity value is absent. Have the platform owner confirm the
selected project's managed identity; do not substitute your signed-in user's
object ID, the audience app's Object ID, or an identity from another project.

| Setting | Source and meaning |
|---|---|
| Audience / `aud` / `JFROG_AUDIENCE` | **Application (client) ID** from the audience app registration's Overview, not its Object ID. Use the same value in the JFrog provider, identity mapping and Foundry connection. |
| Mapping `oid` | Selected project's `identity.principalId` above. Identifies the caller and restricts this mapping to that project identity. |
| Mapping `tid` | Selected project's `identity.tenantId` above. Identifies the issuing Entra directory; confirm it matches the intended tenant. |
| Provider URL | Tenant authority `https://login.microsoftonline.com/<tenant-id>` for the default v1 setup; discovery metadata is under `/.well-known/openid-configuration`. |
| Token Issuer | Issuer from that tenant's discovery metadata, matching the actual token version. For the default v1 setup: `https://sts.windows.net/<tenant-id>/`, including the trailing slash. |
| Provider Name / `JFROG_OIDC_PROVIDER_NAME` | Administrator-chosen JFrog integration name, for example `foundrypoc`. The connection's `body.provider_name` must match it exactly. |
| Azure App Id field in JFrog | Only needed for custom signing keys in this setup; leave blank for the default configuration. It is not where the audience app ID goes. |
| Mapping name and priority | Administrator-chosen rule label and evaluation order, not Azure identifiers. Review other mappings so a broader rule does not grant unintended access. |
| Group and repository | Administrator-created JFrog runtime group and exact Docker repository. A JFrog permission grants that group Read only on that repository. |
| Service and expiration | Restrict the exchanged credential to Artifactory and a short lifetime, such as 15 minutes. |
| Registry target / `JFROG_REGISTRY_ORIGIN` | Approved HTTPS registry origin from Docker Set Me Up, without an API/repository path. |
| Token endpoint / `JFROG_TOKEN_ENDPOINT` | JFrog's `/access/api/v1/oidc/token`; not a value from the app registration. |

For example, the identity mapping's Claims JSON should contain these three
exact matches. Replace the placeholders with the values above in the JFrog UI;
these are match conditions, not a token to generate or store:

```json
{
  "tid": "<project-identity-tenant-id>",
  "oid": "<project-identity-principal-id>",
  "aud": "<audience-application-client-id>"
}
```

The audience answers "what is this token intended for?" and `oid` answers
"who is requesting access?" Knowing the audience app ID does not authorize
another project through this mapping. The dedicated group's repository
permission determines what the matched identity may do.

## Select or create the audience application

Prefer an existing approved audience app. Read its **Application (client) ID**
from Entra ID > App registrations > the application > Overview and set
`JFROG_AUDIENCE` in your own shell. You can inspect that app without requesting
a token:

```bash
az ad app show --id "$JFROG_AUDIENCE" \
  --query '{applicationClientId:appId,appRegistrationObjectId:id}' --output json
```

If a new audience app is needed, obtain explicit approval before running this
creation command. Do not run it on every lab execution:

```bash
export JFROG_AUDIENCE="$(az ad app create \
  --display-name "<approved-audience-app-name>" --query appId --output tsv)"
```

No client secret, API permission, Foundry role or federated credential on this
audience-only app is required. Creating the app does not grant registry access:
the claim mapping and repository permission below do that.

## Administrator-owned trust and permissions

Confirm that the selected JFrog tenant supports inbound OIDC token exchange,
not just SSO. JFrog documents this feature for Enterprise X/Enterprise+;
confirm the actual trial/license entitlement before proceeding. No JFrog CLI
or Copilot JFrog MCP connection is required.

1. With separate operator approval, create/reuse an Entra application as the
   audience. No client secret, API permissions, or Azure role assignment is
   needed for this audience-only application. Record its application/client ID.
2. Read the selected Foundry project's `identity.principalId` and tenant ID.
   The project identity pulls the image; the hosted agent identity calls the
   model. Do not substitute the developer/publisher identity for either.
3. In JFrog **Administration > General Management > Manage Integrations**, add
   an Azure OIDC provider. Use the exact name accepted by the UI; an
   alphanumeric name avoids provider-name validation differences. Configure
   the audience above and tenant-specific provider discovery URL. Match the
   token issuer to the resource's actual token version: default v1 resource
   tokens use `https://sts.windows.net/<tenant-id>/`, with discovery under
   `https://login.microsoftonline.com/<tenant-id>/.well-known/openid-configuration`.
   Do not assume v2 tokens or borrow a developer token as project-identity proof.
   Azure App Id is only needed for custom signing keys, not this default setup.
4. Create an isolated **Local Docker** repository. Read Docker **Set Me Up**
   to establish the actual registry hostname/repository prefix. The
   `/artifactory/api/docker/<repository>` URL is an API endpoint, not the
   Docker image reference.
5. Create a dedicated runtime group with no administrative roles, no Auto Join,
   and no human/anonymous members. Grant **Read only** on the exact POC
   repository, not Any Local/Remote Repository. Do not reuse the broad `readers`
   group or grant Deploy/Cache, Delete/Overwrite, Annotate, or Manage.
6. Create an identity mapping with exact `tid`, `oid` (project principal ID),
   and `aud` claims. Select **Group**, only the dedicated runtime group, no
   username or additional user/admin scope, Artifactory service only, and a
   short expiration such as 15 minutes. A blank username avoids Auto Join
   expansion. Preserve the exact provider name for `body.provider_name`.
7. Retain administrator-confirmed effective pull success and push denial in the
   isolated POC repository, without token bodies. Runtime OIDC exchange and
   Foundry pull evidence remain separate from publisher success. If those
   checks are unavailable, the trust handoff remains incomplete.

The JFrog token-exchange endpoint is `/access/api/v1/oidc/token`. Both it and
the registry must be reachable over approved HTTPS paths from Foundry.
Independent blob verification can follow HTTPS storage redirects, dropping
authorization on a different origin; permit only approved backing-storage
network paths. Do not disable TLS, enable public exceptions, grant broad roles,
or copy the image into ACR as a workaround.

## Explicit Foundry connection setup and preflight

Connection creation is a separate approved operation, not a deployment side
effect. Compare any existing connection first; stop on conflicts rather than
using `--force`. Set the nonsecret values in [`.env.example`](../.env.example) in your own shell.
After approval, the documented connection shape can be created with:

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd ai connection create "<connection-name>" \
  --project-endpoint "$FOUNDRY_PROJECT_ENDPOINT" \
  --kind custom-keys --auth-type custom-keys --target "$JFROG_REGISTRY_ORIGIN" \
  --custom-key "audience=$JFROG_AUDIENCE" \
  --custom-key "tokenEndpoint=$JFROG_TOKEN_ENDPOINT" \
  --custom-key "body.provider_name=$JFROG_OIDC_PROVIDER_NAME" \
  --metadata "type=registry_connection" --metadata "mode=oauth_token_exchange" \
  --no-prompt
```

Do not dump connection credentials. `scripts/preflight.py --method jfrog`
checks the exact same-project connection ID/name, CustomKeys type, registry
origin/image hostname, audience, provider, exchange endpoint and metadata.
It first checks metadata, then reads only this connection's nonsecret OIDC
configuration into memory using the SDK credential-read endpoint. The pinned
SDK flattens custom keys and lowercases their names; the checker accounts for
that representation but rejects missing, additional, duplicate or different
keys without printing their values. It neither creates nor repairs connections:

```bash
python scripts/preflight.py --method jfrog --name registry-jfrog-preflight \
  --image "$JFROG_IMAGE" --zip-evidence "$ZIP_EVIDENCE" \
  --local-evidence "$LOCAL_EVIDENCE" --check-tools
```

This is a configuration check, not an image-existence, exchange, or inference
test. Use the selected digest-qualified JFrog reference; before publication,
the known ACR manifest digest may identify the intended image for this
metadata-only check.

## Setup and runtime acceptance checklist

Complete these steps in order; an existing correctly configured resource may
be reused after comparison rather than recreated:

1. **Operator/platform owner:** select and approve the project and repository;
   verify its managed identity, compatible Foundry/JFrog capabilities, and
   approved registry/token network paths.
2. **Entra administrator/operator:** create or select the audience-only app and
   record its client ID. No client secret, API permission, Foundry role or
   federated credential on this app is required for this documented flow.
3. **JFrog administrator:** configure the provider and exact claim mapping;
   create the dedicated group and repository Read-only permission. Configure
   publisher access separately.
4. **Foundry operator:** explicitly create or verify the same-project registry
   connection, then run the configuration preflight above. The connection
   tells Foundry where and how to exchange a token; it does not itself grant
   JFrog permissions.
5. **Deployment operator:** after this POC's ZIP/local/ACR evidence gates pass,
   deploy the digest-pinned JFrog image with that connection using the
   [CLI or SDK entry point](lab.md#direct-jfrog-deployment).
   Creating a version triggers image acquisition; there is no separate manual
   runtime pull command.
6. **JFrog administrator and deployment operator:** correlate the exact
   version/run and UTC times with sanitized exchange and pull audit events;
   retain effective runtime pull success and push-denial evidence from an
   isolated approved test. Verify the exact version's model smoke separately.
   Record missing audit evidence or caching limitations as unverified, not
   passed. Do not retain token bodies or use publisher success as runtime proof.
