# ML Commons

ML Commons is the machine learning framework for OpenSearch. It provides APIs to register, deploy, and invoke ML models — both locally hosted models and remote models accessed via connectors (e.g., Amazon Bedrock, OpenAI, Cohere, custom endpoints).

## Key Concepts

- **Model** — A machine learning model registered in OpenSearch. Can be a local model (uploaded to the cluster) or a remote model (accessed via a connector).
- **Model group** — An access-control container for models. Models in the same group share visibility and permission settings.
- **Connector** — A configuration that defines how to call an external ML service (endpoint URL, request/response mapping, credential handling). Used for remote model inference.
- **Deploy / Undeploy** — Local models must be deployed to ML nodes before use. Remote models are deployed by registering a connector.
- **Predict** — The inference API. Send input data to a deployed model and get predictions back.
- **Agent** — An LLM-powered entity that can use tools to accomplish tasks. Agents support conversational memory and can chain multiple tool calls.
- **Tool** — A capability available to an agent (e.g., `VectorDBTool`, `SearchIndexTool`, `CATIndexTool`, `PPLTool`). Tools are registered and configured via the agent API.
- **Memory** — Conversational memory that persists across agent interactions. Stored in a system index.
- **Model access control** — Controls who can access models and model groups using backend roles.

## Common Use Cases

- Deploying text embedding models for semantic search
- Connecting to Amazon Bedrock, OpenAI, or Cohere for LLM inference
- Building agentic RAG workflows with agents and tools
- Running local ML models (e.g., sparse encoding, cross-encoder reranking)
- Setting up conversational search with memory

## Tutorials

- [Configuring agentic search](https://docs.opensearch.org/latest/vector-search/ai-search/building-agentic-search-flows/) — End-to-end agentic search setup (links to flow agents, memory, search templates, MCP, and more)
- [Agents and tools tutorial](https://docs.opensearch.org/latest/ml-commons-plugin/agents-tools/agents-tools-tutorial/) — Register agents, configure tools, and run agent executions
- [Conversational search with Claude on Bedrock](https://docs.opensearch.org/latest/tutorials/gen-ai/rag/conversational-search-claude-bedrock/) — RAG setup with Bedrock (links to OpenAI, Cohere, and other provider variants)
- [Gen AI tutorials index](https://docs.opensearch.org/latest/tutorials/gen-ai/index/) — All generative AI tutorials (RAG, chatbots, agents, model controls)

## Official Documentation

- [ML Commons overview](https://docs.opensearch.org/latest/ml-commons-plugin/index/)
- [Model access control](https://docs.opensearch.org/latest/ml-commons-plugin/model-access-control/)
- [Connectors](https://docs.opensearch.org/latest/ml-commons-plugin/remote-models/connectors/)
- [Agents and tools](https://docs.opensearch.org/latest/ml-commons-plugin/agents-tools/index/)
- [Conversational memory](https://docs.opensearch.org/latest/ml-commons-plugin/conversational-memory/)
- [Supported models](https://docs.opensearch.org/latest/ml-commons-plugin/integrating-ml-models/)
- [API reference](https://docs.opensearch.org/latest/ml-commons-plugin/api/index/)
- [Cluster settings](https://docs.opensearch.org/latest/ml-commons-plugin/cluster-settings/)
