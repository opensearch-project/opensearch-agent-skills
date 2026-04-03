# Amazon OpenSearch Service Domain — Step 3: Configure Agentic Search

This guide configures conversational agents with QueryPlanningTool for natural language search. Only follow this for agentic search strategy.

Agentic search requires OpenSearch 2.11+ and uses Bedrock Claude as the reasoning model.

## State Input

From `.opensearch-deploy-state.json`:
- `resource_endpoint`: domain endpoint URL
- `index_name`: target index
- `aws_region`: for Bedrock endpoint
- `aws_account_id`: for IAM role ARN

## Step 1: Create IAM Role for Bedrock Access

```json
POST /iam/CreateRole
{
  "RoleName": "opensearch-bedrock-agent-role",
  "AssumeRolePolicyDocument": {
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": { "Service": "opensearchservice.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }]
  }
}
```

Attach Bedrock invoke permissions:

```json
POST /iam/PutRolePolicy
{
  "RoleName": "opensearch-bedrock-agent-role",
  "PolicyName": "BedrockClaudeInvokePolicy",
  "PolicyDocument": {
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-5-sonnet-*"
    }]
  }
}
```

Update state: `"iam_role_arn": "<role-arn>"`

## Step 2: Map ML Role (if fine-grained access control enabled)

1. Log in to OpenSearch Dashboards
2. Navigate to Security > Roles > `ml_full_access`
3. Mapped users > Manage mapping
4. Add IAM role ARN under Backend roles: `arn:aws:iam::<aws_account_id>:role/opensearch-bedrock-agent-role`
5. Click Map

## Step 3: Create Bedrock Claude Connector

```
POST <domain-endpoint>/_plugins/_ml/connectors/_create
{
  "name": "Amazon Bedrock Claude 3.5 Sonnet",
  "description": "Connector for Bedrock Claude for agentic search",
  "version": 1,
  "protocol": "aws_sigv4",
  "credential": { "roleArn": "<iam_role_arn>" },
  "parameters": {
    "region": "<aws_region>",
    "service_name": "bedrock",
    "model": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "system_prompt": "You are a helpful assistant that plans and executes search queries.",
    "temperature": 0.0,
    "top_p": 0.9,
    "max_tokens": 2000
  },
  "actions": [{
    "action_type": "predict",
    "method": "POST",
    "headers": { "content-type": "application/json" },
    "url": "https://bedrock-runtime.${parameters.region}.amazonaws.com/model/${parameters.model}/converse",
    "request_body": "{ \"system\": [{\"text\": \"${parameters.system_prompt}\"}], \"messages\": ${parameters.messages}, \"inferenceConfig\": {\"temperature\": ${parameters.temperature}, \"topP\": ${parameters.top_p}, \"maxTokens\": ${parameters.max_tokens}} }"
  }]
}
```

Update state: `"connector_id": "<connector_id>"`

## Step 4: Register and Deploy Model

```
POST <domain-endpoint>/_plugins/_ml/models/_register?deploy=true
{
  "name": "Bedrock Claude 3.5 Sonnet for Agentic Search",
  "function_name": "remote",
  "description": "Claude model for query planning and reasoning",
  "connector_id": "<connector_id>"
}
```

Test the model:
```
POST <domain-endpoint>/_plugins/_ml/models/<model-id>/_predict
{
  "parameters": {
    "messages": [{ "role": "user", "content": [{ "text": "hello" }] }]
  }
}
```

Verify the response contains generated text.

Update state: `"model_id": "<model_id>"`

## Step 5: Create Conversational Agent

```
POST <domain-endpoint>/_plugins/_ml/agents/_register
{
  "name": "Agentic Search Agent",
  "type": "conversational",
  "description": "Agent for natural language search with query planning",
  "llm": {
    "model_id": "<model_id>",
    "parameters": { "max_iteration": 15 }
  },
  "memory": { "type": "conversation_index" },
  "parameters": { "_llm_interface": "bedrock/converse" },
  "tools": [{ "type": "QueryPlanningTool" }],
  "app_type": "os_chat"
}
```

Update state: `"agent_id": "<agent_id>"`

## Step 6: Create Agentic Search Pipeline

```
PUT <domain-endpoint>/_search/pipeline/agentic-search-pipeline
{
  "request_processors": [{
    "agentic_query_translator": { "agent_id": "<agent_id>" }
  }]
}
```

Update state: `"search_pipeline_name": "agentic-search-pipeline"`

## Step 7: Test Agentic Search

```
GET <domain-endpoint>/<index-name>/_search?search_pipeline=agentic-search-pipeline
{
  "query": {
    "agentic": {
      "query_text": "Find all documents about machine learning published in the last year",
      "query_fields": ["title", "content", "publish_date"]
    }
  }
}
```

The agent will:
1. Analyze the natural language question
2. Examine the index mapping
3. Generate appropriate OpenSearch DSL query
4. Execute the query and return results

## State Output

Final `.opensearch-deploy-state.json`:
```json
{
  "step_completed": "agentic-setup",
  "iam_role_arn": "<role-arn>",
  "connector_id": "<connector-id>",
  "model_id": "<model-id>",
  "agent_id": "<agent-id>",
  "search_pipeline_name": "agentic-search-pipeline"
}
```

## Connect Search UI to AWS Endpoint

After agentic setup is complete, switch the local Search Builder UI to query the AWS domain:

```
Call connect_search_ui_to_endpoint(
  endpoint="<domain-endpoint>",
  port=443,
  use_ssl=true,
  username="<master-user>",
  password="<master-password>",
  index_name="<index-name>"
)
```

The UI header badge will change from "Local" to "AWS Cloud" with a green connection indicator.

## Provide Access Information

Give the user:
- Domain endpoint URL
- Domain ARN
- OpenSearch Dashboards URL
- Master user credentials (securely)
- Sample agentic search queries
- Search Builder UI URL (already connected to AWS endpoint)
- Agent ID for direct agent invocation
