#!/usr/bin/env python3
"""LeadFinder Ops — OpenSearch-backed lead search & recovery CLI.

Subcommands:
  doctor   — verify cluster reachable and index present
  init     — create the `leads` index with k-NN mapping
  missed   — list unanswered leads in a time window
  search   — hybrid BM25 + keyword search over lead messages
  report   — owner summary for a time window

Usage:
  uv run python scripts/leadsearch.py doctor
  uv run python scripts/leadsearch.py init
  uv run python scripts/leadsearch.py missed --window 30d
  uv run python scripts/leadsearch.py search "unanswered quote request water heater"
  uv run python scripts/leadsearch.py report --window 30d

Environment:
  OS_URL      — OpenSearch endpoint (default http://localhost:9200)
  OS_USER     — auth user (default admin)
  OS_PASSWORD — auth password (default admin)

No external dependencies: uses urllib from the standard library so the skill
runs anywhere Python 3.11+ runs.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import base64
from datetime import datetime, timedelta, timezone

OS_URL = os.environ.get("OS_URL", "http://localhost:9200")
OS_USER = os.environ.get("OS_USER", "admin")
OS_PASSWORD = os.environ.get("OS_PASSWORD", "admin")
INDEX = "leads"

INDEX_BODY = {
    "settings": {"index.knn": True},
    "mappings": {
        "properties": {
            "lead_id": {"type": "keyword"},
            "received_at": {"type": "date"},
            "source": {"type": "keyword"},
            "customer_name": {"type": "text"},
            "contact": {"type": "keyword"},
            "message": {"type": "text"},
            "message_embedding": {
                "type": "knn_vector",
                "dimension": 384,
                "method": {"name": "hnsw", "space_type": "cosinesimil", "engine": "nmslib"},
            },
            "category": {"type": "keyword"},
            "responded_at": {"type": "date"},
            "response_channel": {"type": "keyword"},
            "next_action": {"type": "keyword"},
        }
    },
}


def _req(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    url = f"{OS_URL}/{path.lstrip('/')}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    token = base64.b64encode(f"{OS_USER}:{OS_PASSWORD}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            parsed = json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            parsed = {}
        return e.code, parsed
    except urllib.error.URLError as e:
        return 0, {"error": f"connection failed: {e.reason}"}


def parse_window(window: str) -> datetime:
    """Parse '30d', '72h', '15m' into an aware UTC datetime."""
    unit = window[-1]
    n = int(window[:-1])
    delta = {"d": timedelta(days=n), "h": timedelta(hours=n), "m": timedelta(minutes=n)}[unit]
    return datetime.now(timezone.utc) - delta


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_doctor() -> int:
    code, info = _req("GET", "/")
    ok = code == 200
    print(f"cluster: {'UP' if ok else 'UNREACHABLE'} ({code})")
    if ok:
        print(f"version: {info.get('version', {}).get('number', '?')}")
    code, idx = _req("GET", f"/{INDEX}")
    if code == 200:
        print(f"index '{INDEX}': present")
        return 0
    print(f"index '{INDEX}': MISSING — run `init`")
    return 1 if ok else 2


def cmd_init() -> int:
    code, body = _req("PUT", f"/{INDEX}", INDEX_BODY)
    if code in (200, 201):
        print(f"created index '{INDEX}' with k-NN mapping (dimension 384)")
        return 0
    if code == 400 and "resource_already_exists" in str(body):
        print(f"index '{INDEX}' already exists")
        return 0
    print(f"create failed ({code}): {body}")
    return 1


def cmd_missed(window: str, emergency: bool) -> int:
    must = [
        {"range": {"received_at": {"gte": iso(parse_window(window))}}},
        {"bool": {"must_not": {"exists": {"field": "responded_at"}}}},
    ]
    if emergency:
        must.append({"term": {"category": "urgent"}})
    q = {
        "size": 50,
        "sort": [{"received_at": "asc"}],
        "query": {"bool": {"must": must}},
        "_source": ["lead_id", "received_at", "source", "customer_name", "contact", "message", "category"],
    }
    code, body = _req("POST", f"/{INDEX}/_search", q)
    if code != 200:
        print(f"search failed ({code}): {body}")
        return 1
    hits = body.get("hits", {}).get("hits", [])
    total = body.get("hits", {}).get("total", {}).get("value", 0)
    print(f"unanswered leads in last {window}: {total}")
    for h in hits:
        s = h["_source"]
        received = datetime.strptime(s["received_at"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - received).days
        flag = " \u26a0\ufe0f URGENT" if s.get("category") == "urgent" else ""
        print(f"  [{s['received_at'][:10]}] {s.get('customer_name','?'):20s} {s.get('source','?'):12s} "
              f"{age_days}d old{flag}\n    {s.get('message','')[:100]}")
    if not hits:
        print("  (none — every lead has a response on record)")
    return 0


def cmd_search(text: str, size: int) -> int:
    q = {
        "size": size,
        "query": {
            "bool": {
                "should": [
                    {"match": {"message": {"query": text, "boost": 1.0}}},
                    {"match": {"customer_name": {"query": text, "boost": 0.5}}},
                ],
                "minimum_should_match": 1,
            }
        },
        "_source": ["lead_id", "received_at", "customer_name", "message", "category", "responded_at"],
    }
    code, body = _req("POST", f"/{INDEX}/_search", q)
    if code != 200:
        print(f"search failed ({code}): {body}")
        return 1
    hits = body.get("hits", {}).get("hits", [])
    print(f"matches for '{text}': {len(hits)}")
    for h in hits:
        s = h["_source"]
        answered = "answered" if s.get("responded_at") else "UNANSWERED"
        print(f"  ({h['_score']:.1f}) [{s['received_at'][:10]}] {s.get('customer_name','?'):20s} "
              f"{s.get('category','?'):12s} {answered}\n    {s.get('message','')[:100]}")
    return 0


def cmd_report(window: str) -> int:
    since = iso(parse_window(window))
    aggs = {
        "by_category": {"terms": {"field": "category", "size": 10}},
        "unanswered": {
            "filter": {"bool": {"must": [{"range": {"received_at": {"gte": since}}},
                                          {"bool": {"must_not": {"exists": {"field": "responded_at"}}}}]}}
        },
        "oldest_unanswered": {
            "min": {"field": "received_at", "missing": None}
        },
    }
    q = {"size": 0, "query": {"range": {"received_at": {"gte": since}}}, "aggs": aggs}
    code, body = _req("POST", f"/{INDEX}/_search", q)
    if code != 200:
        print(f"report failed ({code}): {body}")
        return 1
    a = body.get("aggregations", {})
    total = body.get("hits", {}).get("total", {}).get("value", 0)
    unanswered = a.get("unanswered", {}).get("doc_count", 0)
    print(f"Lead report — last {window} (generated {datetime.now(timezone.utc).isoformat()[:19]}Z)")
    print(f"  total leads: {total}")
    print(f"  unanswered:  {unanswered}")
    print("  by category:")
    for b in a.get("by_category", {}).get("buckets", []):
        print(f"    {b['key']:18s} {b['doc_count']}")
    if total:
        pct = 100.0 * unanswered / total
        print(f"  recovery rate: {100 - pct:.0f}% answered")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="leadsearch.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="verify cluster and index")
    sub.add_parser("init", help="create leads index with k-NN mapping")
    sp = sub.add_parser("missed", help="list unanswered leads")
    sp.add_argument("--window", default="30d", help="e.g. 30d, 72h, 15m")
    sp.add_argument("--min-value", default="", help="set to 'emergency' to filter urgent only")
    sp = sub.add_parser("search", help="search lead messages")
    sp.add_argument("text")
    sp.add_argument("--size", type=int, default=10)
    sp = sub.add_parser("report", help="owner summary")
    sp.add_argument("--window", default="30d")
    args = p.parse_args()
    if args.cmd == "doctor":
        return cmd_doctor()
    if args.cmd == "init":
        return cmd_init()
    if args.cmd == "missed":
        return cmd_missed(args.window, args.min_value == "emergency")
    if args.cmd == "search":
        return cmd_search(args.text, args.size)
    if args.cmd == "report":
        return cmd_report(args.window)
    return 1


if __name__ == "__main__":
    sys.exit(main())
