# Flow Framework

Flow Framework automates the provisioning of OpenSearch resources by defining workflows as templates. A workflow is a sequence of steps (create index, register model, create pipeline, etc.) that are executed in dependency order. This is especially useful for setting up complex ML and search configurations.

## Key Concepts

- **Workflow** — A directed acyclic graph (DAG) of provisioning steps. Defined as a JSON template with nodes and edges.
- **Template** — The JSON definition of a workflow. Contains metadata, a list of nodes (steps), and edges (dependencies).
- **Node** — A single provisioning step (e.g., `create_index`, `register_model_group`, `register_remote_model`, `deploy_model`, `create_search_pipeline`).
- **Edge** — A dependency between two nodes. Ensures steps execute in the correct order.
- **Provision** — Execute the workflow. Each node runs in dependency order, and outputs from earlier nodes can be referenced by later nodes using substitution syntax.
- **Use case templates** — Pre-built templates for common patterns (semantic search, conversational search, hybrid search). Available via the search workflow API.
- **Deprovision** — Tear down resources created by a workflow in reverse order.
- **Substitution** — Reference outputs from earlier steps using `${{node_id.output_key}}` syntax.

## Common Use Cases

- Automating semantic search setup (register model, create ingest pipeline, create index)
- Provisioning agentic RAG workflows end-to-end
- Repeatable infrastructure-as-code for OpenSearch ML configurations
- Using pre-built use case templates for quick starts

## Tutorials

- [Workflow tutorial](https://docs.opensearch.org/latest/automating-configurations/workflow-tutorial/) — Step-by-step workflow creation with use case templates
- [Building AI search flows](https://docs.opensearch.org/latest/vector-search/ai-search/building-flows/) — Create search workflows (links to agentic search flows, workflow builder UI, and more)
- [AI search flows tutorials](https://docs.opensearch.org/latest/tutorials/gen-ai/ai-search-flows/index/) — End-to-end AI search flow examples

## Official Documentation

- [Flow Framework overview](https://docs.opensearch.org/latest/automating-configurations/index/)
- [Workflow templates](https://docs.opensearch.org/latest/automating-configurations/workflow-templates/)
- [Workflow steps](https://docs.opensearch.org/latest/automating-configurations/workflow-steps/)
- [Workflow access control](https://docs.opensearch.org/latest/automating-configurations/workflow-access-control/)
- [Workflow security](https://docs.opensearch.org/latest/automating-configurations/workflow-security/)
- [Workflow settings](https://docs.opensearch.org/latest/automating-configurations/workflow-settings/)
- [API reference](https://docs.opensearch.org/latest/automating-configurations/api/index/)
