#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["opensearch-py>=2.4"]
# ///
"""CLI for permission-aware-search: permission-enforced search with optional RAG, using OpenSearch DLS.

Usage:
    uv run python scripts/permission_search.py <command> [options]

Commands:
    check-security  Verify the security plugin is enabled and DLS is available
    check-llm       Check reachability of the optional RAG LLM endpoint
    setup           Create indexes and the DLS reader role (idempotent)
    create-users    Create OpenSearch users mapped to the reader role (demos, eval-dls)
    ingest          Index documents from a JSONL file or directory
    sync-acl        Update the ACL lookup index from a static users-to-principals file
    refresh-acl     Rebuild the ACL lookup index atomically from a
                    group-to-members file
    query           Search as an end user (DLS enforced by OpenSearch); add --rag for an LLM answer
    eval-dls        Verify DLS enforcement for two users and a known document
    benchmark       Measure query latency
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class ConfigurationError(ValueError):
    """A user-correctable CLI or environment configuration error."""


class ExtractionError(RuntimeError):
    """A sanitized document conversion failure."""

    def __init__(self, filename: str, error_type: str):
        super().__init__(f"Failed to extract {filename} ({error_type})")
        self.filename = filename
        self.error_type = error_type


class OptionalDependencyError(RuntimeError):
    """An optional feature was requested without its Python package."""


# Optional packages ship in named dependency groups in pyproject.toml.
_DEPENDENCY_GROUPS = {"docling": "ingestion", "boto3": "ingestion"}


def _optional_dependency_error(package: str, feature: str) -> OptionalDependencyError:
    group = _DEPENDENCY_GROUPS.get(package, package)
    return OptionalDependencyError(
        f"{feature} requires optional package {package!r}. "
        f"Re-run with `uv run --group {group} python scripts/permission_search.py ...`."
    )


def cmd_check_security(args):
    config = _runtime_config(args)
    from lib.os_client import build_admin_client
    from opensearchpy.exceptions import (
        AuthenticationException,
        AuthorizationException,
        ConnectionError as OpenSearchConnectionError,
        NotFoundError,
        SerializationError,
        TransportError,
    )

    client = build_admin_client(config)
    try:
        response = client.transport.perform_request("GET", "/_plugins/_security/health")
    except NotFoundError:
        result = {
            "security": "disabled",
            "dls_supported": False,
            "error": "plugin_not_found",
        }
    except AuthenticationException:
        result = {
            "security": "unknown",
            "dls_supported": False,
            "error": "authentication",
        }
    except AuthorizationException:
        result = {
            "security": "unknown",
            "dls_supported": False,
            "error": "authorization",
        }
    except OpenSearchConnectionError:
        result = {
            "security": "unknown",
            "dls_supported": False,
            "error": "connection",
        }
    except SerializationError:
        result = {
            "security": "unknown",
            "dls_supported": False,
            "error": "malformed_response",
        }
    except TransportError as exc:
        result = {
            "security": "unknown",
            "dls_supported": False,
            "error": "transport",
            "status_code": exc.status_code,
        }
    else:
        status = response.get("status") if isinstance(response, dict) else None
        if status == "UP":
            result = {"security": "enabled", "dls_supported": True}
        elif status == "DOWN":
            result = {
                "security": "unhealthy",
                "dls_supported": False,
                "error": "health",
            }
        else:
            result = {
                "security": "unknown",
                "dls_supported": False,
                "error": "malformed_response",
            }

    print(json.dumps(result))
    if not result["dls_supported"]:
        sys.exit(1)


def cmd_check_llm(args):
    """Check reachability of the optional RAG LLM endpoint (openai_compatible/DMR)."""
    from urllib.request import urlopen

    config = _runtime_config(args)
    llm_cfg = config.get("llm", {})
    provider = llm_cfg.get("provider", "openai_compatible")
    if provider not in ("openai_compatible", "dmr"):
        print(json.dumps({"provider": provider, "note": "reachability check only supports openai_compatible/dmr"}))
        return
    base_url = llm_cfg.get("base_url", "http://localhost:12434/engines/v1")
    try:
        with urlopen(f"{base_url.rstrip('/')}/models", timeout=10) as response:
            payload = json.loads(response.read())
        models = [m.get("id") for m in payload.get("data", [])]
        print(json.dumps({"reachable": True, "base_url": base_url, "models": models}))
    except Exception as e:
        print(json.dumps({"reachable": False, "base_url": base_url, "error": str(e)}))
        sys.exit(1)


def cmd_setup(args):
    from lib.dls_manager import DLSManager
    from lib.index_writer import IndexWriter

    config = _runtime_config(args)
    writer = IndexWriter(config)
    acl_lookup_index = writer.setup(force_recreate=args.recreate)

    mgr = DLSManager(config)
    mgr.create_role(acl_lookup_index=acl_lookup_index)
    mgr.ensure_role_mapping()

    index = config["opensearch"]["index"]
    print(json.dumps({"status": "ok", "index": index, "acl_index": f"{index}-acl"}))


def cmd_create_users(args):
    """Create named users in OpenSearch security and map them to the reader role.

    Convenience for demos and eval-dls. Passwords follow the same convention
    eval-dls uses (a fixed demo password) unless --password is given.
    """
    from lib.dls_manager import DLSManager

    config = _runtime_config(args)
    mgr = DLSManager(config)
    usernames = [u.strip() for u in args.users.split(",") if u.strip()]
    created = []
    for username in usernames:
        password = args.password or _derive_test_password(username)
        mgr.create_test_user(username, password)
        mgr.map_test_user_to_role(username)
        created.append(username)
    print(json.dumps({"status": "ok", "users_created": created, "role": mgr.role_name}))


def cmd_ingest(args, writer_factory=None, chunk_text_fn=None):
    if writer_factory is None:
        from lib.index_writer import IndexWriter
        writer_factory = IndexWriter
    if chunk_text_fn is None:
        from lib.chunker import chunk_text
        chunk_text_fn = chunk_text

    config = _runtime_config(args)
    writer = writer_factory(config)
    cfg = config.get("chunking", {})
    chunk_size = cfg.get("chunk_size", 512)
    chunk_overlap = cfg.get("chunk_overlap", 64)

    indexed = skipped = 0
    extraction_errors = []
    batch: list[dict] = []
    batch_size = args.batch_size

    def flush():
        if batch:
            writer.bulk_index(batch)
            batch.clear()

    def process_record(rec: dict):
        nonlocal indexed, skipped
        content = rec.get("content", "").strip()
        allowed = rec.get("allowed_users", [])
        if not content or not allowed:
            skipped += 1
            return
        chunks = chunk_text_fn(content, chunk_size, chunk_overlap)
        for chunk_id, chunk in enumerate(chunks):
            doc = {
                "title": rec.get("title", ""),
                "content": chunk,
                "allowed_users": allowed,
                "path": rec.get("path", ""),
                "source_file": rec.get("source_file", ""),
                "chunk_id": chunk_id,
                "metadata": rec.get("metadata", {}),
            }
            batch.append(doc)
            indexed += 1
            if len(batch) >= batch_size:
                flush()
    if args.input:
        input_path = args.input
        if os.path.isfile(input_path) and input_path.endswith(".jsonl"):
            with open(input_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        process_record(json.loads(line))
        elif os.path.isdir(input_path):
            acl_file = json.load(open(args.acl_file)) if args.acl_file else {}
            for fname in sorted(os.listdir(input_path)):
                fpath = os.path.join(input_path, fname)
                if not os.path.isfile(fpath):
                    continue
                allowed = acl_file.get(fname, [])
                if not allowed:
                    skipped += 1
                    continue
                try:
                    text = _extract_text(fpath)
                except ExtractionError as exc:
                    skipped += 1
                    extraction_errors.append({
                        "file": exc.filename,
                        "reason": "conversion_failed",
                        "error_type": exc.error_type,
                    })
                    continue
                if text is None:
                    skipped += 1
                    continue
                if not text:
                    skipped += 1
                    continue
                process_record({"content": text, "allowed_users": allowed,
                                "source_file": fname, "path": fpath})
        else:
            print(json.dumps({"error": f"Unsupported input: {input_path}"}))
            sys.exit(1)

    flush()
    result = {"indexed": indexed, "skipped": skipped}
    if extraction_errors:
        result["errors"] = extraction_errors
    print(json.dumps(result))
    if extraction_errors:
        sys.exit(1)


def cmd_sync_acl(args, writer_factory=None):
    if writer_factory is None:
        from lib.index_writer import IndexWriter
        writer_factory = IndexWriter

    config = _runtime_config(args)
    writer = writer_factory(config)

    with open(args.acl_file) as f:
        mapping = json.load(f)
    if not isinstance(mapping, dict):
        raise ValueError("ACL file must contain a JSON object mapping users to principals")

    docs = [{"_id": user, "allowed_users": principals}
            for user, principals in mapping.items()]
    backing_index = writer.replace_acl_documents(docs)
    print(json.dumps({
        "status": "ok",
        "users_synced": len(docs),
        "acl_backing_index": backing_index,
    }))


def cmd_refresh_acl(args, writer_factory=None, resolver_factory=None):
    if resolver_factory is None:
        from lib.group_resolver import build_resolver
        resolver_factory = build_resolver
    if writer_factory is None:
        from lib.index_writer import IndexWriter
        writer_factory = IndexWriter

    config = _runtime_config(args)

    resolver = resolver_factory(config)
    mapping = resolver.get_all_user_principals()

    if not mapping:
        print(json.dumps({"status": "error", "message": "Directory returned no users"}))
        sys.exit(1)

    writer = writer_factory(config)
    backing_index = writer.replace_acl_documents([
        {"_id": user, "allowed_users": principals}
        for user, principals in mapping.items()
    ])

    print(json.dumps({
        "status": "ok",
        "users_refreshed": len(mapping),
        "source": config.get("directory", {}).get("source", "unknown"),
        "acl_backing_index": backing_index,
    }))


def cmd_query(args):
    password = _required_user_password(args)
    from lib.search_runner import LLMProviderError, SearchRunner

    config = _runtime_config(args)
    # DLS resolves ${user.name} from these authenticated end-user credentials.
    runner = SearchRunner(config, username=args.user, password=password)
    try:
        result = runner.query(question=args.question, top_k=args.top_k, rag=args.rag)
    except LLMProviderError as exc:
        error = {
            "status": "error",
            "provider": exc.provider,
            "category": exc.category,
            "message": str(exc),
        }
        if args.json:
            print(json.dumps(error, indent=2))
        else:
            print(
                f"RAG provider error [{exc.provider}/{exc.category}]: {exc}",
                file=sys.stderr,
            )
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    hits = result["hits"]

    if args.rag:
        if result.get("answer") is None:
            print("No accessible documents found for this question.")
            return
        print(f"\nAnswer: {result['answer']}\n")
        print("Sources:")
        for i, src in enumerate(hits, 1):
            print(f"  [{i}] {_hit_label(src)}")
        return

    # Search-only (default): ranked, permission-enforced hits.
    if not hits:
        print("No accessible documents found for this question.")
        return
    print(f"\n{len(hits)} result(s):\n")
    for i, src in enumerate(hits, 1):
        print(f"  [{i}] {_hit_label(src)}")
        if src.get("snippet"):
            print(f"      {src['snippet']}")


def _hit_label(src: dict) -> str:
    return (src.get("title") or src.get("source_file")
            or src.get("path") or f"chunk {src.get('chunk_id', 0)}")


def _audit_eval_user(config, username, password, client_factory):
    client = client_factory(config, username, password)
    authinfo = client.transport.perform_request(
        "GET", "/_plugins/_security/authinfo"
    )
    index = config["opensearch"]["index"]
    permission_check = client.transport.perform_request(
        "PUT",
        f"/{index}/_doc/__permission_check",
        params={"perform_permission_check": "true"},
        body={"probe": True},
    )
    roles = sorted(authinfo.get("roles", []))
    expected_role = f"{index}-reader"
    return {
        "user": username,
        "authenticated_user": authinfo.get("user_name"),
        "roles": roles,
        "expected_role_assigned": expected_role in roles,
        "write_blocked": permission_check.get("accessAllowed") is False,
    }


def cmd_eval_dls(args, runner_factory=None, client_factory=None):
    if runner_factory is None:
        from lib.search_runner import SearchRunner
        runner_factory = SearchRunner
    if client_factory is None:
        from lib.os_client import build_app_client
        client_factory = build_app_client

    config = _runtime_config(args)
    shared_password = getattr(args, "password", None)
    allowed_password = (
        getattr(args, "allowed_password", None)
        or os.getenv("PERMISSION_SEARCH_ALLOWED_PASSWORD")
        or shared_password
        or _derive_test_password(args.allowed_user)
    )
    forbidden_password = (
        getattr(args, "forbidden_password", None)
        or os.getenv("PERMISSION_SEARCH_FORBIDDEN_PASSWORD")
        or shared_password
        or _derive_test_password(args.forbidden_user)
    )

    allowed_runner = runner_factory(
        config, username=args.allowed_user, password=allowed_password
    )
    forbidden_runner = runner_factory(
        config, username=args.forbidden_user, password=forbidden_password
    )

    allowed_hit = allowed_runner.find_document(args.document_id)
    forbidden_hit = forbidden_runner.find_document(args.document_id)
    user_checks = [
        _audit_eval_user(
            config, args.allowed_user, allowed_password, client_factory
        ),
        _audit_eval_user(
            config, args.forbidden_user, forbidden_password, client_factory
        ),
    ]

    user_checks_pass = all(
        check["authenticated_user"] == check["user"]
        and check["expected_role_assigned"]
        and check["write_blocked"]
        for check in user_checks
    )
    passed = bool(allowed_hit and not forbidden_hit and user_checks_pass)
    print(json.dumps({
        "allowed_user_sees_document": allowed_hit,
        "forbidden_user_sees_document": forbidden_hit,
        "effective_user_checks": user_checks,
        "pass": passed,
    }, indent=2))
    if not passed:
        sys.exit(1)


def cmd_benchmark(args):
    password = _required_user_password(args)
    from lib.search_runner import SearchRunner

    config = _runtime_config(args)
    runner = SearchRunner(config, username=args.user, password=password)

    sample_questions = [
        "What are the main objectives of this project?",
        "Who is responsible for the quarterly review?",
        "What is the budget allocation for next year?",
        "Summarize the key risks identified in the report.",
        "What is the approval process for new vendors?",
    ]
    n = args.queries
    questions = (sample_questions * ((n // len(sample_questions)) + 1))[:n]

    latencies = []
    for q in questions:
        t0 = time.monotonic()
        runner.query(question=q, top_k=5, rag=False)
        latencies.append((time.monotonic() - t0) * 1000)

    latencies.sort()
    p50 = latencies[int(len(latencies) * 0.50)]
    p99 = latencies[max(0, int(len(latencies) * 0.99) - 1)]
    print(json.dumps({
        "p50_ms": round(p50), "p99_ms": round(p99),
        "min_ms": round(min(latencies)), "max_ms": round(max(latencies)),
    }, indent=2))


# -- helpers ------------------------------------------------------------------

def _runtime_config(args) -> dict:
    host = os.getenv("OPENSEARCH_HOST", "localhost")
    port = os.getenv("OPENSEARCH_PORT", "9200")
    scheme = os.getenv("OPENSEARCH_SCHEME", "https")
    url = _setting(
        args, "opensearch_url", "OPENSEARCH_URL", f"{scheme}://{host}:{port}"
    )
    index = _setting(
        args, "index", "OPENSEARCH_INDEX", "permission-aware-search"
    )
    if not str(url).strip() or not str(index).strip():
        raise ConfigurationError("OpenSearch URL and index must not be empty.")

    embedding_mode = _setting(
        args, "embedding_mode", "PERMISSION_SEARCH_EMBEDDING_MODE", "local"
    )
    if embedding_mode not in ("local", "none"):
        raise ConfigurationError("Embedding mode must be 'local' or 'none'.")

    chunk_size = _int_setting(
        args, "chunk_size", "PERMISSION_SEARCH_CHUNK_SIZE", 512, minimum=1
    )
    chunk_overlap = _int_setting(
        args, "chunk_overlap", "PERMISSION_SEARCH_CHUNK_OVERLAP", 64, minimum=0
    )
    if chunk_overlap >= chunk_size:
        raise ConfigurationError("Chunk overlap must be smaller than chunk size.")

    llm_provider = _setting(
        args, "llm_provider", "PERMISSION_SEARCH_LLM_PROVIDER", "openai_compatible"
    )
    if llm_provider not in (
        "openai_compatible", "dmr", "bedrock", "none", "disabled"
    ):
        raise ConfigurationError(f"Unsupported LLM provider: {llm_provider!r}.")

    config = {
        "opensearch": {
            "url": str(url),
            "admin_username": os.getenv("OPENSEARCH_USER", "admin"),
            "admin_password": os.getenv(
                "OPENSEARCH_PASSWORD", "myStrongPassword123!"
            ),
            "ssl_verify": _bool_setting(
                args, "ssl_verify", "OPENSEARCH_SSL_VERIFY", False
            ),
            "index": str(index),
        },
        "embedding": {
            "mode": embedding_mode,
            "model": _setting(
                args,
                "embedding_model",
                "PERMISSION_SEARCH_EMBEDDING_MODEL",
                "huggingface/sentence-transformers/all-MiniLM-L6-v2",
            ),
            "dimension": _int_setting(
                args,
                "embedding_dimension",
                "PERMISSION_SEARCH_EMBEDDING_DIMENSION",
                384,
                minimum=1,
            ),
        },
        "chunking": {
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
        },
        "llm": {
            "provider": llm_provider,
            "base_url": _setting(
                args,
                "llm_url",
                "PERMISSION_SEARCH_LLM_URL",
                "http://localhost:12434/engines/v1",
            ),
            "model": _setting(
                args, "llm_model", "PERMISSION_SEARCH_LLM_MODEL", "ai/smollm2"
            ),
            "max_tokens": _int_setting(
                args,
                "llm_max_tokens",
                "PERMISSION_SEARCH_LLM_MAX_TOKENS",
                1024,
                minimum=1,
            ),
            "timeout": _int_setting(
                args,
                "llm_timeout",
                "PERMISSION_SEARCH_LLM_TIMEOUT",
                120,
                minimum=1,
            ),
            "model_id": _setting(
                args,
                "bedrock_model_id",
                "PERMISSION_SEARCH_BEDROCK_MODEL_ID",
                "anthropic.claude-3-haiku-20240307-v1:0",
            ),
            "region": _setting(
                args, "bedrock_region", "AWS_REGION", "us-east-1"
            ),
        },
    }
    if getattr(args, "command", None) == "refresh-acl":
        config["directory"] = _directory_config(args)
    return config


def _setting(args, argument: str, environment: str, default):
    value = getattr(args, argument, None)
    if value is not None:
        return value
    return os.getenv(environment, default)


def _int_setting(
    args, argument: str, environment: str, default: int, *, minimum: int
) -> int:
    value = _setting(args, argument, environment, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{environment} must be an integer.") from exc
    if parsed < minimum:
        raise ConfigurationError(f"{environment} must be at least {minimum}.")
    return parsed


def _bool_setting(args, argument: str, environment: str, default: bool) -> bool:
    value = getattr(args, argument, None)
    if value is not None:
        return value
    raw = os.getenv(environment)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise ConfigurationError(
        f"{environment} must be true/false, yes/no, on/off, or 1/0."
    )


def _derive_test_password(username: str) -> str:
    # Convention password for demo/eval-dls users. Must NOT contain the username -
    # the security plugin rejects passwords that are "similar to user name".
    return "Demo-Passw0rd-1!"


def _required_user_password(args) -> str:
    password = getattr(args, "password", None) or os.getenv(
        "PERMISSION_SEARCH_USER_PASSWORD"
    )
    if not password:
        raise ConfigurationError(
            "Provide --password or set PERMISSION_SEARCH_USER_PASSWORD."
        )
    return password


def _directory_config(args) -> dict:
    file_path = _setting(args, "file", "PERMISSION_SEARCH_GROUPS_FILE", "")
    if not file_path:
        raise ConfigurationError(
            "refresh-acl requires --file or PERMISSION_SEARCH_GROUPS_FILE."
        )
    return {"source": "file", "file": {"path": file_path}}


def _extract_text(path: str) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".md"):
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    if ext in (".pdf", ".docx", ".pptx", ".xlsx"):
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise _optional_dependency_error(
                "docling", "PDF and Office document ingestion"
            ) from exc
        try:
            result = DocumentConverter().convert(path)
            return result.document.export_to_markdown()
        except Exception as exc:
            raise ExtractionError(os.path.basename(path), type(exc).__name__) from exc
    return None


def _add_opensearch_arguments(parser):
    parser.add_argument(
        "--opensearch-url",
        help="Override OPENSEARCH_URL (default: https://OPENSEARCH_HOST:OPENSEARCH_PORT)",
    )
    parser.add_argument(
        "--index",
        help="Override OPENSEARCH_INDEX (default: permission-aware-search)",
    )
    parser.add_argument(
        "--ssl-verify",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Override OPENSEARCH_SSL_VERIFY",
    )


def _add_embedding_arguments(parser):
    parser.add_argument("--embedding-mode", choices=["local", "none"])
    parser.add_argument("--embedding-model")
    parser.add_argument("--embedding-dimension", type=_positive_int)


def _add_llm_arguments(parser):
    parser.add_argument(
        "--llm-provider",
        choices=["openai_compatible", "dmr", "bedrock", "none", "disabled"],
    )
    parser.add_argument("--llm-url")
    parser.add_argument("--llm-model")
    parser.add_argument("--llm-max-tokens", type=_positive_int)
    parser.add_argument("--llm-timeout", type=_positive_int)
    parser.add_argument("--bedrock-model-id")
    parser.add_argument("--bedrock-region")


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _build_parser():
    parser = argparse.ArgumentParser(
        description="permission-aware-search: permission-enforced search with optional RAG, using OpenSearch DLS"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check-security")
    _add_opensearch_arguments(p)

    p = sub.add_parser("check-llm",
        help="Check reachability of the optional RAG LLM endpoint")
    _add_llm_arguments(p)

    p = sub.add_parser("setup")
    _add_opensearch_arguments(p)
    _add_embedding_arguments(p)
    p.add_argument("--recreate", action="store_true")

    p = sub.add_parser("create-users",
        help="Create OpenSearch users mapped to the reader role (for demos and eval-dls)")
    _add_opensearch_arguments(p)
    p.add_argument("--users", required=True,
                   help="Comma-separated usernames, e.g. alice,bob,carol")
    p.add_argument("--password",
                   help="Password for all users (default: Test-<User>-1! convention)")

    p = sub.add_parser("ingest")
    _add_opensearch_arguments(p)
    _add_embedding_arguments(p)
    p.add_argument("--input", required=True)
    p.add_argument("--acl-file")
    p.add_argument("--batch-size", type=_positive_int, default=50)
    p.add_argument("--chunk-size", type=_positive_int)
    p.add_argument("--chunk-overlap", type=_non_negative_int)

    p = sub.add_parser("sync-acl")
    _add_opensearch_arguments(p)
    p.add_argument("--acl-file", required=True)

    p = sub.add_parser("refresh-acl",
        help="Rebuild the ACL lookup index from a group->members file")
    _add_opensearch_arguments(p)
    p.add_argument("--file", metavar="PATH",
                   help="Path to a group->members JSON file")

    p = sub.add_parser("query")
    _add_opensearch_arguments(p)
    _add_embedding_arguments(p)
    _add_llm_arguments(p)
    p.add_argument("--question", required=True)
    p.add_argument("--top-k", type=_positive_int, default=5)
    p.add_argument("--user", required=True,
                   help="Authenticated end user whose DLS permissions are enforced")
    p.add_argument("--password",
                   help="OpenSearch password for --user; prefer "
                        "PERMISSION_SEARCH_USER_PASSWORD")
    p.add_argument("--rag", action="store_true",
                   help="Generate an LLM answer from the permitted results "
                        "(default: return ranked hits only)")
    p.add_argument("--json", action="store_true",
                   help="Emit structured JSON instead of formatted text")

    p = sub.add_parser("eval-dls")
    _add_opensearch_arguments(p)
    p.add_argument("--allowed-user", required=True)
    p.add_argument("--forbidden-user", required=True)
    p.add_argument("--document-id", required=True)
    p.add_argument("--password", help="Password for test users (optional, uses convention if omitted)")
    p.add_argument("--allowed-password",
                   help="Password for --allowed-user; prefer "
                        "PERMISSION_SEARCH_ALLOWED_PASSWORD")
    p.add_argument("--forbidden-password",
                   help="Password for --forbidden-user; prefer "
                        "PERMISSION_SEARCH_FORBIDDEN_PASSWORD")

    p = sub.add_parser("benchmark")
    _add_opensearch_arguments(p)
    _add_embedding_arguments(p)
    p.add_argument("--queries", type=_positive_int, default=20)
    p.add_argument("--user", required=True,
                   help="Authenticated end user whose DLS permissions are enforced")
    p.add_argument("--password",
                   help="OpenSearch password for --user; prefer "
                        "PERMISSION_SEARCH_USER_PASSWORD")

    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    dispatch = {
        "check-security": cmd_check_security,
        "check-llm":      cmd_check_llm,
        "setup":          cmd_setup,
        "create-users":   cmd_create_users,
        "ingest":         cmd_ingest,
        "sync-acl":       cmd_sync_acl,
        "refresh-acl":    cmd_refresh_acl,
        "query":          cmd_query,
        "eval-dls":       cmd_eval_dls,
        "benchmark":      cmd_benchmark,
    }
    try:
        dispatch[args.command](args)
    except (ConfigurationError, OptionalDependencyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
