# Amazon OpenSearch Service Domain — Step 1: Provision Domain

This guide covers creating and configuring an Amazon OpenSearch Service Domain (managed cluster). Follow it after `prepare_aws_deployment()` returns `deployment_target: "domain"`.

## Prerequisites

Before starting:
1. Read `.opensearch-deploy-state.json` for current deployment state
2. Confirm AWS credentials are valid: `aws sts get-caller-identity` (via AWS API MCP)
3. Verify required MCP servers are connected: `awslabs.aws-api-mcp-server`, `opensearch-mcp-server`
4. Save the AWS account ID and principal ARN to the state file

## State Input

From `.opensearch-deploy-state.json`:
- `deployment_target`: "domain"
- `search_strategy`: "agentic" or other

## Step 1: Get Latest OpenSearch Version

Before creating the domain, fetch the latest available OpenSearch version:

```
aws opensearch list-versions
```

This returns all supported versions. Pick the latest `OpenSearch_X.Y` version (highest major, then minor). Ignore `Elasticsearch_*` versions.

> For agentic search, confirm the selected version is 3.3 or higher.

## Step 2: Create Domain

Use the AWS API MCP server with the version from Step 1:

```
aws opensearch create-domain
  --domain-name <domain-name>
  --engine-version <latest-version-from-step-1>
  --cluster-config InstanceType=t3.medium.search,InstanceCount=1
  --ebs-options EBSEnabled=true,VolumeType=gp3,VolumeSize=100
  --node-to-node-encryption-options Enabled=true
  --encryption-at-rest-options Enabled=true
  --domain-endpoint-options EnforceHTTPS=true
```

For production, use larger instances (r6g.large.search, 3+ data nodes, 3 dedicated leaders).

## Step 3: Enable Fine-Grained Access Control

```
aws opensearch update-domain-config
  --domain-name <domain-name>
  --advanced-security-options Enabled=true,InternalUserDatabaseEnabled=true,MasterUserOptions={MasterUserName=admin,MasterUserPassword=<strong-password>}
```

Set up:
- Master user credentials
- Role-based access control

## Step 4: Configure Network Access

**Public access (development):**
- Set IP-based access policies
- Use fine-grained access control

**VPC access (production):**
- Deploy within VPC, configure security groups

## Step 5: Wait for Domain Active

Poll until domain is active (typically 10-15 minutes):

```
aws opensearch describe-domain --domain-name <domain-name>
```

Wait for:
- `Processing`: false
- `DomainStatus.Endpoint`: available

## State Output

Update `.opensearch-deploy-state.json`:
```json
{
  "step_completed": "provision-domain",
  "aws_account_id": "<from sts get-caller-identity>",
  "aws_region": "<configured region>",
  "principal_arn": "<from sts get-caller-identity>",
  "resource_name": "<domain-name>",
  "resource_endpoint": "<domain-endpoint-url>"
}
```

## Next Step

Proceed to [Domain Deploy Search](domain-02-deploy-search.md).
