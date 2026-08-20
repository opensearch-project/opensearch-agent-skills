"""Sample data loading for OpenSearch search builder."""

import csv
import json
import os
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .client import create_client
from .http_safe import (
    RevalidatingRedirectHandler,
    ValidatingHTTPConnection,
    ValidatingHTTPHandler,
    ValidatingHTTPSConnection,
    ValidatingHTTPSHandler,
    build_safe_opener,
    is_restricted_ip,
    validate_url,
)


def _load_records_from_file(file_path: Path, limit: int = 10) -> tuple[list[dict], str | None]:
    suffix = file_path.suffix.lower()

    if suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
            table = pq.read_table(str(file_path))
            records = table.to_pylist()[:limit]
            return records, None
        except ImportError:
            return [], "pyarrow required for Parquet files. Install with: pip install pyarrow"
        except Exception as e:
            return [], str(e)

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            if suffix in (".json", ".jsonl", ".ndjson"):
                content = f.read().strip()
                if content.startswith("["):
                    records = json.loads(content)
                    return records[:limit], None
                # JSONL
                records = []
                for line in content.splitlines():
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
                        if len(records) >= limit:
                            break
                return records, None

            if suffix in (".csv", ".tsv"):
                delimiter = "\t" if suffix == ".tsv" else ","
                reader = csv.DictReader(f, delimiter=delimiter)
                records = []
                for row in reader:
                    records.append(dict(row))
                    if len(records) >= limit:
                        break
                return records, None

            return [], f"Unsupported file format: {suffix}"
    except Exception as e:
        return [], str(e)


def _infer_text_fields(doc: dict) -> list[str]:
    text_fields = []
    for key, value in doc.items():
        if isinstance(value, str) and len(value.split()) > 3:
            text_fields.append(key)
    return text_fields


# IMDb's non-commercial dataset export: https://developer.imdb.com/non-commercial-datasets/
_IMDB_SAMPLE_URL = "https://datasets.imdbws.com/title.basics.tsv.gz"
_IMDB_SAMPLE_FILENAME = "imdb.title.basics.tsv"
_IMDB_SAMPLE_MAX_ROWS = 100_000  # cap applied when the full sample is downloaded

# Small (20-title) fallback bundled with the skill so builtin_imdb works
# offline by default. Pass allow_download=True to fetch from IMDb instead.
_IMDB_FALLBACK_FILENAME = "imdb.title.basics.sample20.tsv"


def _imdb_cache_dir() -> Path:
    """Local cache directory for downloaded sample data.

    Respects XDG_CACHE_HOME when set, otherwise defaults to ~/.cache."""
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg_cache) if xdg_cache else Path.home() / ".cache"
    return base / "opensearch-agent-skills" / "sample_data"


def _download_imdb_sample(dest: Path) -> None:
    """Download IMDb's title.basics.tsv.gz and write the first
    _IMDB_SAMPLE_MAX_ROWS rows to `dest`.

    Stops reading once enough rows are collected, so only a small part of
    the (200MB+) source file is actually downloaded. Requires HTTPS and
    checks the decompressed header matches the expected TSV schema.
    """
    import gzip

    parsed = urlparse(_IMDB_SAMPLE_URL)
    if parsed.scheme != "https":
        raise ValueError(f"Refusing to fetch sample data over non-HTTPS URL: {_IMDB_SAMPLE_URL}")
    _validate_url(_IMDB_SAMPLE_URL)

    req = urllib.request.Request(
        _IMDB_SAMPLE_URL, headers={"User-Agent": "opensearch-skills/1.0"}
    )
    opener = _build_safe_opener()

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_suffix(dest.suffix + ".part")
    max_line_bytes = 1024 * 1024  # 1MB; real rows are well under 1KB

    try:
        with opener.open(req, timeout=60) as resp:
            with gzip.GzipFile(fileobj=resp) as gz, open(
                tmp_path, "w", encoding="utf-8", newline=""
            ) as out:
                for i, raw_line in enumerate(gz):
                    if len(raw_line) > max_line_bytes:
                        raise ValueError(
                            "Sample data line exceeded the expected size; "
                            "response does not look like valid TSV"
                        )
                    line = raw_line.decode("utf-8", errors="replace")
                    if i == 0 and not line.startswith("tconst\t"):
                        raise ValueError(
                            "Unexpected sample data format: header does not "
                            "match IMDb title.basics.tsv schema"
                        )
                    if i > _IMDB_SAMPLE_MAX_ROWS:  # header + N data rows
                        break
                    out.write(line)
        tmp_path.replace(dest)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def load_sample_builtin_imdb(allow_download: bool = False) -> str:
    """Load the built-in IMDB sample dataset.

    By default uses a small bundled fallback (no network call). Pass
    allow_download=True to fetch a larger sample from IMDb instead,
    caching it locally for reuse.
    """
    script_dir = Path(__file__).resolve().parent.parent

    if not allow_download:
        fallback_path = script_dir / "sample_data" / _IMDB_FALLBACK_FILENAME
        if fallback_path.exists():
            return load_sample_from_file(str(fallback_path.resolve()))
        return json.dumps({
            "error": (
                "Bundled IMDB sample not found. Retry with allow_download=True "
                "to fetch a larger sample from IMDb's dataset export."
            )
        })

    cached_path = _imdb_cache_dir() / _IMDB_SAMPLE_FILENAME
    if cached_path.exists():
        return load_sample_from_file(str(cached_path.resolve()))

    try:
        _download_imdb_sample(cached_path)
    except Exception as e:
        return json.dumps({
            "error": f"IMDB sample data not found locally and download failed: {e}"
        })

    return load_sample_from_file(str(cached_path.resolve()))


def load_sample_from_file(file_path: str) -> str:
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return json.dumps({"error": f"File not found: {file_path}"})

    records, error = _load_records_from_file(path, limit=10)
    if error:
        return json.dumps({"error": error})
    if not records:
        return json.dumps({"error": "No records found in file."})

    sample = records[0]
    text_fields = _infer_text_fields(sample)
    return json.dumps({
        "status": "loaded",
        "source": str(path),
        "record_count": len(records),
        "sample_doc": sample,
        "text_fields": text_fields,
        "text_search_required": len(text_fields) > 0,
    }, ensure_ascii=False, default=str)


# The SSRF-hardened fetch stack lives in lib/http_safe.py so that every caller
# shares one implementation. These names are kept for existing callers.
_is_restricted_ip = is_restricted_ip
_validate_url = validate_url
_build_safe_opener = build_safe_opener
_ValidatingHTTPConnection = ValidatingHTTPConnection
_ValidatingHTTPSConnection = ValidatingHTTPSConnection
_ValidatingHTTPHandler = ValidatingHTTPHandler
_ValidatingHTTPSHandler = ValidatingHTTPSHandler
_RevalidatingRedirectHandler = RevalidatingRedirectHandler


def load_sample_from_url(url: str) -> str:
    try:
        _validate_url(url)
        req = urllib.request.Request(url, headers={"User-Agent": "opensearch-skills/1.0"})
        opener = _build_safe_opener()
        with opener.open(req, timeout=30) as resp:
            content = resp.read().decode("utf-8", errors="replace")

        # Try JSON
        try:
            data = json.loads(content)
            if isinstance(data, list):
                records = data[:10]
            elif isinstance(data, dict):
                records = [data]
            else:
                return json.dumps({"error": "URL returned unexpected JSON format."})
        except json.JSONDecodeError:
            # Try CSV
            lines = content.splitlines()
            reader = csv.DictReader(lines)
            records = [dict(row) for row in list(reader)[:10]]

        if not records:
            return json.dumps({"error": "No records loaded from URL."})

        sample = records[0]
        text_fields = _infer_text_fields(sample)
        return json.dumps({
            "status": "loaded",
            "source": url,
            "record_count": len(records),
            "sample_doc": sample,
            "text_fields": text_fields,
            "text_search_required": len(text_fields) > 0,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": f"Failed to load from URL: {e}"})


def load_sample_from_index(index_name: str) -> str:
    try:
        client = create_client()
        resp = client.search(index=index_name, body={"query": {"match_all": {}}, "size": 10})
        hits = resp.get("hits", {}).get("hits", [])
        if not hits:
            return json.dumps({"error": f"No documents in index '{index_name}'."})

        records = [hit["_source"] for hit in hits if "_source" in hit]
        sample = records[0] if records else {}
        text_fields = _infer_text_fields(sample)
        return json.dumps({
            "status": "loaded",
            "source": f"localhost:{index_name}",
            "record_count": len(records),
            "sample_doc": sample,
            "text_fields": text_fields,
            "text_search_required": len(text_fields) > 0,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": f"Failed to load from index: {e}"})


def load_sample_from_paste(doc_json: str) -> str:
    try:
        doc = json.loads(doc_json)
        if not isinstance(doc, dict):
            return json.dumps({"error": "Pasted data must be a JSON object."})
        text_fields = _infer_text_fields(doc)
        return json.dumps({
            "status": "loaded",
            "source": "paste",
            "record_count": 1,
            "sample_doc": doc,
            "text_fields": text_fields,
            "text_search_required": len(text_fields) > 0,
        }, ensure_ascii=False, default=str)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {e}"})
