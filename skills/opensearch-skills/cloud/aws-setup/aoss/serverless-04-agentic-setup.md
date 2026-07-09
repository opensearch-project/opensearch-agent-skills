# Amazon OpenSearch Serverless NextGen — Configure Flow Agent Search

This guide configures flow agent agentic search on a serverless nextgen collection.

Only **flow agents** are supported on serverless nextgen. Flow agents are stateless — each query is independently planned and executed via `QueryPlanningTool`. For conversational agents (stateful with RAG + memory), use a managed domain instead.

## Prerequisites

- Completed [aoss-nextgen-provisioning/SKILL.md](aoss-nextgen-provisioning/SKILL.md) (collection active)
- Completed [serverless-02-deploy-search.md](serverless-02-deploy-search.md) (index created with data)
- Agent resource permissions included in data access policy (configured during provisioning)

## State Input

From `.opensearch-deploy-state.json`:
- `resource_endpoint`: collection endpoint URL
- `index_name`: target index
- `aws_region`: for Bedrock endpoint
- `principal_arn`: for IAM role

## Step 1: Create IAM Role for Bedrock Access

### Production trust policy:

```bash
aws iam create-role --role-name opensearch-bedrock-agent-role --assume-role-policy-document '{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": [
      "opensearchservice.amazonaws.com",
      "aoss.amazonaws.com",
      "global.prod.oasis.aoss.aws.internal"
    ]},
    "Action": "sts:AssumeRole"
  }]
}'
```

### Attach Bedrock invoke permissions:

```bash
aws iam put-role-policy --role-name opensearch-bedrock-agent-role \
  --policy-name BedrockClaudeInvokePolicy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/*",
        "arn:aws:bedrock:*:*:inference-profile/*"
      ]
    }]
  }'
```

Update state: `"iam_role_arn": "<role-arn>"`

## Step 2: Register Model with Inline Connector

Register the model with an embedded connector in a single call. The connector's `request_body` must use the agent framework's template variables (`user_prompt`, `_chat_history`, `_interactions`, `tool_configs`).

```
POST <collection-endpoint>/_plugins/_ml/models/_register?deploy=true
{
  "name": "agentic search base model",
  "function_name": "remote",
  "connector": {
    "name": "Bedrock Claude Connector",
    "description": "Amazon Bedrock connector for Claude",
    "version": 1,
    "protocol": "aws_sigv4",
    "parameters": {
      "region": "<aws_region>",
      "service_name": "bedrock",
      "model": "us.anthropic.claude-sonnet-4-20250514-v1:0"
    },
    "credential": {
      "roleArn": "<iam_role_arn>"
    },
    "actions": [{
      "action_type": "predict",
      "method": "POST",
      "url": "https://bedrock-runtime.${parameters.region}.amazonaws.com/model/${parameters.model}/converse",
      "headers": { "content-type": "application/json" },
      "request_body": "{ \"system\": [{\"text\": \"${parameters.system_prompt}\"}], \"messages\": [${parameters._chat_history:-}{\"role\":\"user\",\"content\":[{\"text\":\"${parameters.user_prompt}\"}]}${parameters._interactions:-}]${parameters.tool_configs:-} }"
    }]
  }
}
```

Wait for model state to reach `DEPLOYED`, then update state: `"model_id": "<model_id>"`

## Step 3: Create Flow Agent

```
POST <collection-endpoint>/_plugins/_ml/agents/_register
{
  "name": "Agentic Search Agent",
  "type": "flow",
  "description": "Flow agent for natural language search with query planning",
  "tools": [{
    "type": "QueryPlanningTool",
    "description": "A general tool to answer any question",
    "parameters": {
      "model_id": "<model_id>",
      "response_filter": "$.output.message.content[0].text"
    }
  }]
}
```

Notes:
- `type` must be `flow` — conversational agents are not supported on serverless nextgen
- Only `QueryPlanningTool` is needed — it handles index mapping introspection internally
- `response_filter` tells the tool how to extract the LLM response from the Bedrock Converse output
- No `llm` block needed — the model is referenced inside the tool's `parameters`

Update state: `"agent_id": "<agent_id>"`

## Step 4: Create Agentic Search Pipeline

```
PUT <collection-endpoint>/_search/pipeline/agentic-search-pipeline
{
  "request_processors": [{
    "agentic_query_translator": { "agent_id": "<agent_id>" }
  }],
  "response_processors": [{
    "agentic_context": {
      "agent_steps_summary": true,
      "dsl_query": true
    }
  }]
}
```

The `response_processors` with `agentic_context` adds metadata to the response:
- `dsl_query`: the generated OpenSearch DSL
- `agent_steps_summary`: reasoning steps the agent took

Update state: `"search_pipeline_name": "agentic-search-pipeline"`

### Critical: Data Access Policy for Pipeline Search

The IAM role used in the model connector's `credential.roleArn` **MUST** be added as a principal in the data access policy with access to all four ResourceTypes (`collection`, `index`, `model`, `agent`).

When the search pipeline invokes the agent internally, AOSS uses the connector's IAM role to:
1. Read index mappings (requires `index` access)
2. Execute the generated DSL query (requires `index` access)
3. Invoke the model (requires `model` access)
4. Execute the agent (requires `agent` access)

Without this, pipeline-based `agentic` queries will fail with `403 Forbidden` even though direct `_execute` API calls work (because direct calls use the caller's identity).

Required data access policy (set during provisioning or update now):

```bash
aws opensearchserverless create-access-policy --type data \
  --name <collection-name>-access-policy \
  --policy '[{
    "Rules": [
      {"Resource": ["collection/<collection-name>"], "Permission": ["aoss:*"], "ResourceType": "collection"},
      {"Resource": ["index/<collection-name>/*"], "Permission": ["aoss:*"], "ResourceType": "index"},
      {"Resource": ["model/<collection-name>/*"], "Permission": ["aoss:*"], "ResourceType": "model"},
      {"Resource": ["agent/<collection-name>/*"], "Permission": ["aoss:*"], "ResourceType": "agent"}
    ],
    "Principal": ["<caller-principal-arn>", "<iam_role_arn>"]
  }]' --region <aws_region>
```

Both the caller's principal (for manual API calls) and the connector IAM role (for pipeline-based invocation) must be listed as principals.

## Step 5: Test Agentic Search

```
GET <collection-endpoint>/<index-name>/_search?search_pipeline=agentic-search-pipeline
{
  "query": {
    "agentic": {
      "query_text": "Find documents about machine learning"
    }
  }
}
```

Expected response includes search hits plus `ext` metadata:
```json
{
  "hits": { "total": {"value": N}, "hits": [...] },
  "ext": {
    "dsl_query": "{\"size\":10,\"query\":{\"multi_match\":{...}}}"
  }
}
```

The agent will:
1. Analyze the natural language question
2. Examine the index mapping via `QueryPlanningTool`
3. Generate appropriate OpenSearch DSL
4. Execute the query and return results

## State Output

Final `.opensearch-deploy-state.json`:
```json
{
  "step_completed": "agentic-setup",
  "collection_generation": "NEXTGEN",
  "iam_role_arn": "<role-arn>",
  "model_id": "<model-id>",
  "agent_id": "<agent-id>",
  "search_pipeline_name": "agentic-search-pipeline"
}
```

## Connect Search UI to AWS Endpoint

After agentic setup is complete:

```
Call connect_search_ui_to_endpoint(
  endpoint="<collection-endpoint>",
  port=443,
  use_ssl=true,
  index_name="<index-name>"
)
```

## Provide Access Information

Give the user:
- Collection endpoint URL
- Collection ARN
- Agent ID for direct agent invocation
- Sample agentic search queries
- Search Builder UI URL (already connected to AWS endpoint)
