# Aiven for OpenSearch — Step 1: Provision Service

This guide covers creating and configuring an Aiven for OpenSearch service (a managed cluster). Follow it after the user chooses Aiven as the deployment target.

All Aiven calls go through the **`aiven-mcp`** MCP server. The Aiven Console equivalents are shown in comments so users who prefer the UI can follow along.

## Prerequisites

Before starting:
1. Read `.opensearch-deploy-state.json` for current deployment state
2. Confirm `aiven-mcp` was connected with full access and `allow_secrets=true` (a connection flag that lets `aiven_service_connection_info` return the real credentials instead of `[REDACTED]`). If the connection is read-only, tell the user to reconnect with full access.

## Step 1: Select the Project

```
aiven_project_list
```

Present the available projects and ask the user which one to deploy into. Save it as `project`.

Update state: `"project": "<project>"`

## Step 2: List Plans

```
aiven_service_type_plans   # service_type="opensearch", project="<project>"
```

Each plan entry describes the tier (e.g. `hobbyist`, `startup-4`, `business-8`, `premium-16`), node count, CPU/memory, and disk. Some entries include `regions` / `clouds` listing where the plan can run.

Present the plans to the user (name, size, approximate price if available) and ask them to choose. **Do not pick a plan yourself.**

Save it as `plan`. Update state: `"plan": "<plan>"`.

## Step 3: Choose the Cloud Region

Prefer the `regions` / `clouds` shown on the chosen plan. If those are unclear, list all clouds available to the project:

```
aiven_list_project_clouds   # project="<project>"
```

Aiven cloud names look like `aws-eu-west-1`, `google-europe-west1`, `azure-westeurope`, `do-fra1`, `upcloud-de-fra`. Present valid names and ask the user to choose. **Never invent a region.**

Save it as `cloud`. Update state: `"cloud": "<cloud>"`.

## Step 4: Create the Service

Choose a service name (lowercase letters, numbers, dashes) and create the OpenSearch service:

```
aiven_service_create
  project      = "<project>"
  service_name = "<service-name>"
  service_type = "opensearch"
  plan         = "<plan>"
  cloud        = "<cloud>"
  # Optional user_config, e.g. OpenSearch major version:
  # user_config = { "opensearch_version": "2" }
```

> Aiven Console equivalent: **Services → Create service → OpenSearch**, then pick cloud, region, and plan.

The response includes `service_name`, `service_type`, `state` (usually `BUILDING` right after create), `plan`, and `cloud_name`.

Tell the user the service is provisioning (typically a few minutes) and ask them to tell you when to check status. **Do not poll in a loop.**

Update state: `"service_name": "<service-name>"`, `"step_completed": "create-service"`.

## Step 5: Wait for RUNNING, then Read Endpoint + Credentials

When the user asks you to check, call once:

```
aiven_service_get   # project="<project>", service_name="<service-name>"
```

If `state` is not `RUNNING`, report the state and stop — ask the user to tell you when to check again. **Do not loop.**

If `state` is `RUNNING`, read the endpoint and credentials with `aiven_service_connection_info` (this is the tool that returns the real host, port, user, and password — `aiven_service_get` keeps them `[REDACTED]`):

```
aiven_service_connection_info   # project="<project>", service_name="<service-name>"
```

- **Host / port / user** — from the response (default admin user is `avnadmin`).
- **Password** — from the response; requires `allow_secrets=true`, otherwise it comes back `[REDACTED]`.
- **Dashboards URL** — the `opensearch_dashboards` endpoint if present.

> Aiven Console equivalent: the service's **Connection information** tab.

**How the credential reaches the MCP:** Aiven generates the password; you read it from `aiven_service_connection_info` and wire it into `opensearch-mcp-server`'s `OPENSEARCH_PASSWORD` env in Step 2. The agent never invents it.

Store the pieces you'll need for Step 2. Do not echo the password into the chat beyond what's needed to configure the MCP server.

Update state:
```json
{
  "step_completed": "provision-service",
  "resource_name": "<service-name>",
  "resource_host": "<host>",
  "resource_port": "<port>",
  "resource_endpoint": "https://<host>:<port>",
  "os_username": "<user>",
  "dashboards_url": "<opensearch_dashboards component url, if present>"
}
```

Do **not** write the password into the state file. Keep it only in the `opensearch-mcp-server` env configured in Step 2.

## Next Step

Proceed to [Deploy Search Configuration](aiven-02-deploy-search.md).
