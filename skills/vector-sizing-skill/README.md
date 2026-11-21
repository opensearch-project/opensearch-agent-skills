# vector-sizing-skill

An OpenSearch agent skill that estimates cluster sizing for vector/k-NN workloads across **AWS, Azure, and GCP**. It calculates HNSW memory requirements, recommends instance types and node counts, determines shard strategy, and provides monthly cost estimates — all from within your IDE.

## Problem

Sizing an OpenSearch cluster for vector workloads requires understanding:
- HNSW graph memory footprint (must fit in RAM for performant search)
- Instance type selection across cloud providers and generations
- Quantization trade-offs (FP32 vs FP16 vs SQ8 vs PQ)
- Shard strategy at scale (30M vectors/shard guideline)
- Multi-AZ node distribution
- Managed vs self-managed cost/operational trade-offs

This is currently a manual spreadsheet exercise that takes hours, is error-prone, and rarely considers multiple clouds. This skill makes it a 30-second conversation with your agent.

## Demo Video

▶ [Watch the demo on YouTube](https://youtu.be/NtvjgsRtJMU)

## Demo

```
> Size an OpenSearch cluster for 100M vectors, 1536 dimensions, compare across clouds

Agent runs: python3 scripts/vector_sizing.py cross-cloud \
  --vectors 100000000 --dimensions 1536

Result:
  CROSS-CLOUD COMPARISON: 100,000,000 vectors x 1536 dims
  Memory needed: 629.4 GB per replica set

  Cloud                            Instance                 Nodes   Monthly
  AWS OpenSearch Service (Managed) r7g.16xlarge.search      6       $35,180
  AWS EC2 (Self-Managed)           x2idn.24xlarge           2       $17,529
  Azure VMs (Self-Managed)         Standard_E96s_v5         4       $21,164
  GCP VMs (Self-Managed)           n2-highmem-80            4       $16,586

  Note: Managed service includes patching, backups, monitoring.
  Self-managed is cheaper but requires operational overhead.
```

## Installation

### Option 1: One-line install (recommended)

```bash
npx skills add opensearch-project/opensearch-agent-skills@vector-sizing-skill --full-depth
```

This auto-detects your agent (Claude Code, Cursor, Kiro, etc.) and configures it.

### Option 2: Install for a specific agent

```bash
# Claude Code
npx skills add opensearch-project/opensearch-agent-skills@vector-sizing-skill --full-depth -a claude-code

# Cursor
npx skills add opensearch-project/opensearch-agent-skills@vector-sizing-skill --full-depth -a cursor

# All detected agents
npx skills add opensearch-project/opensearch-agent-skills@vector-sizing-skill --full-depth --all
```

### Option 3: Manual install (Claude Code)

```bash
# From your project root
mkdir -p .claude/skills/vector-sizing
cp -r vector-sizing-skill/* .claude/skills/vector-sizing/
```

Claude Code auto-discovers skills in `.claude/skills/` on the next session.

### Verify installation

Once installed, ask your agent:
```
> vector sizing for 10M vectors with 768 dimensions
```

If the skill is active, the agent will run the calculator and present sizing recommendations.

## Usage

The skill activates on prompts like:
- "Size a cluster for 50M vectors with 768 dimensions"
- "How many nodes do I need for vector search on Azure?"
- "Compare quantization options for my k-NN workload"
- "What's cheaper — AWS managed or self-managed on GCP?"
- "Cross-cloud comparison for 294M vectors at 1536 dimensions"

## Commands

```bash
# Full sizing estimate (single cloud)
python3 scripts/vector_sizing.py calculate \
  --vectors 294000000 \
  --dimensions 1536 \
  --engine faiss \
  --quantization fp32 \
  --replicas 1 \
  --multi-az 2 \
  --cloud aws-ec2

# Multi-cloud side-by-side comparison
python3 scripts/vector_sizing.py calculate \
  --vectors 100000000 \
  --dimensions 1536 \
  --cloud aws-ec2,azure,gcp

# Cross-cloud comparison (best option from each provider)
python3 scripts/vector_sizing.py cross-cloud \
  --vectors 294000000 \
  --dimensions 1536

# Compare quantization options on a specific cloud
python3 scripts/vector_sizing.py compare \
  --vectors 294000000 \
  --dimensions 1536 \
  --cloud azure

# Show available instance types for a cloud
python3 scripts/vector_sizing.py instances --cloud gcp
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--vectors` | Number of vectors to index | Required |
| `--dimensions` | Vector dimensions | Required |
| `--engine` | k-NN engine (faiss, nmslib, lucene) | faiss |
| `--quantization` | Precision (fp32, fp16, sq8, pq) | fp32 |
| `--replicas` | Number of replicas | 1 |
| `--doc-size-bytes` | Non-vector document size | 1024 |
| `--qps` | Target queries per second | 0 (memory-only) |
| `--multi-az` | AZ count (0, 2, 3) | 2 |
| `--cloud` | Cloud provider(s), comma-separated | aws-ec2 |
| `--output` | Output format (human, json) | human |

### Available Clouds

| Value | Description |
|-------|-------------|
| `aws-opensearch` | AWS OpenSearch Service (managed, includes `.search` suffixed types) |
| `aws-ec2` | AWS EC2 self-managed (r7g, r8g, r7i, x2idn families) |
| `azure` | Azure VMs (Standard_E*s_v5, E*as_v5, M-series) |
| `gcp` | GCP VMs (n2-highmem, n2d-highmem, m2-megamem/ultramem) |

## Architecture

```
vector-sizing-skill/
├── SKILL.md                    # Agent entry point (workflow + rules)
├── scripts/
│   └── vector_sizing.py        # Core calculator (Python, zero deps)
├── references/
│   ├── engines.md              # FAISS vs nmslib vs Lucene comparison
│   ├── quantization.md         # Quantization trade-offs and decision tree
│   ├── instance-catalog.md     # Instance specs and pricing
│   ├── pricing.json            # Dated pricing snapshot + provider source URLs
│   └── knn-mappings.md         # Index mapping templates
├── tests/
│   └── test_vector_sizing.py   # 37 tests covering all clouds
├── LICENSE                     # Apache 2.0
└── README.md
```

## How It Works

1. **Agent reads SKILL.md** → understands workflow and rules
2. **Gathers inputs** from user (vectors, dimensions, engine, cloud, etc.)
3. **Runs calculator** → produces structured sizing estimate per cloud
4. **Presents options** → economy / balanced / performance tiers
5. **Offers refinements** → quantization, cross-cloud comparison, mapping generation

The calculator uses zero external dependencies — pure Python with transparent formulas the user can verify.

## Key Design Decisions

- **Cloud-agnostic**: Supports AWS (managed + EC2), Azure, and GCP out of the box
- **No proprietary dependencies**: Pure Python, no API calls, no paid services
- **Vendor-neutral**: Runs OpenSearch on any distribution (self-managed, Docker, K8s, managed)
- **Transparent math**: Every calculation shown with formula so users can verify
- **Multiple tiers**: Always presents options, never a single "answer"
- **Conservative defaults**: 75% max memory utilization, 20% storage headroom
- **JSON output**: Agents can parse results programmatically for downstream tasks
- **Cross-cloud insights**: Highlights managed vs self-managed trade-offs
- **Pricing that stays current**: prices are not hardcoded in code — they load from a
  dated `references/pricing.json` (with provider source URLs), the output always shows
  the snapshot date, and the agent can fetch live prices from the web and pass them via
  `--prices-file`. This keeps the tool dependency-free while avoiding stale cost figures.

## Compatibility

- Python 3.9+ (standard library only — no external packages, no `pip install`)
- Runs with plain `python3`; `uv run python` also works if you prefer, but nothing to resolve since there are no dependencies
- Any OpenSearch distribution (self-managed, Docker, Kubernetes, managed service)
- Works with: Claude Code, Cursor, Kiro, GitHub Copilot, Windsurf, Gemini CLI, OpenAI Codex

## License

Apache 2.0
