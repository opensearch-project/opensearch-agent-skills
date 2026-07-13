# Aiven for OpenSearch — Step 1: Provision Service

This guide covers creating and configuring an Aiven for OpenSearch service (a managed cluster). Follow it after the user chooses Aiven as the deployment target.

All Aiven calls go through the **`aiven-mcp`** MCP server. The Aiven Console equivalents are shown in comments so users who prefer the UI can follow along.

## Prerequisites

Before starting:
1. Read `.opensearch-deploy-state.json` for current deployment state
2. Verify the `aiven-mcp` server is connected and reachable — call `aiven_project_list`. If it fails with an auth error, the user needs to (re)connect with a valid Aiven token.
3. Confirm `aiven-mcp` was connected with full access and `allow_secrets=true`. If `aiven_service_create` is not available, the connection is read-only — tell the user to reconnect with full access (or at minimum `write_allowlist=aiven_service_create`). If `aiven_service_get` returns `[REDACTED]` credentials in Step 5, they need `allow_secrets=true`.

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

Once `state == "RUNNING"`, extract the connection details from the response:

- **Endpoint** — from `service_uri` (an `https://<user>:<password>@<host>:<port>` URI) and/or the `components` array (`host`, `port`, `component: "opensearch"`). The Dashboards URL is the `opensearch_dashboards` component if present.
- **Credentials** — from `service_uri_params` (`host`, `port`, `user`, `password`) or the `users` array. The default admin user is typically `avnadmin`.

> These values are only returned in full because `aiven-mcp` was connected with `allow_secrets=true`. Without it, `service_uri` and `password` come back as `[REDACTED]` — if you see that, tell the user to reconnect with `allow_secrets=true`.
>
> Aiven Console equivalent: the service's **Connection information** tab (Service URI, Host, Port, User, Password).

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
