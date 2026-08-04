# Benchmark Methodology

## Purpose

The bundled benchmark is a deterministic regression test for the sentinel's
document-level signal coverage. It answers a narrow question: does this version
continue to distinguish the included clean fixtures from the included
adversarial fixtures at the documented severity threshold?

It is not an independent security evaluation, a measurement of real-world
attack prevalence, or evidence that every unseen attack will be detected.

## Corpus

`assets/benchmark-corpus.jsonl` contains 20 labeled documents:

- 10 clean documents spanning search guidance, operations, security context,
  HTML comments, short encoded identifiers, API guidance, and ordinary prose
- 10 malicious or integrity-failed documents spanning instruction override,
  role impersonation, secret exfiltration, tool and response coercion, hidden
  markup, active content, Unicode concealment, printable Base64, and checksum
  mismatch

Every fixture includes provenance fields. The benchmark computes the valid
SHA-256 value at runtime, except for the explicitly labeled checksum-tampering
fixture.

## Classification

The benchmark calls the same `analyze_document` function used by JSONL and live
cluster scans. A document is predicted malicious when its severity is `medium`
or higher. It reports the full confusion matrix, precision, recall, F1,
accuracy, per-document scores, signal coverage, elapsed time, and throughput.

Default quality gates require precision, recall, and F1 to each be at least
`0.95`. Override those thresholds only when intentionally testing a different
acceptance policy.

## Reproduction

From the skill directory:

```bash
uv run python scripts/benchmark.py --output rag-integrity-benchmark.json
```

The expected classification result for version 1.0 of the bundled corpus is:

| Metric | Result |
|---|---:|
| True positives | 10 |
| False positives | 0 |
| True negatives | 10 |
| False negatives | 0 |
| Precision | 1.0 |
| Recall | 1.0 |
| F1 | 1.0 |
| Accuracy | 1.0 |

Runtime and documents-per-second depend on the host and are reported rather
than hard-coded.

## Safety Assertion

The benchmark constructs the standard scanner report and verifies that
`cluster_mutations_performed` is zero and that containment requires human
approval. The analyzer does not connect to or mutate an OpenSearch cluster
during this benchmark.

## Extending the Corpus

Add both clean and malicious fixtures when introducing a signal. Clean fixtures
should include legitimate text near the new pattern so regressions in false
positives are visible. Never add confidential production documents, raw
credentials, or live exploit payloads to the corpus.
