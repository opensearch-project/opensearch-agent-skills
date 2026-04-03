# OpenSearch Agentic Search Guide

---

## 1. Overview

Agentic search is an AI-powered retrieval method introduced in OpenSearch 3.2 that handles multi-step natural language questions and provides answer synthesis. It is a **standalone retrieval approach** designed for complex reasoning scenarios where users expect synthesized answers rather than ranked documents.

**Architecture:**
```
User Multi-Step Question
         ↓
   Agentic Search Agent (LLM-powered reasoning & orchestration)
         ↓
   Query Planning & Decomposition
         ↓
   Document Retrieval (agent selects optimal method internally)
         ↓
   Answer Synthesis
         ↓
   Synthesized Answer (not just ranked hits)
```

**How it works:**
1. User asks a multi-step natural language question (e.g., "What are the top-rated products under $100 and why are they popular?")
2. LLM-powered agent analyzes the question and breaks it down into steps
3. Agent determines the best retrieval strategy and generates appropriate queries
4. Agent retrieves relevant documents using its internal retrieval capabilities
5. Agent synthesizes results into a coherent, reasoned answer

**Key Distinction:** Agentic search is a complete, standalone retrieval method. Unlike BM25, Dense Vector, or Hybrid search which return ranked documents, agentic search returns synthesized answers. Choose agentic search when users need multi-step reasoning and answer synthesis, not when they just need ranked search results.

---

## 2. Agent Types

Agentic search supports two agent types optimized for different use cases.

### 2.1 Conversational Agents

**Overview:** Full-featured agents with multi-tool support and conversation memory.

| Aspect | Details |
|--------|---------|
| **Tools** | Multiple (QueryPlanningTool + others) |
| **Memory** | Conversation history with memory IDs |
| **Reasoning** | Detailed step-by-step traces |
| **Latency** | Higher (multiple LLM calls) |
| **Cost** | Higher (more API calls) |
| **Use Case** | Complex multi-turn conversations, tool orchestration |

### 2.2 Flow Agents

**Overview:** Streamlined agents focused solely on query planning.

| Aspect | Details |
|--------|---------|
| **Tools** | Single (QueryPlanningTool only) |
| **Memory** | None |
| **Reasoning** | Simplified |
| **Latency** | Lower (fewer LLM calls) |
| **Cost** | Lower |
| **Use Case** | Simple stateless queries, known indexes |

---

## 3. Accuracy Characteristics

| Aspect | Rating | Notes |
|--------|--------|-------|
| **Simple Queries** | 5/5 | Excellent for straightforward keyword/filter queries |
| **Complex Logic** | 4/5 | Good for multi-condition boolean queries |
| **Ambiguity Handling** | 4/5 | LLM can interpret ambiguous intent |
| **Consistency** | 3/5 | May generate different DSL for same question |
| **Domain Knowledge** | 3/5 | Limited to index schema; no external domain knowledge |

**Strengths:**
- Handles natural language variations well
- Can infer user intent from context
- Generates syntactically correct DSL
- Adapts to index schema automatically

**Weaknesses:**
- May misinterpret ambiguous questions
- No guarantee of optimal query structure
- Can be inconsistent across similar queries
- Result quality depends on underlying retrieval method

---

## 4. Latency & Cost Profile

### 4.1 Latency Composition

```
Total Latency = LLM Inference + DSL Execution
```

| Component | Typical Range | Notes |
|-----------|---------------|-------|
| **LLM Inference** | 200-2000ms | Dominates total latency |
| **DSL Execution** | 10-500ms | Depends on query type (BM25/neural/hybrid) |
| **Total** | 210-2500ms | 10-100x slower than direct DSL |

**Latency Factors:**
- Model size (GPT-4 vs GPT-3.5)
- Query complexity
- Agent type (flow faster than conversational)
- Number of tools invoked

### 4.2 Cost Profile

| Resource | Cost Level | Details |
|----------|------------|---------|
| **LLM API Calls** | 4/5 (High) | Per-query inference costs |
| **Storage** | 2/5 (Low-Medium) | Conversation memory (if enabled) |
| **Compute** | 2/5 (Low-Medium) | Agent orchestration overhead |
| **Underlying Search** | Varies | Depends on generated query (BM25/neural/hybrid) |

**Cost Optimization:**
- Use flow agents when memory not needed
- Cache common query patterns
- Use smaller/faster LLM models
- Limit max_iteration parameter
- Disable conversation memory if not required

---

## 5. When to Use Agentic Search

**Use Agentic Search (standalone retrieval method) when:**
- Users ask multi-step questions requiring reasoning and answer synthesis
  - Example: "What are the top-rated products under $30k and why are they popular?"
  - Example: "Show me budget laptops with good reviews and explain the trade-offs"
- Questions need context from multiple queries to form a complete answer
- Users expect ChatGPT-like synthesized answers, not just ranked documents
- Complex analytical questions requiring query decomposition and reasoning
- Conversational search experiences where synthesis is more valuable than document ranking

**Use Other Methods (BM25/Dense/Sparse/Hybrid) when:**
- Users just need ranked documents (not synthesized answers)
- Simple keyword searches or semantic similarity lookups
- Latency-critical applications (agentic adds 200-2000ms overhead)
- Cost-sensitive deployments (LLM API costs per query)
- High-frequency queries where query templates work well
- Query structure is known and predictable

---

## 6. Setup Requirements

### 6.1 Prerequisites

| Requirement | Details |
|-------------|---------|
| **OpenSearch Version** | 3.2+ |
| **LLM Provider** | Amazon Bedrock (Claude 4 Sonnet recommended), OpenAI, or self-hosted |
| **Permissions** | IAM role with Bedrock InvokeModel permissions (if using Bedrock) |
| **Plugins** | ML Commons Plugin, Agent Framework (built-in 3.2+) |

### 6.2 Setup Components

Agentic search requires three main components:

1. **LLM Model Registration**: Register the LLM (e.g., Bedrock Claude) as a remote model in OpenSearch
2. **Agent Creation**: Create a conversational or flow agent with query planning tools
3. **Search Pipeline**: Attach an agentic query translator processor to your search pipeline

**Agent Tools Configuration:**
- `ListIndexTool`: Discovers available indices
- `IndexMappingTool`: Retrieves index schema
- `WebSearchTool`: Optional external search (e.g., DuckDuckGo)
- `QueryPlanningTool`: Core tool that generates OpenSearch DSL

### 6.3 Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query_text` | String | Yes | Natural language question |
| `query_fields` | Array | No | Fields to consider (inferred if omitted) |
| `memory_id` | String | No | Conversation memory ID (conversational agents only) |

**Note:** Actual setup is handled by implementation tools. The knowledge base focuses on decision criteria.

---

## 7. Advanced Features

### 7.1 Conversation Memory

Conversational agents support multi-turn conversations with context retention:

- First query establishes a conversation session
- Response includes a `memory_id` 
- Subsequent queries reference the `memory_id` to maintain context
- Enables follow-up questions like "What about blue ones?" after asking about red cars

### 7.2 Automatic Retrieval Method Selection

When configured with an embedding model, agents can automatically choose the optimal retrieval method:

| Query Type | Selected Method |
|------------|-----------------|
| Keyword queries | BM25 |
| Conceptual queries | Dense/sparse vector |
| Mixed queries | Hybrid |

This eliminates the need for manual query routing logic.

---

## 8. Deployment Considerations

### 8.1 Model Options

| Option | Pros | Cons |
|--------|------|------|
| **Amazon Bedrock** | AWS integration, Claude 4 Sonnet, IAM auth | AWS-only, requires IAM role |
| **OpenAI API** | Easy setup, SOTA models | External dependency, per-call cost |
| **Self-hosted** | Full control | Infrastructure overhead |

**Recommended:** Amazon Bedrock with Claude 4 Sonnet for Amazon OpenSearch Service deployments.

### 8.2 Scaling

- **LLM API rate limits:** Plan for concurrent queries
- **Conversation memory:** Monitor index growth
- **Cost:** Linear with query volume

### 8.3 Security

- Secure API key storage
- Be mindful of PII in natural language queries
- Understand LLM provider data policies
- Implement conversation memory retention policies

---

## 9. Limitations

1. **Latency:** 200-2000ms overhead per query
2. **Cost:** LLM API calls per query
3. **Consistency:** Same question may generate different DSL
4. **Answer synthesis quality:** Depends on LLM capabilities and retrieved documents
5. **Complex DSL:** May struggle with advanced DSL features
6. **Not a replacement for traditional search:** Users expecting simple ranked results may prefer direct retrieval

---

*Document Version: 1.0*
*Last Updated: January 2025*
*Applicable OpenSearch Versions: 3.2+*
*Based on: https://docs.opensearch.org/latest/vector-search/ai-search/agentic-search/*
