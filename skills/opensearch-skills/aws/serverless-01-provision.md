# Amazon OpenSearch Serverless — Step 1: Provision Collection

This guide covers creating and configuring an OpenSearch Serverless collection. Follow it after `prepare_aws_deployment()` returns `deployment_target: "serverless"`.

## Prerequisites

Before starting:
1. Read `.opensearch-deploy-state.json` for current deployment state
2. Confirm AWS credentials are valid: `aws sts get-caller-identity` (via AWS API MCP)
3. Verify required MCP servers are connected: `awslabs.aws-api-mcp-server`, `opensearch-mcp-server`
4. Save the AWS account ID and principal ARN to the state file

## State Input

From `.opensearch-deploy-state.json`:
- `deployment_target`: "serverless"
- `search_strategy`: determines collection type

## Step 1: Create Encryption Policy

Create an encryption policy (required before collection creation):

```json
POST /opensearchserverless/CreateSecurityPolicy
{
  "name": "<collection-name>-encryption",
  "type": "encryption",
  "policy": "{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/<collection-name>\"]}],\"AWSOwnedKey\":true}"
}
```

## Step 2: Create Network Policy

```json
POST /opensearchserverless/CreateSecurityPolicy
{
  "name": "<collection-name>-network",
  "type": "network",
  "policy": "[{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/<collection-name>\"]},{\"ResourceType\":\"dashboard\",\"Resource\":[\"collection/<collection-name>\"]}],\"AllowFromPublic\":true}]"
}
```

For production, replace `AllowFromPublic` with VPC endpoint IDs.

## Step 3: Create Data Access Policy

Create a data access policy with permissions for index, collection, and ML resources:

```json
POST /opensearchserverless/CreateAccessPolicy
{
  "name": "<collection-name>-data",
  "type": "data",
  "policy": "[{\"Rules\":[{\"ResourceType\":\"index\",\"Resource\":[\"index/<collection-name>/*\"],\"Permission\":[\"aoss:CreateIndex\",\"aoss:DescribeIndex\",\"aoss:UpdateIndex\",\"aoss:DeleteIndex\",\"aoss:ReadDocument\",\"aoss:WriteDocument\"]},{\"ResourceType\":\"collection\",\"Resource\":[\"collection/<collection-name>\"],\"Permission\":[\"aoss:CreateCollectionItems\",\"aoss:DescribeCollectionItems\"]},{\"ResourceType\":\"model\",\"Resource\":[\"model/<collection-name>/*\"],\"Permission\":[\"aoss:CreateMLResource\"]}],\"Principal\":[\"<principal_arn>\"]}]"
}
```

Replace `<principal_arn>` with the value from the state file.

## Step 4: Create Collection

Choose collection type based on search strategy:
- **VECTORSEARCH**: For dense vector search (semantic search with dense embeddings)
- **SEARCH**: For all other strategies (BM25, neural sparse, hybrid with neural sparse)

Neural sparse (automatic semantic enrichment) requires SEARCH type, not VECTORSEARCH.

```json
POST /opensearchserverless/CreateCollection
{
  "name": "<collection-name>",
  "type": "SEARCH or VECTORSEARCH",
  "description": "Search application deployed from local OpenSearch"
}
```

## Step 5: Wait for Collection Active

Poll until status is "ACTIVE" (typically 1-3 minutes):

```json
POST /opensearchserverless/BatchGetCollection
{
  "names": ["<collection-name>"]
}
```

## State Output

Update `.opensearch-deploy-state.json`:
```json
{
  "step_completed": "provision-collection",
  "aws_account_id": "<from sts get-caller-identity>",
  "aws_region": "<configured region>",
  "principal_arn": "<from sts get-caller-identity>",
  "resource_name": "<collection-name>",
  "resource_endpoint": "<collection-endpoint-url>"
}
```

## Next Step

Proceed to [Serverless Deploy Search](serverless-02-deploy-search.md).
