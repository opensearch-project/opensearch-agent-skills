"""Mine and validate candidate synonym pairs for measured vocabulary gaps.

Split into two halves on purpose:

  * Pure functions (``mine_candidate_synonyms``, ``score_overlap``,
    ``rank_delta``) — no OpenSearch client, fully unit-testable with plain
    dicts/lists.
  * Thin client-calling functions (``fetch_sample_document_ids``,
    ``fetch_document_term_lists``, ``validate_synonym_candidate``) — these
    take an already-constructed OpenSearch client so tests can pass a fake.

The overall flow (driven by the CLI / the skill's Step 5):

  1. mine_candidate_synonyms(): given a query term and a sample of documents
     that DID match other query terms, find terms that co-occur with the
     query term's "sibling" concepts elsewhere in the corpus.
  2. validate_synonym_candidate(): run a non-mutating OR query expansion and
     compare before/after rank position for the target document.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

MAX_SAMPLE_DOCUMENTS = 500
MAX_SAMPLE_FIELDS = 20

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "is", "it", "of", "on", "or", "that", "the", "this", "to",
    "was", "were", "with",
}


@dataclass
class SynonymCandidate:
    term: str
    candidate: str
    support: int  # number of documents where the co-occurrence was observed
    confidence: float  # support / documents containing the query term
    association: float = 0.0  # Jaccard association across sampled documents


def mine_candidate_synonyms(
    query_term: str,
    target_doc_terms: list[str],
    corpus_term_lists: list[list[str]],
    min_support: int = 2,
    max_candidates: int = 5,
    min_neighborhood_documents: int = 1,
) -> list[SynonymCandidate]:
    """Find candidate synonyms for ``query_term`` using corpus co-occurrence.

    Candidates must occur in the target document, because expanding the query
    to a term absent from the target cannot make that document match. Support
    counts documents, not repeated token occurrences. Confidence is
    ``P(candidate | query_term)`` and association is document-level Jaccard;
    neither is presented as proof of semantic equivalence.

    This is a lightweight heuristic (word co-occurrence counting), not an
    embedding-based similarity search — deliberately, so it has zero extra
    dependencies and is trivially unit-testable.
    """
    query_term_lower = query_term.lower()
    target_terms_lower = {
        t.lower()
        for t in target_doc_terms
        if len(t) >= 3 and t.lower() not in _STOPWORDS and t.lower() != query_term_lower
    }
    corpus_sets = [{t.lower() for t in terms} for terms in corpus_term_lists]

    # Documents that contain the query term define its "neighborhood".
    neighborhood_docs = [terms for terms in corpus_sets if query_term_lower in terms]
    if len(neighborhood_docs) < min_neighborhood_documents:
        return []

    co_occurrence_counter: Counter[str] = Counter()
    for terms in neighborhood_docs:
        for term in terms & target_terms_lower:
            co_occurrence_counter[term] += 1

    document_frequency: Counter[str] = Counter()
    for terms in corpus_sets:
        for term in terms & target_terms_lower:
            document_frequency[term] += 1

    candidates: list[SynonymCandidate] = []
    for term, support in co_occurrence_counter.most_common():
        if support < min_support:
            continue
        query_docs = len(neighborhood_docs)
        union_docs = query_docs + document_frequency[term] - support
        candidates.append(
            SynonymCandidate(
                term=query_term,
                candidate=term,
                support=support,
                confidence=round(support / query_docs, 4),
                association=round(support / union_docs, 4) if union_docs else 0.0,
            )
        )

    candidates.sort(
        key=lambda candidate: (
            -candidate.support,
            -candidate.association,
            candidate.candidate,
        )
    )
    return candidates[:max_candidates]


def score_overlap(before_terms: set[str], after_terms: set[str], relevant_terms: set[str]) -> dict:
    """Compare term-overlap-with-relevant-set before vs. after a synonym is applied.

    Returns a dict with before/after overlap counts and the delta, used as
    a simple, dependency-free stand-in for a full nDCG recomputation when we
    only have term sets (e.g. from an _analyze simulation) rather than a
    full live re-ranking.
    """
    before_overlap = len(before_terms & relevant_terms)
    after_overlap = len(after_terms & relevant_terms)
    return {
        "before_overlap": before_overlap,
        "after_overlap": after_overlap,
        "delta": after_overlap - before_overlap,
    }


def rank_delta(before_rank: int | None, after_rank: int | None) -> dict:
    """Summarize how a document's rank position changed.

    ``None`` means "did not appear in top-k". Lower rank number is better
    (1 = first place).
    """
    if before_rank is None and after_rank is None:
        return {"before_rank": None, "after_rank": None, "moved": False, "improved": False}
    if before_rank is None:
        return {"before_rank": None, "after_rank": after_rank, "moved": True, "improved": True}
    if after_rank is None:
        return {"before_rank": before_rank, "after_rank": None, "moved": True, "improved": False}
    return {
        "before_rank": before_rank,
        "after_rank": after_rank,
        "moved": before_rank != after_rank,
        "improved": after_rank < before_rank,
    }


# --- Client-calling helpers (thin; take a pre-built client) ----------------


def fetch_sample_documents(client, index: str, fields: list[str], size: int = 200) -> list[dict]:
    """Fetch a sample of documents' field values for corpus-wide term mining.

    Returns sampled ``_source`` dictionaries. Call
    :func:`analyze_source_document` before mining so the configured field
    analyzers, rather than whitespace splitting, produce the term lists.
    """
    if not 1 <= size <= MAX_SAMPLE_DOCUMENTS:
        raise ValueError(f"Sample size must be between 1 and {MAX_SAMPLE_DOCUMENTS}.")
    if not 1 <= len(fields) <= MAX_SAMPLE_FIELDS:
        raise ValueError(f"Field count must be between 1 and {MAX_SAMPLE_FIELDS}.")
    resp = client.search(
        index=index,
        body={
            "size": size,
            "_source": fields,
            "track_total_hits": False,
            "timeout": "10s",
            "terminate_after": 10_000,
            "query": {
                "function_score": {
                    "query": {"match_all": {}},
                    "random_score": {"seed": 8675309, "field": "_seq_no"},
                }
            },
        },
    )
    docs = []
    for hit in resp.get("hits", {}).get("hits", []):
        docs.append(hit.get("_source", {}))
    return docs


def fetch_sample_document_ids(
    client,
    index: str,
    size: int = 200,
    *,
    seed: int = 8675309,
) -> list[str]:
    """Fetch a reproducible, shard-spanning sample without returning `_source`."""
    if not 1 <= size <= MAX_SAMPLE_DOCUMENTS:
        raise ValueError(f"Sample size must be between 1 and {MAX_SAMPLE_DOCUMENTS}.")
    response = client.search(
        index=index,
        body={
            "size": size,
            "_source": False,
            "track_total_hits": False,
            "timeout": "10s",
            "terminate_after": 10_000,
            "query": {
                "function_score": {
                    "query": {"match_all": {}},
                    "random_score": {"seed": seed, "field": "_seq_no"},
                }
            },
        },
        request_timeout=15,
    )
    return [
        str(hit.get("_id"))
        for hit in response.get("hits", {}).get("hits", [])
        if hit.get("_id") is not None
    ]


def fetch_document_term_lists(
    client,
    index: str,
    document_ids: list[str],
    fields: list[str],
) -> list[list[str]]:
    """Generate term vectors for many existing documents in one request."""
    if not document_ids:
        return []
    if len(document_ids) > MAX_SAMPLE_DOCUMENTS:
        raise ValueError(
            f"At most {MAX_SAMPLE_DOCUMENTS} documents may be analyzed at once."
        )
    if not 1 <= len(fields) <= MAX_SAMPLE_FIELDS:
        raise ValueError(f"Field count must be between 1 and {MAX_SAMPLE_FIELDS}.")
    response = client.mtermvectors(
        index=index,
        body={
            "ids": [str(doc_id) for doc_id in document_ids],
            "parameters": {
                "fields": fields,
                "field_statistics": False,
                "term_statistics": False,
                "positions": False,
                "offsets": False,
                "payloads": False,
            },
        },
        request_timeout=30,
    )
    terms_by_id: dict[str, list[str]] = {}
    for document in response.get("docs", []):
        doc_id = str(document.get("_id", ""))
        terms: set[str] = set()
        for field_data in (document.get("term_vectors") or {}).values():
            terms.update(
                str(term).lower()
                for term in (field_data.get("terms") or {})
                if term
            )
        terms_by_id[doc_id] = sorted(terms)
    return [terms_by_id.get(str(doc_id), []) for doc_id in document_ids]


def _source_value(source: dict, field_name: str):
    value = source
    for part in field_name.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def analyze_source_document(client, index: str, source: dict, fields: list[str]) -> list[str]:
    """Analyze selected source fields using each field's configured analyzer."""
    tokens: list[str] = []
    for field_name in fields:
        value = _source_value(source, field_name)
        values = value if isinstance(value, list) else [value]
        text_values = [str(item) for item in values if isinstance(item, str)]
        if not text_values:
            continue
        response = client.indices.analyze(
            index=index,
            body={"field": field_name, "text": text_values},
        )
        tokens.extend(
            str(token.get("token", "")).lower()
            for token in response.get("tokens", [])
            if token.get("token")
        )
    return tokens


def simulate_synonym_analyzer(
    client, index: str, text: str, synonym_pairs: list[tuple[str, str]], base_analyzer: str = "standard"
) -> list[str]:
    """Run ``_analyze`` with a standard tokenizer and inline synonym filter.

    This does not modify the live index — it uses the ``_analyze`` API's
    ability to define a filter/analyzer inline for a single request, so it
    is safe to call against a production cluster.
    """
    if base_analyzer != "standard":
        raise ValueError(
            "Inline synonym simulation currently supports only the standard tokenizer; "
            "validate custom analyzers with a temporary index or search-time analyzer."
        )
    if any(
        not a.strip()
        or not b.strip()
        or "," in a
        or "," in b
        or "=>" in a
        or "=>" in b
        for a, b in synonym_pairs
    ):
        raise ValueError("Synonym terms must be non-empty and cannot contain ',' or '=>'.")
    synonym_rules = [f"{a}, {b}" for a, b in synonym_pairs]
    body = {
        "text": text,
        "tokenizer": "standard",
        "filter": [
            "lowercase",
            {"type": "synonym", "synonyms": synonym_rules},
        ],
    }
    resp = client.indices.analyze(index=index, body=body)
    return [t["token"] for t in resp.get("tokens", [])]


def validate_synonym_candidate(
    client,
    index: str,
    query_term: str,
    candidate: SynonymCandidate,
    target_doc_id: str,
    search_fn,
) -> dict:
    """Validate a candidate with a non-mutating OR query expansion.

    ``search_fn`` is injected (rather than hardcoded to a specific query
    shape) so this works across match/multi_match/hybrid queries — it must
    be a callable ``search_fn(client, index, query_text) -> list[doc_id]``
    returning ranked document ids.
    """
    target_id = str(target_doc_id)
    before_ranked = [
        str(doc_id) for doc_id in search_fn(client, index, query_term)
    ]
    before_rank = (
        before_ranked.index(target_id) + 1 if target_id in before_ranked else None
    )

    expanded_query = f"{query_term} {candidate.candidate}"
    after_ranked = [
        str(doc_id) for doc_id in search_fn(client, index, expanded_query)
    ]
    after_rank = (
        after_ranked.index(target_id) + 1 if target_id in after_ranked else None
    )

    delta = rank_delta(before_rank, after_rank)
    return {
        "query_term": query_term,
        "candidate": candidate.candidate,
        "confidence": candidate.confidence,
        "validation_method": "or_query_expansion",
        **delta,
    }
