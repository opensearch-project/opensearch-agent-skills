#!/usr/bin/env python3
"""Read-only integrity analysis for OpenSearch RAG corpora.

The analyzer treats indexed content as untrusted data. It detects deterministic
prompt-injection and concealment signals, verifies optional provenance fields,
and groups exact or near-duplicate documents with SimHash. When connected to
OpenSearch, it can use a deployed neural-search model to expand suspicious
documents into semantic-neighbor candidates.

No command in this module mutates an OpenSearch cluster.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse


SCHEMA_VERSION = "1.0"
DEFAULT_TEXT_FIELDS = ("content", "text", "body", "chunk")
DEFAULT_PROVENANCE_FIELDS = ("source_uri", "ingested_at", "content_sha256")
ZERO_WIDTH_CODEPOINTS = {
    "\u200b",
    "\u200c",
    "\u200d",
    "\u2060",
    "\ufeff",
}
BIDI_CONTROL_CODEPOINTS = {
    "\u061c",
    "\u200e",
    "\u200f",
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
    "\u2066",
    "\u2067",
    "\u2068",
    "\u2069",
}
SEVERITY_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass(frozen=True)
class DetectionRule:
    rule_id: str
    weight: int
    severity: str
    description: str
    pattern: re.Pattern[str]


RULES: tuple[DetectionRule, ...] = (
    DetectionRule(
        "instruction-override",
        38,
        "high",
        "Content attempts to supersede prior, system, or developer instructions.",
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\b.{0,60}"
            r"\b(?:previous|prior|above|system|developer)\b.{0,60}"
            r"\b(?:instruction|message|prompt|rule)s?\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    DetectionRule(
        "role-impersonation",
        28,
        "medium",
        "Content imitates a privileged model-message role.",
        re.compile(
            r"\b(?:system|developer|assistant)\s*(?:message|prompt|instruction)s?\s*[:=]",
            re.IGNORECASE,
        ),
    ),
    DetectionRule(
        "secret-exfiltration",
        45,
        "high",
        "Content asks the retriever or model to disclose credentials or private prompts.",
        re.compile(
            r"\b(?:reveal|print|show|exfiltrate|send|return|leak)\b.{0,90}"
            r"\b(?:system prompt|api[- ]?key|secret|credential|access token|password)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    DetectionRule(
        "tool-coercion",
        32,
        "high",
        "Content attempts to make the agent invoke a tool, shell, or command.",
        re.compile(
            r"\b(?:call|invoke|run|execute|launch|use)\b.{0,50}"
            r"\b(?:tool|function|shell|terminal|command|powershell|bash)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    DetectionRule(
        "response-coercion",
        30,
        "high",
        "Content tells the model what to output instead of supplying source material.",
        re.compile(
            r"\b(?:do not (?:summarize|answer|cite)|instead (?:say|output|respond)|"
            r"you must (?:say|output|respond)|reply only with)\b",
            re.IGNORECASE,
        ),
    ),
    DetectionRule(
        "hidden-markup-instruction",
        24,
        "medium",
        "An HTML comment contains instruction-like language.",
        re.compile(
            r"<!--(?:(?!-->).){0,1200}"
            r"(?:ignore|disregard|system prompt|assistant|execute|reveal)"
            r"(?:(?!-->).){0,1200}-->",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    DetectionRule(
        "embedded-active-content",
        24,
        "medium",
        "Content embeds an active data URI or script-like payload.",
        re.compile(
            r"(?:data\s*:\s*(?:text/html|application/javascript)|<script\b|javascript\s*:)",
            re.IGNORECASE,
        ),
    ),
)


def utc_now() -> str:
    """Return an RFC 3339 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_csv(value: str) -> tuple[str, ...]:
    """Parse a comma-separated list into a stable tuple."""
    return tuple(part.strip() for part in value.split(",") if part.strip())


def get_path(source: Mapping[str, Any], dotted_path: str) -> Any:
    """Read a dotted path from a nested mapping."""
    value: Any = source
    for part in dotted_path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def text_value(value: Any) -> str:
    """Convert only text-bearing values into analyzable text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(text_value(item) for item in value if text_value(item))
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def extract_text(source: Mapping[str, Any], fields: Sequence[str]) -> str:
    """Join configured document fields without interpreting their contents."""
    parts = []
    for field in fields:
        value = text_value(get_path(source, field))
        if value:
            parts.append(value)
    return "\n".join(parts)


def normalized_text(text: str) -> str:
    """Normalize compatibility characters while preserving control evidence."""
    return unicodedata.normalize("NFKC", text)


def content_sha256(text: str) -> str:
    """Hash normalized UTF-8 content deterministically."""
    return hashlib.sha256(normalized_text(text).encode("utf-8")).hexdigest()


def redact_controls(text: str) -> str:
    """Make invisible and control code points explicit in short evidence."""
    rendered: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if char in ZERO_WIDTH_CODEPOINTS or char in BIDI_CONTROL_CODEPOINTS:
            rendered.append(f"<U+{ord(char):04X}>")
        elif category.startswith("C") and char not in "\n\t\r":
            rendered.append(f"<U+{ord(char):04X}>")
        elif char in "\r\n\t":
            rendered.append(" ")
        else:
            rendered.append(char)
    return re.sub(r"\s+", " ", "".join(rendered)).strip()


def evidence_snippet(text: str, start: int, end: int, radius: int = 48) -> str:
    """Return bounded, control-visible evidence without reproducing a document."""
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = redact_controls(text[left:right])
    if left:
        snippet = "…" + snippet
    if right < len(text):
        snippet += "…"
    return snippet[:240]


def signal(
    signal_id: str,
    severity: str,
    weight: int,
    description: str,
    *,
    evidence: str | None = None,
    count: int | None = None,
) -> dict[str, Any]:
    """Create a stable finding signal."""
    item: dict[str, Any] = {
        "id": signal_id,
        "severity": severity,
        "weight": weight,
        "description": description,
    }
    if evidence:
        item["evidence"] = evidence
    if count is not None:
        item["count"] = count
    return item


def encoded_blob_signal(text: str) -> dict[str, Any] | None:
    """Detect long Base64 blobs that decode mostly to printable bytes."""
    for match in re.finditer(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{80,}={0,2}", text):
        candidate = match.group(0)
        unpadded = candidate.rstrip("=")
        remainder = len(unpadded) % 4
        if remainder == 1:
            continue
        normalized = unpadded + ("=" * ((4 - remainder) % 4))
        try:
            decoded = base64.b64decode(normalized, validate=True)
        except (ValueError, base64.binascii.Error):
            continue
        if not decoded:
            continue
        printable = sum(
            byte in (9, 10, 13) or 32 <= byte <= 126 for byte in decoded
        ) / len(decoded)
        if printable >= 0.72:
            return signal(
                "encoded-text-blob",
                "medium",
                18,
                "A long Base64 value decodes predominantly to printable text.",
                evidence=evidence_snippet(text, match.start(), match.end()),
            )
    return None


def tokenize(text: str) -> list[str]:
    """Tokenize normalized text for deterministic SimHash."""
    return re.findall(r"[\w'-]+", normalized_text(text).casefold())


def simhash64(tokens: Sequence[str]) -> int:
    """Compute a deterministic 64-bit token-frequency SimHash."""
    if not tokens:
        return 0
    frequencies = Counter(tokens)
    vector = [0] * 64
    for token, frequency in frequencies.items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        weight = frequency.bit_length()
        for bit in range(64):
            vector[bit] += weight if (value >> bit) & 1 else -weight
    result = 0
    for bit, score in enumerate(vector):
        if score >= 0:
            result |= 1 << bit
    return result


def hamming_distance(left: int, right: int) -> int:
    """Return the Hamming distance between two integers."""
    return (left ^ right).bit_count()


def severity_for_score(score: int) -> str:
    """Map a bounded risk score to a stable severity."""
    if score >= 85:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    if score > 0:
        return "low"
    return "none"


def analyze_document(
    *,
    index: str,
    document_id: str,
    source: Mapping[str, Any],
    text_fields: Sequence[str] = DEFAULT_TEXT_FIELDS,
    provenance_fields: Sequence[str] = DEFAULT_PROVENANCE_FIELDS,
) -> dict[str, Any]:
    """Analyze one untrusted document without executing or following its text."""
    raw_text = extract_text(source, text_fields)
    normalized = normalized_text(raw_text)
    findings: list[dict[str, Any]] = []

    for rule in RULES:
        match = rule.pattern.search(normalized)
        if match:
            findings.append(
                signal(
                    rule.rule_id,
                    rule.severity,
                    rule.weight,
                    rule.description,
                    evidence=evidence_snippet(normalized, match.start(), match.end()),
                )
            )

    zero_width_count = sum(char in ZERO_WIDTH_CODEPOINTS for char in raw_text)
    if zero_width_count:
        findings.append(
            signal(
                "zero-width-concealment",
                "medium",
                min(24, 10 + zero_width_count),
                "Content contains zero-width code points that can conceal instructions.",
                count=zero_width_count,
            )
        )

    bidi_count = sum(char in BIDI_CONTROL_CODEPOINTS for char in raw_text)
    if bidi_count:
        findings.append(
            signal(
                "bidirectional-override",
                "high",
                min(34, 22 + bidi_count),
                "Content contains bidirectional controls that can reorder displayed text.",
                count=bidi_count,
            )
        )

    other_controls = sum(
        unicodedata.category(char).startswith("C")
        and char not in ZERO_WIDTH_CODEPOINTS
        and char not in BIDI_CONTROL_CODEPOINTS
        and char not in "\n\t\r"
        for char in raw_text
    )
    if other_controls:
        findings.append(
            signal(
                "unexpected-control-characters",
                "low",
                min(14, 5 + other_controls),
                "Content contains non-formatting control characters.",
                count=other_controls,
            )
        )

    encoded = encoded_blob_signal(normalized)
    if encoded:
        findings.append(encoded)

    computed_hash = content_sha256(raw_text)
    missing_provenance = [
        field
        for field in provenance_fields
        if get_path(source, field) in (None, "", [])
    ]
    if missing_provenance:
        findings.append(
            signal(
                "missing-provenance",
                "low",
                min(20, 4 * len(missing_provenance)),
                "Configured provenance fields are absent: "
                + ", ".join(missing_provenance),
                count=len(missing_provenance),
            )
        )

    expected_hash = get_path(source, "content_sha256")
    if isinstance(expected_hash, str) and expected_hash:
        normalized_expected = expected_hash.removeprefix("sha256:").casefold()
        if normalized_expected != computed_hash:
            findings.append(
                signal(
                    "provenance-hash-mismatch",
                    "critical",
                    70,
                    "The stored content_sha256 does not match the analyzed content.",
                )
            )

    risk_score = min(100, sum(item["weight"] for item in findings))
    score_severity = severity_for_score(risk_score)
    strongest_signal = max(
        (item["severity"] for item in findings),
        key=lambda severity: SEVERITY_ORDER[severity],
        default="none",
    )
    compound_severity = (
        "critical"
        if sum(
            SEVERITY_ORDER[item["severity"]] >= SEVERITY_ORDER["high"]
            for item in findings
        )
        >= 2
        else "none"
    )
    overall_severity = max(
        (score_severity, strongest_signal, compound_severity),
        key=lambda severity: SEVERITY_ORDER[severity],
    )
    tokens = tokenize(raw_text)
    return {
        "index": index,
        "id": str(document_id),
        "risk_score": risk_score,
        "severity": overall_severity,
        "content_sha256": computed_hash,
        "simhash64": f"{simhash64(tokens):016x}",
        "token_count": len(tokens),
        "signals": sorted(
            findings,
            key=lambda item: (
                -SEVERITY_ORDER[item["severity"]],
                -item["weight"],
                item["id"],
            ),
        ),
        "recommended_action": (
            "isolate-and-review"
            if SEVERITY_ORDER[overall_severity] >= SEVERITY_ORDER["high"]
            else "review"
            if overall_severity == "medium"
            else "retain-with-evidence"
        ),
    }


class UnionFind:
    """Small deterministic union-find for duplicate clustering."""

    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def find_near_duplicate_clusters(
    findings: Sequence[Mapping[str, Any]], max_distance: int = 3
) -> list[dict[str, Any]]:
    """Group exact and near-duplicate documents using deterministic SimHash."""
    eligible = [item for item in findings if int(item.get("token_count", 0)) >= 5]
    union_find = UnionFind(len(eligible))
    pair_distances: dict[tuple[int, int], int] = {}
    for left in range(len(eligible)):
        left_hash = int(str(eligible[left]["simhash64"]), 16)
        for right in range(left + 1, len(eligible)):
            right_hash = int(str(eligible[right]["simhash64"]), 16)
            distance = hamming_distance(left_hash, right_hash)
            exact_match = (
                eligible[left]["content_sha256"] == eligible[right]["content_sha256"]
            )
            if exact_match or distance <= max_distance:
                union_find.union(left, right)
                if distance <= max_distance:
                    pair_distances[(left, right)] = distance

    grouped: dict[int, list[int]] = {}
    for position in range(len(eligible)):
        grouped.setdefault(union_find.find(position), []).append(position)

    clusters: list[dict[str, Any]] = []
    for positions in grouped.values():
        if len(positions) < 2:
            continue
        distances = [
            distance
            for (left, right), distance in pair_distances.items()
            if left in positions and right in positions
        ]
        members = [
            {
                "index": eligible[position]["index"],
                "id": eligible[position]["id"],
                "content_sha256": eligible[position]["content_sha256"],
                "severity": eligible[position]["severity"],
            }
            for position in positions
        ]
        exact_content = len({member["content_sha256"] for member in members}) == 1
        distance_basis = (
            "exact-content" if exact_content else "qualifying-simhash-edges"
        )
        reported_distances = [] if exact_content else distances
        clusters.append(
            {
                "cluster_id": hashlib.sha256(
                    "|".join(
                        sorted(
                            f"{member['index']}:{member['id']}" for member in members
                        )
                    ).encode("utf-8")
                ).hexdigest()[:16],
                "member_count": len(members),
                "minimum_simhash_distance": (
                    min(reported_distances) if reported_distances else 0
                ),
                "maximum_simhash_distance": (
                    max(reported_distances) if reported_distances else 0
                ),
                "distance_basis": distance_basis,
                "exact_content": exact_content,
                "members": sorted(
                    members, key=lambda member: (member["index"], member["id"])
                ),
                "recommended_action": "compare-provenance-and-ingest-history",
            }
        )
    return sorted(
        clusters, key=lambda cluster: (-cluster["member_count"], cluster["cluster_id"])
    )


def build_neural_query(
    *,
    vector_field: str,
    query_text: str,
    model_id: str,
    k: int,
    exclude_id: str | None = None,
) -> dict[str, Any]:
    """Build an OpenSearch neural-query request for semantic expansion."""
    neural: dict[str, Any] = {
        "neural": {
            vector_field: {
                "query_text": query_text,
                "model_id": model_id,
                "k": k,
            }
        }
    }
    query: dict[str, Any] = neural
    if exclude_id:
        query = {
            "bool": {
                "must": [neural],
                "must_not": [{"ids": {"values": [exclude_id]}}],
            }
        }
    return {
        "_source": {"excludes": [vector_field]},
        "size": k,
        "query": query,
    }


def make_report(
    findings: Sequence[dict[str, Any]],
    *,
    near_duplicate_distance: int,
    semantic_neighbors: Sequence[dict[str, Any]] | None = None,
    source: str,
) -> dict[str, Any]:
    """Build the stable machine-readable report."""
    ordered = sorted(
        findings,
        key=lambda item: (
            -SEVERITY_ORDER[item["severity"]],
            -item["risk_score"],
            item["index"],
            item["id"],
        ),
    )
    severities = Counter(item["severity"] for item in ordered)
    duplicate_clusters = find_near_duplicate_clusters(
        ordered, max_distance=near_duplicate_distance
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "mode": "read-only",
        "source": source,
        "summary": {
            "documents_analyzed": len(ordered),
            "critical": severities["critical"],
            "high": severities["high"],
            "medium": severities["medium"],
            "low": severities["low"],
            "clean": severities["none"],
            "near_duplicate_clusters": len(duplicate_clusters),
        },
        "findings": ordered,
        "near_duplicate_clusters": duplicate_clusters,
        "semantic_neighbors": list(semantic_neighbors or []),
        "safety": {
            "cluster_mutations_performed": 0,
            "containment_requires_human_approval": True,
            "content_was_treated_as_untrusted_data": True,
        },
    }


def load_jsonl(path: Path) -> Iterable[tuple[int, Mapping[str, Any]]]:
    """Yield non-empty JSON objects from a UTF-8 JSONL file."""
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, Mapping):
                raise ValueError(f"line {line_number}: expected a JSON object")
            yield line_number, value


def scan_jsonl(args: argparse.Namespace) -> dict[str, Any]:
    """Analyze a JSONL export."""
    findings: list[dict[str, Any]] = []
    for line_number, record in load_jsonl(Path(args.input)):
        raw_source = record.get("_source", record)
        if not isinstance(raw_source, Mapping):
            raise ValueError(f"line {line_number}: _source must be an object")
        findings.append(
            analyze_document(
                index=str(record.get("_index", args.index)),
                document_id=str(record.get("_id", record.get("id", line_number))),
                source=raw_source,
                text_fields=args.text_fields,
                provenance_fields=args.provenance_fields,
            )
        )
    return make_report(
        findings,
        near_duplicate_distance=args.near_duplicate_distance,
        source=f"jsonl:{Path(args.input).resolve()}",
    )


def client_from_environment() -> Any:
    """Create an OpenSearch client without accepting credentials on the CLI."""
    endpoint = os.environ.get("OPENSEARCH_URL")
    if not endpoint:
        raise RuntimeError("OPENSEARCH_URL is required for scan-cluster")
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("OPENSEARCH_URL must be an http(s) URL")
    if parsed.username or parsed.password:
        raise RuntimeError(
            "do not embed credentials in OPENSEARCH_URL; use the credential "
            "environment variables"
        )

    username = os.environ.get("OPENSEARCH_USERNAME")
    password = os.environ.get("OPENSEARCH_PASSWORD")
    if bool(username) != bool(password):
        raise RuntimeError(
            "set both OPENSEARCH_USERNAME and OPENSEARCH_PASSWORD, or neither"
        )
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = parsed.hostname.casefold() == "localhost"
    if parsed.scheme == "http" and not loopback:
        raise RuntimeError(
            "plain HTTP is allowed only for loopback development endpoints"
        )
    if username and parsed.scheme != "https":
        raise RuntimeError("OpenSearch credentials require an HTTPS endpoint")

    verify_setting = os.environ.get("OPENSEARCH_SSL_VERIFY", "true").casefold()
    if verify_setting in {"1", "true", "yes"}:
        verify_certs = True
    elif verify_setting in {"0", "false", "no"}:
        verify_certs = False
    else:
        raise RuntimeError(
            "OPENSEARCH_SSL_VERIFY must be true, false, yes, no, 1, or 0"
        )
    if not verify_certs and (parsed.scheme != "https" or not loopback or username):
        raise RuntimeError(
            "disabling TLS verification is allowed only for unauthenticated "
            "HTTPS loopback endpoints"
        )

    try:
        from opensearchpy import OpenSearch
    except ImportError as exc:
        raise RuntimeError(
            "opensearch-py is required; run this command through uv"
        ) from exc
    host: dict[str, Any] = {
        "host": parsed.hostname,
        "port": parsed.port or (443 if parsed.scheme == "https" else 80),
        "scheme": parsed.scheme,
    }
    kwargs: dict[str, Any] = {
        "hosts": [host],
        "use_ssl": parsed.scheme == "https",
        "verify_certs": verify_certs,
        "timeout": 30,
    }
    if username and password:
        kwargs["http_auth"] = (username, password)
    return OpenSearch(**kwargs)


def semantic_expansion(
    client: Any,
    *,
    index: str,
    sources: Mapping[str, str],
    findings: Sequence[Mapping[str, Any]],
    vector_field: str,
    model_id: str,
    k: int,
    max_seeds: int,
) -> list[dict[str, Any]]:
    """Expand the highest-risk seeds using OpenSearch's neural query."""
    expanded: list[dict[str, Any]] = []
    seeds = [item for item in findings if SEVERITY_ORDER[item["severity"]] >= 2][
        :max_seeds
    ]
    for seed in seeds:
        query_text = sources.get(str(seed["id"]), "")
        if not query_text:
            continue
        body = build_neural_query(
            vector_field=vector_field,
            query_text=query_text[:4000],
            model_id=model_id,
            k=k,
            exclude_id=str(seed["id"]),
        )
        response = client.search(index=index, body=body)
        neighbors = [
            {
                "index": hit.get("_index", index),
                "id": str(hit.get("_id")),
                "score": hit.get("_score"),
            }
            for hit in response.get("hits", {}).get("hits", [])
        ]
        expanded.append(
            {
                "seed": {"index": seed["index"], "id": seed["id"]},
                "query_type": "neural",
                "neighbors": neighbors,
            }
        )
    return expanded


def scan_cluster(args: argparse.Namespace) -> dict[str, Any]:
    """Read a bounded sample from OpenSearch and analyze it."""
    client = client_from_environment()
    # Mapping retrieval is an intentional preflight: it proves index visibility
    # before document sampling and gives operators an auditable discovery call.
    client.indices.get_mapping(index=args.index)
    response = client.search(
        index=args.index,
        body={
            "size": args.size,
            "sort": ["_doc"],
            "_source": {
                "includes": sorted(set(args.text_fields + args.provenance_fields))
            },
            "query": {"match_all": {}},
        },
    )
    findings: list[dict[str, Any]] = []
    source_text: dict[str, str] = {}
    for hit in response.get("hits", {}).get("hits", []):
        source = hit.get("_source") or {}
        if not isinstance(source, Mapping):
            continue
        document_id = str(hit.get("_id"))
        source_text[document_id] = extract_text(source, args.text_fields)
        findings.append(
            analyze_document(
                index=str(hit.get("_index", args.index)),
                document_id=document_id,
                source=source,
                text_fields=args.text_fields,
                provenance_fields=args.provenance_fields,
            )
        )

    semantic_neighbors: list[dict[str, Any]] = []
    if args.semantic_field or args.model_id:
        if not (args.semantic_field and args.model_id):
            raise ValueError(
                "--semantic-field and --model-id must be provided together"
            )
        semantic_neighbors = semantic_expansion(
            client,
            index=args.index,
            sources=source_text,
            findings=findings,
            vector_field=args.semantic_field,
            model_id=args.model_id,
            k=args.semantic_k,
            max_seeds=args.semantic_seeds,
        )
    return make_report(
        findings,
        near_duplicate_distance=args.near_duplicate_distance,
        semantic_neighbors=semantic_neighbors,
        source=f"opensearch:{args.index}",
    )


def write_report(report: Mapping[str, Any], output: str) -> None:
    """Write a report to stdout or a UTF-8 JSON file."""
    rendered = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True)
    if output == "-":
        print(rendered)
        return
    Path(output).write_text(rendered + "\n", encoding="utf-8")


def should_fail(report: Mapping[str, Any], threshold: str) -> bool:
    """Return whether report severity meets a caller-selected CI threshold."""
    if threshold == "none":
        return False
    minimum = SEVERITY_ORDER[threshold]
    return any(
        SEVERITY_ORDER[item["severity"]] >= minimum
        for item in report.get("findings", [])
    )


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--text-fields",
        type=parse_csv,
        default=DEFAULT_TEXT_FIELDS,
        help="Comma-separated text-bearing fields (default: content,text,body,chunk)",
    )
    parser.add_argument(
        "--provenance-fields",
        type=parse_csv,
        default=DEFAULT_PROVENANCE_FIELDS,
        help="Comma-separated fields required for provenance checks",
    )
    parser.add_argument(
        "--near-duplicate-distance",
        type=int,
        default=3,
        choices=range(0, 17),
        metavar="0..16",
        help="Maximum 64-bit SimHash distance for near duplicates (default: 3)",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Report path, or - for stdout (default: -)",
    )
    parser.add_argument(
        "--fail-on",
        choices=("none", "low", "medium", "high", "critical"),
        default="none",
        help="Exit 2 when a finding meets this severity (default: none)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only prompt-injection, provenance, and duplicate analysis "
            "for OpenSearch RAG corpora"
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    jsonl = subparsers.add_parser(
        "scan-jsonl", help="Analyze a JSONL export without a cluster"
    )
    jsonl.add_argument("--input", required=True, help="UTF-8 JSONL input")
    jsonl.add_argument("--index", default="offline-export", help="Fallback index name")
    add_common_arguments(jsonl)
    jsonl.set_defaults(handler=scan_jsonl)

    cluster = subparsers.add_parser(
        "scan-cluster", help="Analyze a bounded read-only OpenSearch sample"
    )
    cluster.add_argument("--index", required=True, help="Index, alias, or pattern")
    cluster.add_argument(
        "--size",
        type=int,
        default=250,
        choices=range(1, 1001),
        metavar="1..1000",
        help="Maximum sampled documents (default: 250)",
    )
    cluster.add_argument(
        "--semantic-field",
        help="Optional neural-search embedding field for semantic expansion",
    )
    cluster.add_argument(
        "--model-id",
        help="Optional deployed OpenSearch embedding model ID",
    )
    cluster.add_argument(
        "--semantic-k",
        type=int,
        default=10,
        choices=range(1, 101),
        metavar="1..100",
    )
    cluster.add_argument(
        "--semantic-seeds",
        type=int,
        default=5,
        choices=range(1, 21),
        metavar="1..20",
    )
    add_common_arguments(cluster)
    cluster.set_defaults(handler=scan_cluster)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = args.handler(args)
        write_report(report, args.output)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"rag-integrity-sentinel: {exc}", file=sys.stderr)
        return 1
    return 2 if should_fail(report, args.fail_on) else 0


if __name__ == "__main__":
    raise SystemExit(main())
