---
name: aos-observability-setup
description: >
  Provision an Amazon OpenSearch Service managed domain tuned for observability by
  setting engine mode OPTIMIZED and use case OBSERVABILITY. Same flow as the standard
  managed-domain provisioning, plus those two parameters at create time. Use when the
  user wants an observability, logs, or traces domain on AWS, or wants to set
  engine_mode / use_case on a managed domain. Activate on terms like engine mode, use
  case, OPTIMIZED, OBSERVABILITY, observability domain, log analytics domain, trace
  analytics domain, or2, or aws opensearch create-domain engine-mode.
compatibility: >
  Requires AWS credentials and the awslabs.aws-api-mcp-server and opensearch-mcp-server
  MCP servers (same as aws-setup). Expects a deployment state file
  (.opensearch-deploy-state.json) when run inside the aws-setup flow.
metadata:
  author: opensearch-project
  version: "1.0"
---

# Amazon OpenSearch Service Domain — Observability-Optimised Provisioning

This guide provisions a managed Amazon OpenSearch Service domain tuned for observability. It is
the standard managed-domain flow ([aos/domain-01-provision.md](../aos/domain-01-provision.md))
with two additions in Step 2: `--engine-mode OPTIMIZED` and `--use-case OBSERVABILITY`. Follow it
when `prepare_aws_deployment()` returns `deployment_target: "domain"` and the workload is logs/traces.

## Prerequisites

Before starting:
1. Read `.opensearch-deploy-state.json` for current deployment state
2. Confirm AWS credentials are valid: `aws sts get-caller-identity` (via AWS API MCP)
3. Verify required MCP servers are connected: `awslabs.aws-api-mcp-server`, `opensearch-mcp-server`
4. Save the AWS account ID and principal ARN to the state file

## Observability Parameters

Two create-time parameters tune the domain for observability:

| Parameter | Flag / property | Value | Valid values |
|---|---|---|---|
| Engine mode | `--engine-mode` / `EngineMode` | `OPTIMIZED` | `GENERAL`, `OPTIMIZED` |
| Use case | `--use-case` / `UseCase` | `OBSERVABILITY` | `SEARCH`, `VECTOR`, `OBSERVABILITY`, `MIXED` |

Both are set **only at create time** — `engine_mode` is immutable, and `use_case` is fixed for
OPTIMIZED domains. Decide up front and confirm with the user before creating.

Parameter names and allowed values are per the OpenSearch Service **CreateDomain** API
(`EngineMode`: `GENERAL | OPTIMIZED`; `UseCase`: `SEARCH | VECTOR | OBSERVABILITY | MIXED`). Confirm
with `aws opensearch create-domain help` or the API reference (see References) before relying on them —
if a name or value has changed, the CLI, CloudFormation, and CDK forms all fail at create time.

## State Input

From `.opensearch-deploy-state.json`:
- `deployment_target`: "domain"
- `use_case`: "observability" → engine mode `OPTIMIZED`, use case `OBSERVABILITY`

## Step 1: Get Latest OpenSearch Version

```
aws opensearch list-versions
```

Pick the latest `OpenSearch_X.Y` version (highest major, then minor). Ignore `Elasticsearch_*`.
Observability-optimised domains require a recent engine — prefer the latest available version.

## Step 2: Create Domain (observability-optimised)

Use the AWS API MCP server with the version from Step 1. This is the standard provisioning
command plus the two observability flags:

```
aws opensearch create-domain
  --domain-name <domain-name>
  --engine-version <latest-version-from-step-1>
  --engine-mode OPTIMIZED
  --use-case OBSERVABILITY
  --cluster-config InstanceType=or2.2xlarge.search,InstanceCount=1
  --ebs-options EBSEnabled=true,VolumeType=gp3,VolumeSize=100
  --node-to-node-encryption-options Enabled=true
  --encryption-at-rest-options Enabled=true
  --domain-endpoint-options EnforceHTTPS=true
```

If the API rejects a combination, read the validation message and adjust the instance type or
engine version, then retry — never silently drop `--engine-mode` / `--use-case`. Confirm supported
instance types with `aws opensearch list-instance-type-details`. For production, use larger `or2`
instances with 3+ data nodes and 3 dedicated leaders.

## Step 3: Enable Fine-Grained Access Control

Prefer an **IAM master user** (`MasterUserARN`) — no password to store or leak:

```
aws opensearch update-domain-config
  --domain-name <domain-name>
  --advanced-security-options Enabled=true,MasterUserOptions={MasterUserARN=<iam-principal-arn>}
```

If an internal user database is required instead, **never pass the password as a literal CLI
argument** — it leaks into shell history, `ps` output, and the state file. Source it securely
(AWS Secrets Manager or a no-echo prompt) and apply it via a restricted-permission JSON file, then
delete the file:

```
read -rs OS_MASTER_PW            # no-echo prompt (or fetch from AWS Secrets Manager)
umask 077
cat > fgac.json <<EOF
{ "DomainName": "<domain-name>",
  "AdvancedSecurityOptions": { "Enabled": true, "InternalUserDatabaseEnabled": true,
    "MasterUserOptions": { "MasterUserName": "admin", "MasterUserPassword": "$OS_MASTER_PW" } } }
EOF
aws opensearch update-domain-config --cli-input-json file://fgac.json
shred -u fgac.json 2>/dev/null || rm -f fgac.json
```

Never write the master password to `.opensearch-deploy-state.json`.

## Step 4: Configure Network Access

- **Public access (development):** IP-based access policies with fine-grained access control.
- **VPC access (production):** deploy within a VPC and configure security groups.

## Step 5: Wait for Domain Active

Poll until the domain is active (typically 10–15 minutes):

```
aws opensearch describe-domain --domain-name <domain-name>
```

Wait for `Processing: false` and an available `DomainStatus.Endpoint`. Confirm the parameters took:

```
aws opensearch describe-domain-config --domain-name <domain-name> \
  --query 'DomainConfig.{EngineMode:EngineMode.Options,UseCase:UseCase.Options}'
```

Expect `OPTIMIZED` / `OBSERVABILITY`.

## State Output

Update `.opensearch-deploy-state.json`:
```json
{
  "step_completed": "provision-domain",
  "aws_account_id": "<from sts get-caller-identity>",
  "aws_region": "<configured region>",
  "principal_arn": "<from sts get-caller-identity>",
  "resource_name": "<domain-name>",
  "resource_endpoint": "<domain-endpoint-url>",
  "engine_mode": "OPTIMIZED",
  "use_case": "OBSERVABILITY"
}
```

## Next Step

Proceed to [Domain Deploy Search](../aos/domain-02-deploy-search.md).

## Provisioning via IaC (alternative to the CLI/MCP flow)

Same domain, same two parameters. CloudFormation carries `EngineMode` / `UseCase` natively;
CDK and Terraform set them by targeting the same `AWS::OpenSearchService::Domain` resource type:

- **CloudFormation** (`AWS::OpenSearchService::Domain`): set `EngineMode: OPTIMIZED` and `UseCase: OBSERVABILITY`.
- **CDK**: use the L1 `opensearchservice.CfnDomain` with `engineMode: 'OPTIMIZED'`, `useCase: 'OBSERVABILITY'`; on an existing high-level `Domain`, `(domain.node.defaultChild as CfnDomain).addPropertyOverride('EngineMode','OPTIMIZED')` and likewise for `UseCase`.
- **Terraform**: use `aws_cloudcontrolapi_resource` with `type_name = "AWS::OpenSearchService::Domain"` and `EngineMode` / `UseCase` in `desired_state`. This provisions the CloudFormation resource type through the AWS Cloud Control API — the same resource type CloudFormation and CDK use — so both parameters are honored. Confirm the type is Cloud Control–enabled with `aws cloudformation describe-type --type RESOURCE --type-name AWS::OpenSearchService::Domain --query ProvisioningType`.

## Usage Attribution

Requests run via `awslabs.aws-api-mcp-server`, which is configured with
`"AWS_SDK_UA_APP_ID": "opensearch-agent-skills"` in its `env`. If you run raw shell `aws` commands
instead, prefix each with `AWS_SDK_UA_APP_ID=opensearch-agent-skills` (scope per-command; never
`export` globally).

## References

- CreateDomain API — `EngineMode` / `UseCase` parameters and valid values: https://docs.aws.amazon.com/opensearch-service/latest/APIReference/API_CreateDomain.html
- CloudFormation `AWS::OpenSearchService::Domain` — `EngineMode` / `UseCase` properties: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-opensearchservice-domain.html
