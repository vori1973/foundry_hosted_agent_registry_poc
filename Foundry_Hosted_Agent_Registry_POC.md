# Microsoft Foundry Hosted Agent Registry Deployment POC

## ZIP Baseline, ACR Validation, Direct JFrog Deployment, and Automation

## 1. Purpose

This proof of concept validates a controlled progression for deploying a Microsoft Foundry Hosted Agent:

1. Start from  ZIP-based Hosted Agent deployment.
2. Convert the same agent into a reusable container image.
3. Push the image to Azure Container Registry.
4. Deploy the agent from ACR to establish a container-based baseline.
5. Push the identical image to JFrog Artifactory.
6. Configure Foundry and JFrog for OIDC token exchange.
7. Deploy the Hosted Agent directly from JFrog.
8. Automate image publication, Hosted Agent deployment, status validation, and smoke testing through CLI or SDK.

The ACR deployment is the control test. Direct deployment from JFrog and repeatable automation are the primary objectives.

---

## 2. Primary POC Question

Can the same Microsoft Foundry Hosted Agent container be:

- successfully deployed from ACR;
- successfully deployed directly from JFrog Artifactory;
- deployed without manually copying the JFrog image into ACR;
- authenticated using managed identity and OIDC token exchange instead of embedded registry credentials;
- published and deployed through CLI, API, SDK, or CI/CD automation?

---

## 3. Success Criteria

The POC is successful when all the following are demonstrated:

1. The existing ZIP-based Hosted Agent is converted into a reusable container image.
2. The container runs successfully outside Foundry.
3. The image is pushed to ACR.
4. Foundry deploys the image from ACR.
5. The ACR-backed Hosted Agent reaches `Active`.
6. The ACR-backed agent passes a Responses API smoke test.
7. The identical container image is pushed to JFrog Artifactory.
8. The Foundry project managed identity participates in an OIDC token-exchange flow.
9. JFrog maps the Foundry identity to repository-scoped, pull-only access.
10. A Foundry project registry connection references the JFrog registry and token endpoint.
11. Foundry deploys the Hosted Agent directly from JFrog.
12. The JFrog-backed agent reaches `Active`.
13. The JFrog-backed agent passes the same Responses API smoke test.
14. ACR is not involved in the direct JFrog deployment path.
15. Image publication and Hosted Agent deployment can be repeated through CLI or SDK.
16. No JFrog username, password, or long-lived access token is embedded in agent code, `azure.yaml`, or pipeline source.

---

## 4. Target Architecture

```text
Existing ZIP Hosted Agent POC
              |
              v
      Reusable agent container
              |
              +-------------------------------+
              |                               |
              v                               v
 Azure Container Registry              JFrog Artifactory
              |                               ^
              | Managed identity/RBAC         |
              |                               | OIDC token exchange
              |                               | and short-lived credential
              v                               |
   Foundry Hosted Agent             Foundry project managed identity
              |                               |
              |                               v
              |                     Foundry registry connection
              |                               |
              +---------------+---------------+
                              |
                              v
                  Same Hosted Agent validation
                  and Responses API smoke test
                              |
                              v
                      CLI/API automation
```

---

## 5. Why Validate ACR First?

The ACR deployment isolates the shared dependencies before introducing JFrog-specific configuration.

If the agent works from ACR, the POC has already established that:

- the Docker image is valid;
- the container starts correctly;
- the Hosted Agent definition is valid;
- the Responses protocol is implemented correctly;
- runtime environment variables are available;
- the selected CPU and memory configuration works;
- Foundry can deploy the container;
- the agent can reach its model and other required services;
- the smoke-test invocation is valid.

If ACR succeeds but JFrog fails, troubleshooting can focus on:

- JFrog OIDC configuration;
- token audience;
- identity mapping;
- repository permissions;
- registry connection configuration;
- DNS and network connectivity to JFrog;
- the JFrog token-exchange endpoint.

Do not advance to the JFrog deployment until the ACR-backed agent reaches `Active` and passes the smoke test.

---

## 6. POC Scope

### Included

- Reuse of the existing ZIP-based agent
- Containerization
- Local container validation
- ACR image publication
- ACR-to-Foundry Hosted Agent deployment
- JFrog image publication
- JFrog OIDC identity configuration
- JFrog-to-Foundry direct deployment
- Azure Developer CLI deployment
- Python SDK deployment
- Deployment status polling
- Responses API smoke testing
- Initial CI/CD design
- Negative testing
- Evidence collection for the J&J discussion

### Initially excluded

- J&J-specific approval implementation
- J&J production security configuration
- J&J Snyk integration
- Production-grade private networking
- Production monitoring and alerting
- Multi-region deployment
- Production rollback automation
- Automatic JFrog administrator configuration
- Full enterprise CI/CD integration

The external POC should establish a known-good technical pattern. The pattern can then be mapped to J&J governance, networking, identity, scanning, and publishing requirements.

---

## 7. Assumptions

- The existing ZIP-based Hosted Agent deployment works.
- The agent can be containerized.
- The agent implements the Responses protocol required by the Hosted Agent definition.
- A non-J&J Azure subscription is available.
- A Foundry account and project are available.
- The required Foundry managed identity exists.
- The user has permission to deploy Hosted Agent versions.
- An ACR can be created or reused.
- A JFrog development, evaluation, or trial environment is available.
- The JFrog environment exposes the OIDC integration and identity-mapping capabilities required by the external-registry pattern.
- The user can create a Microsoft Entra application.
- A JFrog administrator can configure OIDC trust, identity mappings, groups, and repository permissions.

> Important: Before investing significant time in the JFrog configuration, verify that the selected JFrog environment exposes the required OIDC integration, identity-mapping, and token-exchange capabilities.

---

## 8. Required Tooling

Install and authenticate the following:

- Docker-compatible container tooling
- Azure CLI
- Azure Developer CLI
- Azure Developer CLI Foundry extensions
- Bash-compatible shell
- Python 3.10 or later
- Azure AI Projects SDK
- Azure Identity SDK

Install the Python dependencies:

```bash
python -m pip install azure-ai-projects azure-identity
```

Optional but recommended:

- JFrog CLI
- `jq`
- Git
- GitHub Actions or Azure Pipelines
- A container vulnerability scanner

Verify the primary tools:

```bash
az version
azd version
docker version
python --version
```

---

## 9. Environment Variables

Create a local environment file that is excluded from Git.

```bash
# Azure subscription
export AZURE_SUBSCRIPTION_ID="<subscription-id>"
export AZURE_RESOURCE_GROUP="<resource-group>"
export AZURE_LOCATION="<azure-region>"

# Foundry
export FOUNDRY_ACCOUNT_NAME="<foundry-account-name>"
export FOUNDRY_PROJECT_NAME="<foundry-project-name>"

export FOUNDRY_PROJECT_ENDPOINT="https://<account-name>.services.ai.azure.com/api/projects/<project-name>"

export FOUNDRY_PROJECT_ID="/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.CognitiveServices/accounts/<account-name>/projects/<project-name>"

# Agent
export AGENT_NAME="registry-hosted-agent"
export LOCAL_IMAGE_NAME="foundry-hosted-agent"
export IMAGE_TAG="0.1.0"

# Runtime
export AZURE_AI_MODEL_DEPLOYMENT_NAME="<model-deployment-name>"

# ACR
export ACR_NAME="<globally-unique-acr-name>"
export ACR_IMAGE_NAME="foundry-hosted-agent"
export ACR_IMAGE_TAG="${IMAGE_TAG}"

# JFrog
export JFROG_REGISTRY_HOST="<registry-host>"
export JFROG_REPOSITORY="<repository-name>"
export JFROG_IMAGE_NAME="foundry-hosted-agent"
export JFROG_IMAGE_TAG="${IMAGE_TAG}"
export JFROG_OIDC_PROVIDER_NAME="<provider-name>"
export JFROG_TOKEN_ENDPOINT="/access/api/v1/oidc/token"

# Foundry external-registry connection
export REGISTRY_CONNECTION_NAME="private-registry"
```

Derived values:

```bash
export ACR_LOGIN_SERVER="${ACR_NAME}.azurecr.io"

export ACR_FULL_IMAGE_NAME="${ACR_LOGIN_SERVER}/${ACR_IMAGE_NAME}:${ACR_IMAGE_TAG}"

export JFROG_FULL_IMAGE_NAME="${JFROG_REGISTRY_HOST}/${JFROG_REPOSITORY}/${JFROG_IMAGE_NAME}:${JFROG_IMAGE_TAG}"
```

Do not commit:

- local environment files;
- passwords;
- JFrog access tokens;
- Docker authentication files;
- Azure tokens;
- pipeline secrets;
- token-exchange responses.

---

# Phase 1: Reuse and Containerize the Existing Agent

## 10. Reuse the Existing ZIP-Based Agent

Use the simplest validated agent from the existing ZIP POC.

Avoid adding unrelated tools or dependencies until both registry paths work.

The containerized agent should preserve:

- the same agent behavior;
- the same model deployment;
- the same environment variables;
- the same Responses protocol;
- the same smoke-test prompt;
- the same expected result.

This makes the comparison between ZIP, ACR, and JFrog meaningful.

---

## 11. Container Requirements

The container must:

- start without interactive input;
- implement the required Responses protocol;
- listen on the interface and port expected by the Hosted Agent runtime;
- obtain runtime settings from environment variables;
- avoid embedded Azure or registry credentials;
- output startup and request failures to standard output or standard error;
- terminate with a nonzero code when startup fails;
- use deterministic image tags;
- avoid unnecessary packages and development tools.

Build the image:

```bash
docker build \
  -t "${LOCAL_IMAGE_NAME}:${IMAGE_TAG}" \
  .
```

List the image:

```bash
docker image inspect "${LOCAL_IMAGE_NAME}:${IMAGE_TAG}"
```

Run the container locally using the validation procedure appropriate for the agent implementation.

Do not continue until the local container starts successfully.

---

## 12. Establish a Common Smoke Test

Use the same smoke test for:

- the existing ZIP deployment;
- the ACR-backed deployment;
- the JFrog-backed deployment.

Example:

```text
Respond with:
1. A short deployment confirmation.
2. The configured agent name.
3. The registry path used for this deployment, if exposed through configuration.
```

The expected result should validate functional execution, not merely return a static health response.

Record:

- request time;
- agent name;
- agent version;
- registry source;
- response status;
- response content;
- any correlation or request identifier.

---

# Phase 2: Establish the ACR-to-Foundry Baseline

## 13. Create or Select an ACR

For a simple public-network POC, create or reuse an ACR in the test subscription.

Example:

```bash
az login

az account set \
  --subscription "${AZURE_SUBSCRIPTION_ID}"

az acr create \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --name "${ACR_NAME}" \
  --sku Basic
```

Retrieve the login server:

```bash
export ACR_LOGIN_SERVER=$(az acr show \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --name "${ACR_NAME}" \
  --query loginServer \
  --output tsv)

export ACR_FULL_IMAGE_NAME="${ACR_LOGIN_SERVER}/${ACR_IMAGE_NAME}:${ACR_IMAGE_TAG}"

echo "${ACR_FULL_IMAGE_NAME}"
```

> The Basic SKU and public-network approach are suitable only as a minimal isolated POC example. Use the organization-approved SKU, network controls, private endpoints, and policy configuration for governed environments.

---

## 14. Push the Image to ACR

Authenticate:

```bash
az acr login \
  --name "${ACR_NAME}"
```

Tag the local image:

```bash
docker tag \
  "${LOCAL_IMAGE_NAME}:${IMAGE_TAG}" \
  "${ACR_FULL_IMAGE_NAME}"
```

Push the image:

```bash
docker push "${ACR_FULL_IMAGE_NAME}"
```

Verify that the repository exists:

```bash
az acr repository show \
  --name "${ACR_NAME}" \
  --repository "${ACR_IMAGE_NAME}"
```

Retrieve the image digest:

```bash
export ACR_IMAGE_DIGEST=$(az acr repository show \
  --name "${ACR_NAME}" \
  --image "${ACR_IMAGE_NAME}:${ACR_IMAGE_TAG}" \
  --query digest \
  --output tsv)

echo "${ACR_IMAGE_DIGEST}"
```

Retain the tag and digest as deployment evidence.

---

## 15. Configure ACR Pull Access

Identify the managed identity required by the current Hosted Agent ACR deployment pattern.

Grant only the required pull permission at the narrowest practical scope.

Record:

- identity name;
- identity object ID;
- identity resource ID;
- ACR resource ID;
- assigned role;
- assignment scope;
- registry network mode.

Do not assume that a successful local `docker push` proves that Foundry can pull the image. Publisher access and runtime pull access are separate concerns.

---

## 16. Initialize the ACR-Backed Hosted Agent

Authenticate Azure Developer CLI:

```bash
azd auth login
```

Initialize the agent:

```bash
azd ai agent init --no-prompt \
  --agent-name "${AGENT_NAME}-acr" \
  --image "${ACR_FULL_IMAGE_NAME}" \
  --project-id "${FOUNDRY_PROJECT_ID}"
```

Review the generated `azure.yaml`.

Confirm that:

- the agent kind is `hosted`;
- the image references ACR;
- the Foundry project is correct;
- the Responses protocol is declared;
- runtime environment variables are supplied safely;
- no secrets are embedded.

---

## 17. Deploy the Agent from ACR

Deploy:

```bash
azd deploy --no-prompt
```

Check status:

```bash
azd ai agent show
```

Wait until the Hosted Agent version reaches `Active`.

Invoke the agent:

```bash
azd ai agent invoke \
  "Respond with a short ACR deployment confirmation."
```

---

## 18. ACR Baseline Exit Criteria

Do not advance to JFrog until all criteria are satisfied:

- The image exists in ACR.
- The tag and digest are known.
- Foundry pulls the image from ACR.
- The agent container starts successfully.
- The Hosted Agent version reaches `Active`.
- The Responses API smoke test succeeds.
- The same agent implementation used in the ZIP POC is preserved.
- Runtime variables and resource settings are documented.
- Publisher permissions and runtime pull permissions are separated.
- Deployment evidence is retained.

If this phase fails, investigate the shared container and Foundry configuration before introducing JFrog.

---

# Phase 3: Publish the Identical Container to JFrog

## 19. Create or Obtain a JFrog Repository

Create or obtain a Docker or OCI repository in a JFrog development, evaluation, or trial environment.

Record:

- JFrog platform URL;
- Docker registry hostname;
- repository key;
- repository type;
- image naming convention;
- publisher identity;
- runtime pull identity design;
- OIDC feature availability.

The POC should separate two identities:

### Publisher identity

Used by a developer or CI/CD pipeline to push images.

Required permissions:

- repository read;
- repository write;
- metadata publication if required by the pipeline.

### Runtime pull identity

The Foundry project managed identity mapped through OIDC.

Required permissions:

- repository read;
- image pull only;
- no image push;
- no repository administration.

---

## 20. Push the Image to JFrog

Authenticate using a temporary development publisher credential appropriate for the selected JFrog tenant.

Do not use the publisher credential in the Foundry registry connection.

Tag the exact same local image:

```bash
docker tag \
  "${LOCAL_IMAGE_NAME}:${IMAGE_TAG}" \
  "${JFROG_FULL_IMAGE_NAME}"
```

Push the image:

```bash
docker push "${JFROG_FULL_IMAGE_NAME}"
```

Validate an independent pull:

```bash
docker image rm "${JFROG_FULL_IMAGE_NAME}" || true

docker pull "${JFROG_FULL_IMAGE_NAME}"
```

Capture the JFrog image digest if exposed by the selected CLI or API.

Compare it with the local and ACR image digests where possible to demonstrate that the same image content was tested.

---

## 21. JFrog Publication Exit Criteria

- The JFrog repository exists.
- The image is stored in JFrog.
- The full image reference is known.
- An independent pull succeeds.
- The publisher identity is documented.
- The future Foundry runtime identity is limited to pull-only access.
- OIDC and identity-mapping capabilities are confirmed.
- No ACR copy is required for the direct JFrog phase.

---

# Phase 4: Configure JFrog Identity Trust

## 22. Create the Entra Application Used as Token Audience

Create an Entra application whose application ID is used as the audience in the token-exchange flow.

```bash
export ENTRA_APPLICATION_ID=$(az ad app create \
  --display-name "Foundry-Registry-Agent-POC" \
  --query appId \
  --output tsv)

echo "ENTRA_APPLICATION_ID=${ENTRA_APPLICATION_ID}"
```

The application ID is configuration, not a secret.

Do not create or store a client secret unless another separate requirement explicitly needs it.

---

## 23. Get the Foundry Project Managed Identity

```bash
export FOUNDRY_PROJECT_PRINCIPAL_ID=$(az resource show \
  --ids "${FOUNDRY_PROJECT_ID}" \
  --api-version 2025-06-01 \
  --query identity.principalId \
  --output tsv)

echo "FOUNDRY_PROJECT_PRINCIPAL_ID=${FOUNDRY_PROJECT_PRINCIPAL_ID}"
```

If this value is empty:

1. Confirm that `FOUNDRY_PROJECT_ID` points to the project resource.
2. Confirm that the project has the expected managed identity.
3. Verify the API version supported by the environment.
4. Do not continue until the intended identity is known.

---

## 24. Configure JFrog OIDC Trust

The JFrog administrator must configure the JFrog environment to:

1. Create an OIDC integration.
2. Configure the Entra application ID as the expected audience.
3. Create an identity mapping for the Foundry project managed identity.
4. Map that identity to a JFrog group or permission target.
5. Grant read-only access to the POC repository.
6. Deny or omit image-push permission.
7. Confirm the OIDC provider name.
8. Confirm the token-exchange endpoint.
9. Confirm the registry HTTPS origin.

The expected token endpoint for the documented JFrog pattern is:

```text
/access/api/v1/oidc/token
```

### Provide to the JFrog administrator

- Foundry project Azure resource ID
- Foundry project managed identity object or principal ID
- Entra application ID used as audience
- Required repository
- Required action: image pull
- Required permission: read-only

### Obtain from the JFrog administrator

- Registry HTTPS origin
- OIDC provider name
- Confirmed audience
- Token-exchange endpoint
- Repository key
- Image naming convention
- Identity-mapping confirmation
- Permission-target or group name
- Relevant network requirements

Do not place token responses or administrative credentials in the source repository.

---

## 25. JFrog Identity Exit Criteria

- The Entra application exists.
- Its application ID is recorded.
- The Foundry project principal ID is known.
- JFrog trusts the intended audience.
- JFrog recognizes the intended Foundry identity.
- The mapped identity has read-only access to the correct repository.
- The OIDC provider name is known.
- The registry target is known.
- The token-exchange endpoint is confirmed.
- No static pull credential is required by Foundry.

---

# Phase 5: Deploy the Same Hosted Agent Directly from JFrog

## 26. Create the Foundry Registry Connection

Create the connection in the same Foundry project that will host the agent.

```bash
azd ai connection create "${REGISTRY_CONNECTION_NAME}" \
  --project-endpoint "${FOUNDRY_PROJECT_ENDPOINT}" \
  --kind custom-keys \
  --target "https://${JFROG_REGISTRY_HOST}" \
  --auth-type custom-keys \
  --custom-key "audience=${ENTRA_APPLICATION_ID}" \
  --custom-key "tokenEndpoint=${JFROG_TOKEN_ENDPOINT}" \
  --custom-key "body.provider_name=${JFROG_OIDC_PROVIDER_NAME}" \
  --metadata "type=registry_connection" \
  --metadata "mode=oauth_token_exchange"
```

Verify the connection:

```bash
azd ai connection show "${REGISTRY_CONNECTION_NAME}" \
  --project-endpoint "${FOUNDRY_PROJECT_ENDPOINT}"
```

Confirm that:

- the connection exists in the intended Foundry project;
- the target is the JFrog HTTPS origin;
- the metadata type is `registry_connection`;
- the mode is `oauth_token_exchange`;
- the provider name matches the JFrog OIDC configuration;
- the audience matches exactly;
- no registry password is included.

---

## 27. Initialize the JFrog-Backed Hosted Agent

```bash
azd ai agent init --no-prompt \
  --agent-name "${AGENT_NAME}-jfrog" \
  --image "${JFROG_FULL_IMAGE_NAME}" \
  --project-id "${FOUNDRY_PROJECT_ID}" \
  --registry-connection "${REGISTRY_CONNECTION_NAME}"
```

Review the generated `azure.yaml`.

The relevant structure should be equivalent to:

```yaml
services:
  existing-project:
    host: azure.ai.project
    endpoint: ${FOUNDRY_PROJECT_ENDPOINT}

  jfrog-hosted-agent:
    host: azure.ai.agent
    uses:
      - existing-project
    kind: hosted
    name: registry-hosted-agent-jfrog
    image: "<registry-host>/<repository>/foundry-hosted-agent:0.1.0"
    docker:
      imagePassthrough: true
    registryConnectionId: private-registry
    protocols:
      - protocol: responses
        version: "2.0.0"
```

Validate:

- `kind` is `hosted`;
- `image` points to JFrog;
- the image tag matches the ACR baseline;
- `docker.imagePassthrough` is `true`;
- `registryConnectionId` matches the Foundry connection;
- the project is in the `uses` list;
- the existing registry connection is not incorrectly added as a service