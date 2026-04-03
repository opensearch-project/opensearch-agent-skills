#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["opensearch-py>=2.4", "boto3>=1.28"]
# ///
"""Standalone CLI for OpenSearch operations.

No dependency on the opensearch-mcp-server or opensearch_orchestrator.
Uses opensearch-py directly via the lib/ modules in this directory.

Usage:
    uv run python scripts/opensearch_ops.py <command> [options]

Commands:
    status                 Check OpenSearch connectivity
    preflight-check        Check if OpenSearch cluster is already running
    create-index           Create an index with mappings
    deploy-model           Deploy a local pretrained ML model
    deploy-bedrock         Register a Bedrock embedding model
    create-pipeline        Create and attach an ingest/search pipeline
    index-doc              Index a single document
    index-bulk             Bulk index documents from sample data
    launch-ui              Launch the Search Builder UI
    connect-ui             Connect Search UI to a remote endpoint
    search                 Run a search query
    load-sample            Load sample data (file, URL, builtin IMDB)
    cleanup                Stop UI and clean up
    read-knowledge         Read a knowledge base reference file
    deploy-agentic-model   Deploy a Bedrock Claude model for agentic search
    create-flow-agent      Create a flow agent for agentic search (stateless)
    create-conversational-agent Create a conversational agent with memory (multi-turn)
    create-agentic-pipeline Create and attach an agentic search pipeline
    search-docs            Search documentation via DuckDuckGo (default: opensearch.org)
"""

import argparse
import json
import os
import sys

# Ensure the scripts directory is on sys.path for lib/ imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def cmd_status(args):
    from lib.client import create_client, can_connect, build_client, resolve_http_auth
    try:
        http_auth = resolve_http_auth()
        for use_ssl in (True, False):
            client = build_client(use_ssl=use_ssl, http_auth=http_auth)
            ok, _ = can_connect(client)
            if ok:
                proto = "https" if use_ssl else "http"
                print(json.dumps({"reachable": True, "endpoint": f"{proto}://localhost:9200"}))
                return
        print(json.dumps({"reachable": False}))
    except Exception as e:
        print(json.dumps({"reachable": False, "error": str(e)}))


def cmd_preflight_check(args):
    from lib.client import preflight_check_cluster
    result = preflight_check_cluster(
        auth_mode=args.auth_mode or "",
        username=args.username or "",
        password=args.password or "",
    )
    print(json.dumps(result, indent=2))


def cmd_create_index(args):
    from lib.operations import create_index
    body = json.loads(args.body) if args.body else {}
    print(create_index(args.name, body, args.replace))


def cmd_deploy_model(args):
    from lib.operations import deploy_local_model
    print(deploy_local_model(args.name))


def cmd_deploy_bedrock(args):
    from lib.operations import deploy_bedrock_model
    print(deploy_bedrock_model(args.name))


def cmd_create_pipeline(args):
    from lib.operations import create_pipeline
    body = json.loads(args.body) if args.body else {}
    print(create_pipeline(
        pipeline_name=args.name,
        pipeline_body=body,
        index_name=args.index,
        pipeline_type=args.type,
        is_hybrid=args.hybrid,
        hybrid_weights=json.loads(args.weights) if args.weights else None,
    ))


def cmd_index_doc(args):
    from lib.operations import index_doc
    doc = json.loads(args.doc)
    print(index_doc(args.index, doc, args.id))


def cmd_index_bulk(args):
    from lib.samples import _load_records_from_file
    from lib.operations import index_bulk
    from pathlib import Path

    if args.source_file:
        records, err = _load_records_from_file(Path(args.source_file), limit=args.count)
        if err:
            print(json.dumps({"error": err}))
            return
    else:
        print(json.dumps({"error": "Provide --source-file for bulk indexing."}))
        return

    print(index_bulk(args.index, records[:args.count], id_prefix="verification"))


def cmd_launch_ui(args):
    from lib import client as client_lib
    from lib.ui import launch_ui

    user = (getattr(args, "username", None) or "").strip()
    pwd = (getattr(args, "password", None) or "").strip()
    if user and pwd:
        os.environ[client_lib.OPENSEARCH_AUTH_MODE_ENV] = client_lib.OPENSEARCH_AUTH_MODE_CUSTOM
        os.environ[client_lib.OPENSEARCH_USER_ENV] = user
        os.environ[client_lib.OPENSEARCH_PASSWORD_ENV] = pwd

    result = launch_ui(args.index or "")
    print(result)
    if "started" in result.lower() or "running" in result.lower():
        # Keep process alive while UI is running
        try:
            print("Press Ctrl+C to stop the UI server.", file=sys.stderr)
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping UI server.", file=sys.stderr)


def cmd_connect_ui(args):
    from lib.ui import connect_ui
    print(connect_ui(
        endpoint=args.endpoint,
        port=args.port,
        use_ssl=not args.no_ssl,
        username=args.username or "",
        password=args.password or "",
        aws_region=args.aws_region or "",
        aws_service=args.aws_service or "",
        index_name=args.index or "",
    ))


def cmd_search(args):
    from lib.client import create_client
    from lib.operations import search
    client = create_client()
    body = json.loads(args.body) if args.body else None
    result = search(client, args.index, body, args.size)
    print(json.dumps(result, default=str, ensure_ascii=False, indent=2))


def cmd_load_sample(args):
    from lib.samples import (
        load_sample_builtin_imdb,
        load_sample_from_file,
        load_sample_from_url,
        load_sample_from_index,
        load_sample_from_paste,
    )
    dispatch = {
        "builtin_imdb": lambda: load_sample_builtin_imdb(),
        "local_file": lambda: load_sample_from_file(args.value),
        "url": lambda: load_sample_from_url(args.value),
        "localhost_index": lambda: load_sample_from_index(args.value),
        "paste": lambda: load_sample_from_paste(args.value),
    }
    fn = dispatch.get(args.type)
    if fn:
        print(fn())
    else:
        print(json.dumps({"error": f"Unknown source type: {args.type}"}))


def cmd_cleanup(args):
    from lib.ui import cleanup_ui
    print(cleanup_ui())


def cmd_read_knowledge(args):
    knowledge_dir = os.path.join(
        os.path.dirname(__file__), "..", "references", "knowledge"
    )
    target = os.path.join(knowledge_dir, args.file)
    if not os.path.isfile(target):
        available = os.listdir(knowledge_dir) if os.path.isdir(knowledge_dir) else []
        print(f"File not found: {args.file}. Available: {available}", file=sys.stderr)
        sys.exit(1)
    with open(target) as f:
        print(f.read())


def cmd_deploy_agentic_model(args):
    from lib.operations import deploy_agentic_model
    result = deploy_agentic_model(
        access_key=args.access_key or os.getenv("AWS_ACCESS_KEY_ID", ""),
        secret_key=args.secret_key or os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        region=args.region,
        session_token=args.session_token or os.getenv("AWS_SESSION_TOKEN", ""),
        model_name=args.model_name,
    )
    print(result)


def cmd_search_docs(args):
    """Search documentation via DuckDuckGo with site restriction."""
    import re as _re
    from html import unescape
    from urllib.parse import parse_qs, quote_plus, urlparse
    from urllib.request import Request, urlopen

    def _strip_html(text):
        return _re.sub(r"<[^>]+>", "", text)

    def _normalize_text(text):
        return _re.sub(r"\s+", " ", text).strip()

    def _decode_redirect(url):
        parsed = urlparse(url)
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            target = parse_qs(parsed.query).get("uddg", [None])[0]
            if target:
                return target
        return url

    try:
        query = args.query
        site = args.site
        limit = max(1, min(args.count, 10))
        site_prefix = f"site:{site} " if site else ""
        search_query = quote_plus(f"{site_prefix}{query}")
        url = f"https://duckduckgo.com/html/?q={search_query}"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; OpenSearchSkill/1.0)"})

        with urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        titles = _re.findall(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            html, flags=_re.IGNORECASE | _re.DOTALL,
        )
        snippets_raw = _re.findall(
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>|'
            r'<div[^>]*class="result__snippet"[^>]*>(.*?)</div>',
            html, flags=_re.IGNORECASE | _re.DOTALL,
        )
        snippets = [left or right for left, right in snippets_raw]

        filter_domain = site.lower() if site else None
        results = []
        for idx, (raw_href, raw_title) in enumerate(titles):
            href = _decode_redirect(unescape(raw_href))
            if filter_domain and filter_domain not in urlparse(href).netloc.lower():
                continue
            title = _normalize_text(unescape(_strip_html(raw_title)))
            snippet = ""
            if idx < len(snippets):
                snippet = _normalize_text(unescape(_strip_html(snippets[idx])))
            results.append({"title": title, "url": href, "snippet": snippet})
            if len(results) >= limit:
                break

        print(json.dumps({"query": query, "site": site, "results": results}, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"query": args.query, "site": args.site, "results": [], "error": str(e)}))


def cmd_create_flow_agent(args):
    from lib.operations import create_flow_agent
    print(create_flow_agent(args.name, args.model_id))


def cmd_create_conversational_agent(args):
    from lib.operations import create_conversational_agent
    print(create_conversational_agent(args.name, args.model_id, args.max_iterations))


def cmd_compare_ui(args):
    from lib.ui import set_comparison_mode, launch_ui
    result = set_comparison_mode(args.baseline, args.improved)
    print(result)
    if "Error" in result or "required" in result.lower():
        sys.exit(1)
    ui_result = launch_ui(args.improved)
    print(ui_result)
    if "started" in ui_result.lower() or "running" in ui_result.lower():
        try:
            print("Press Ctrl+C to stop the UI server.", file=sys.stderr)
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping UI server.", file=sys.stderr)





def cmd_create_agentic_pipeline(args):
    from lib.operations import create_agentic_pipeline
    print(create_agentic_pipeline(args.name, args.agent_id, args.index))


def main():
    parser = argparse.ArgumentParser(description="OpenSearch operations CLI (standalone)", allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)

    # status
    sub.add_parser("status", help="Check OpenSearch connectivity")

    # preflight-check
    p = sub.add_parser("preflight-check", help="Check if OpenSearch cluster is already running")
    p.add_argument("--auth-mode", default="", choices=["", "none", "default", "custom"],
                   help="Authentication mode: auto-detect (default), none, default, or custom")
    p.add_argument("--username", default="", help="Username for custom auth mode")
    p.add_argument("--password", default="", help="Password for custom auth mode")

    # create-index
    p = sub.add_parser("create-index", help="Create an index")
    p.add_argument("--name", required=True)
    p.add_argument("--body", default="{}", help="JSON index body")
    p.add_argument("--replace", action="store_true", default=True)

    # deploy-model
    p = sub.add_parser("deploy-model", help="Deploy a local pretrained model")
    p.add_argument("--name", required=True)

    # deploy-bedrock
    p = sub.add_parser("deploy-bedrock", help="Register a Bedrock embedding model")
    p.add_argument("--name", required=True)

    # create-pipeline
    p = sub.add_parser("create-pipeline", help="Create and attach a pipeline")
    p.add_argument("--name", required=True)
    p.add_argument("--body", default="{}", help="JSON pipeline body")
    p.add_argument("--index", required=True)
    p.add_argument("--type", default="ingest", choices=["ingest", "search"])
    p.add_argument("--hybrid", action="store_true")
    p.add_argument("--weights", default=None, help="JSON [lexical, semantic]")

    # index-doc
    p = sub.add_parser("index-doc", help="Index a single document")
    p.add_argument("--index", required=True)
    p.add_argument("--doc", required=True, help="JSON document")
    p.add_argument("--id", required=True)

    # index-bulk
    p = sub.add_parser("index-bulk", help="Bulk index docs from a file")
    p.add_argument("--index", required=True)
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--source-file", required=True, help="Local file path")

    # launch-ui
    p = sub.add_parser("launch-ui", help="Launch Search Builder UI")
    p.add_argument("--index", default="")
    p.add_argument(
        "--username",
        default="",
        help="OpenSearch username (sets custom auth for this process; same as OPENSEARCH_USER)",
    )
    p.add_argument(
        "--password",
        default="",
        help="OpenSearch password (sets custom auth for this process; same as OPENSEARCH_PASSWORD)",
    )

    # connect-ui
    p = sub.add_parser("connect-ui", help="Connect UI to remote endpoint")
    p.add_argument("--endpoint", required=True)
    p.add_argument("--port", type=int, default=443)
    p.add_argument("--no-ssl", action="store_true")
    p.add_argument("--username", default="")
    p.add_argument("--password", default="")
    p.add_argument("--aws-region", default="")
    p.add_argument("--aws-service", default="")
    p.add_argument("--index", default="")

    # search
    p = sub.add_parser("search", help="Run a search query")
    p.add_argument("--index", required=True)
    p.add_argument("--body", default=None, help="JSON search body")
    p.add_argument("--size", type=int, default=10)

    # load-sample
    p = sub.add_parser("load-sample", help="Load sample documents")
    p.add_argument("-t", "--type", required=True,
                    choices=["builtin_imdb", "local_file", "url", "localhost_index", "paste"])
    p.add_argument("-v", "--value", default="")

    # cleanup
    sub.add_parser("cleanup", help="Stop UI and clean up")

    # read-knowledge
    p = sub.add_parser("read-knowledge", help="Read a knowledge base file")
    p.add_argument("--file", required=True)

    # deploy-agentic-model
    p = sub.add_parser("deploy-agentic-model", help="Deploy Bedrock Claude for agentic search")
    p.add_argument("--access-key", default="")
    p.add_argument("--secret-key", default="")
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--session-token", default="")
    p.add_argument("--model-name", default="us.anthropic.claude-sonnet-4-20250514-v1:0")

    # compare-ui
    p = sub.add_parser("compare-ui", help="Launch Search Builder UI in comparison mode")
    p.add_argument("--baseline", required=True, help="Baseline index name (before evaluation)")
    p.add_argument("--improved", required=True, help="Improved index name (after evaluation)")

    # create-flow-agent
    p = sub.add_parser("create-flow-agent", help="Create a flow agent for agentic search (stateless)")
    p.add_argument("--name", required=True)
    p.add_argument("--model-id", required=True)

    # create-conversational-agent
    p = sub.add_parser("create-conversational-agent", help="Create a conversational agent with memory (multi-turn)")
    p.add_argument("--name", required=True, help="Agent name")
    p.add_argument("--model-id", required=True, help="Deployed LLM model ID")
    p.add_argument("--max-iterations", type=int, default=10, help="Max LLM iterations (default: 10)")

    # search-docs
    p = sub.add_parser("search-docs", help="Search documentation via DuckDuckGo")
    p.add_argument("--query", required=True, help="Search query")
    p.add_argument("--site", default="opensearch.org", help="Site to restrict search to (default: opensearch.org)")
    p.add_argument("--count", type=int, default=5, help="Max results (1-10)")

    # create-agentic-pipeline
    p = sub.add_parser("create-agentic-pipeline", help="Create agentic search pipeline")
    p.add_argument("--name", required=True)
    p.add_argument("--agent-id", required=True)
    p.add_argument("--index", required=True)

    args = parser.parse_args()

    dispatch = {
        "status": cmd_status,
        "preflight-check": cmd_preflight_check,
        "create-index": cmd_create_index,
        "deploy-model": cmd_deploy_model,
        "deploy-bedrock": cmd_deploy_bedrock,
        "create-pipeline": cmd_create_pipeline,
        "index-doc": cmd_index_doc,
        "index-bulk": cmd_index_bulk,
        "launch-ui": cmd_launch_ui,
        "connect-ui": cmd_connect_ui,
        "compare-ui": cmd_compare_ui,
        "search": cmd_search,
        "load-sample": cmd_load_sample,
        "cleanup": cmd_cleanup,
        "read-knowledge": cmd_read_knowledge,
        "deploy-agentic-model": cmd_deploy_agentic_model,
        "create-flow-agent": cmd_create_flow_agent,
        "create-conversational-agent": cmd_create_conversational_agent,
        "create-agentic-pipeline": cmd_create_agentic_pipeline,
        "search-docs": cmd_search_docs,
    }

    fn = dispatch.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
