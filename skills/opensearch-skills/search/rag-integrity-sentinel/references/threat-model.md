# Threat Model and Containment Boundaries

## Protected System

The protected system is a retrieval-augmented application whose model receives
content from OpenSearch. The sentinel protects the boundary between indexed
content and model context. It does not claim to secure the model, browser,
ingestion source, or application by itself.

## Adversary Goals

An attacker or compromised source may try to:

- Override the application's system or developer instructions
- Cause a tool call, command execution, or secret disclosure
- Conceal instructions with Unicode controls, comments, or encoded text
- Alter content after provenance metadata or a checksum was recorded
- Duplicate or paraphrase poisoned content until it dominates top-k retrieval
- Remove provenance so reviewers cannot identify the ingest source

## Trust Boundaries

Treat these as independent trust domains:

1. Source repository, site, ticket system, or file share
2. Ingestion and chunking pipeline
3. OpenSearch index and search pipeline
4. Retriever or application server
5. Model and tools
6. Human reviewer

A trusted source URI does not prove trusted content. A clean document does not
prove a trustworthy ingestion pipeline.

## Evidence Strength

From strongest to weakest:

1. Stored checksum mismatch against normalized analyzed content
2. Reviewed instruction-like content plus verified unexpected provenance
3. Multiple deterministic concealment and coercion signals
4. Cross-source exact duplicates with inconsistent ingest history
5. Semantic-neighbor similarity to a confirmed poisoned document
6. Missing provenance alone

Similarity is never proof. Legitimate templates, documentation, and security
training material often contain the same words as attacks.

## Containment Boundaries

The default investigation must be read-only. A proposed containment operation
must identify:

- Exact index and document IDs
- Expected current hashes
- Destination quarantine index or exclusion mechanism
- Required privileges
- Rollback operation
- Search queries used for before/after verification
- Expected impact on recall

Do not use `delete_by_query` or a broad wildcard mutation. Prefer exact IDs and
optimistic concurrency controls. Never overwrite the only copy of evidence.

## False-Positive Controls

- Compare flagged chunks with neighboring chunks from the same source.
- Check whether the text is quoted security documentation rather than a live
  instruction.
- Compare source URI, owner, checksum, and ingest timestamp.
- Examine downstream prompt construction: quoted or delimited content can
  reduce exploitability but does not remove the need to investigate.
- Reproduce retrieval with the application's actual query and search pipeline.

## Data Handling

Reports contain hashes, identifiers, bounded snippets, and scores. They should
not contain credentials, full confidential documents, or raw embedding vectors.
Store reports under the same access controls as the source corpus.
