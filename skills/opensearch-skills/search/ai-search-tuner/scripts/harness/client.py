"""OpenSearch client wrapper + a protocol every mode codes against.

Modes and probes talk to the cluster ONLY through `OSClient`. This keeps
opensearch-py usage in one place, centralizes auth/secret hygiene, and — most
importantly — lets the entire test suite run against `FakeOSClient` (in
fake_client.py) with zero real cluster.

Auth is read from environment variables only (never args, never logged):
    OPENSEARCH_URL           e.g. https://localhost:9200
    OPENSEARCH_USERNAME      basic auth (optional)
    OPENSEARCH_PASSWORD      basic auth (optional)
    OPENSEARCH_API_KEY       api-key auth (optional)
    OPENSEARCH_VERIFY_CERTS  "false" to disable (default true)
SigV4 for Amazon OpenSearch Service is supported when OPENSEARCH_AWS_REGION is
set and the aws sdk is available; kept optional so the core stays dependency-light.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class OSClient(Protocol):
    """The minimal cluster surface ai-search-tuner needs.

    Deliberately small so FakeOSClient can implement it fully. All methods are
    thin pass-throughs to the OpenSearch REST API.
    """

    # --- cluster / capability probing ---
    def info(self) -> dict[str, Any]: ...
    def cat_plugins(self) -> list[dict[str, Any]]: ...
    def cluster_stats(self) -> dict[str, Any]: ...
    def knn_stats(self) -> dict[str, Any]: ...
    def cat_indices(self, index: str) -> list[dict[str, Any]]: ...
    def ml_models(self) -> list[dict[str, Any]]: ...
    def get_model_state(self, model_id: str) -> str | None: ...

    # --- index / pipeline lifecycle ---
    def create_index(self, index: str, body: dict[str, Any]) -> dict[str, Any]: ...
    def delete_index(self, index: str) -> dict[str, Any]: ...
    def bulk(self, index: str, docs: list[dict[str, Any]]) -> dict[str, Any]: ...
    def refresh(self, index: str) -> dict[str, Any]: ...
    def put_pipeline(self, pipeline_id: str, body: dict[str, Any]) -> dict[str, Any]: ...
    def delete_pipeline(self, pipeline_id: str) -> dict[str, Any]: ...
    def put_search_pipeline(self, pipeline_id: str, body: dict[str, Any]) -> dict[str, Any]: ...
    def delete_search_pipeline(self, pipeline_id: str) -> dict[str, Any]: ...

    # --- search ---
    def search(self, index: str, body: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]: ...


class RealOSClient:
    """opensearch-py-backed implementation of OSClient.

    Imported lazily so the package (and its tests) don't hard-require
    opensearch-py to be installed.
    """

    def __init__(self, client: Any):
        self._c = client

    @staticmethod
    def _autodetect_localhost_url() -> str:
        """Return a reachable localhost:9200 URL, probing HTTP then HTTPS.

        Defaults to http://localhost:9200 if neither responds (the most common
        local dev setup), so behavior is deterministic when no cluster is up.
        """
        import urllib.request
        import urllib.error
        import ssl

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        for cand in ("http://localhost:9200", "https://localhost:9200"):
            try:
                kw = {"timeout": 2}
                if cand.startswith("https"):
                    kw["context"] = ctx
                with urllib.request.urlopen(urllib.request.Request(cand), **kw):
                    return cand
            except urllib.error.HTTPError:
                # An HTTP error (e.g. 401 on a secured cluster) still means the
                # endpoint is REACHABLE at this scheme — use it.
                return cand
            except Exception:
                continue
        return "http://localhost:9200"

    @classmethod
    def from_env(cls) -> "RealOSClient":
        try:
            from opensearchpy import OpenSearch
        except ImportError as e:  # pragma: no cover - env-dependent
            raise RuntimeError(
                "opensearch-py is required for live runs: pip install opensearch-py"
            ) from e

        # Resolve the cluster URL. If OPENSEARCH_URL is unset, auto-detect the
        # scheme on localhost:9200 rather than blindly defaulting to HTTPS — a
        # local dev cluster (gradlew run / security disabled) speaks plain HTTP,
        # and defaulting to HTTPS made the very first probe fail and forced the
        # agent to diagnose + retry. We probe HTTP first (the common dev case),
        # then HTTPS, and fall back to HTTP if neither answers.
        url = os.environ.get("OPENSEARCH_URL")
        if not url:
            url = cls._autodetect_localhost_url()
        verify = os.environ.get("OPENSEARCH_VERIFY_CERTS", "true").lower() != "false"
        # A local HTTPS dev cluster uses a self-signed cert; don't fail on it
        # unless the user explicitly asked to verify.
        if url.startswith("https://localhost") and "OPENSEARCH_VERIFY_CERTS" not in os.environ:
            verify = False
        # Generous timeout + retries: bulk-indexing through a neural-sparse /
        # embedding ingest pipeline runs model inference per doc and can far
        # exceed the 10s default on larger corpora (the default timed out on a
        # 1.5k-doc SPLADE bulk). Override via OPENSEARCH_TIMEOUT (seconds).
        timeout = int(os.environ.get("OPENSEARCH_TIMEOUT", "120"))
        kwargs: dict[str, Any] = {
            "hosts": [url], "verify_certs": verify, "ssl_show_warn": False,
            "timeout": timeout, "max_retries": 3, "retry_on_timeout": True,
        }

        api_key = os.environ.get("OPENSEARCH_API_KEY")
        user = os.environ.get("OPENSEARCH_USERNAME")
        pwd = os.environ.get("OPENSEARCH_PASSWORD")
        region = os.environ.get("OPENSEARCH_AWS_REGION")

        if region:  # SigV4 for Amazon OpenSearch Service
            from opensearchpy import AWSV4SignerAuth, RequestsHttpConnection
            import boto3

            creds = boto3.Session().get_credentials()
            kwargs["http_auth"] = AWSV4SignerAuth(creds, region, "es")
            kwargs["connection_class"] = RequestsHttpConnection
        elif api_key:
            kwargs["headers"] = {"Authorization": f"ApiKey {api_key}"}
        elif user and pwd:
            kwargs["http_auth"] = (user, pwd)

        return cls(OpenSearch(**kwargs))

    # --- probing ---
    def info(self) -> dict[str, Any]:
        return self._c.info()

    def cat_plugins(self) -> list[dict[str, Any]]:
        return self._c.cat.plugins(format="json")

    def cluster_stats(self) -> dict[str, Any]:
        return self._c.cluster.stats()

    def knn_stats(self) -> dict[str, Any]:
        return self._c.transport.perform_request("GET", "/_plugins/_knn/stats")

    def cat_indices(self, index: str) -> list[dict[str, Any]]:
        return self._c.cat.indices(index=index, format="json", bytes="b")

    def ml_models(self) -> list[dict[str, Any]]:
        try:
            resp = self._c.transport.perform_request(
                "POST", "/_plugins/_ml/models/_search",
                # Exclude chunk sub-documents (they carry a `chunk_number`); we
                # only want the parent model docs. Ask for the fields we need.
                body={
                    "query": {"bool": {"must_not": [{"exists": {"field": "chunk_number"}}]}},
                    "size": 100,
                },
            )
            out = []
            for h in resp.get("hits", {}).get("hits", []):
                src = dict(h.get("_source", {}) or {})
                # The document _id IS the model_id; _search often omits model_id
                # and model_state from _source, so surface the id and let the
                # caller confirm state via get_model_state if needed.
                src.setdefault("model_id", h.get("_id"))
                out.append(src)
            return out
        except Exception:
            return []

    def get_model_state(self, model_id: str) -> str | None:
        """Direct GET of a model's deployment state (authoritative).

        `_search` does not reliably return model_state, so callers that must
        know whether a model is DEPLOYED use this per-candidate lookup.
        """
        try:
            resp = self._c.transport.perform_request(
                "GET", f"/_plugins/_ml/models/{model_id}"
            )
            return resp.get("model_state")
        except Exception:
            return None

    # --- lifecycle ---
    def create_index(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._c.indices.create(index=index, body=body)

    def delete_index(self, index: str) -> dict[str, Any]:
        return self._c.indices.delete(index=index, ignore=[404])

    def bulk(self, index: str, docs: list[dict[str, Any]], chunk_size: int = 1000) -> dict[str, Any]:
        """Index docs, splitting into chunks so no single request body is huge.

        Sending the whole corpus in ONE _bulk body breaks on any realistic
        dense corpus: the body easily exceeds http.max_content_length (default
        100mb -> HTTP 413), and buffering a multi-hundred-MB request on the node
        can OOM a small single-node cluster. We split by document count
        (chunk_size docs per request) which bounds both the request size and the
        node's transient memory. Returns the LAST chunk's response (callers use
        it only for error propagation; opensearch-py raises on transport errors).
        """
        last_resp: dict[str, Any] = {}
        for start in range(0, len(docs), chunk_size):
            batch = docs[start:start + chunk_size]
            lines: list[dict[str, Any]] = []
            for d in batch:
                lines.append({"index": {"_index": index, "_id": d.get("id")}})
                lines.append(d)
            if lines:
                last_resp = self._c.bulk(body=lines, refresh=False)
        return last_resp

    def refresh(self, index: str) -> dict[str, Any]:
        return self._c.indices.refresh(index=index)

    def put_pipeline(self, pipeline_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._c.ingest.put_pipeline(id=pipeline_id, body=body)

    def delete_pipeline(self, pipeline_id: str) -> dict[str, Any]:
        return self._c.ingest.delete_pipeline(id=pipeline_id, ignore=[404])

    def put_search_pipeline(self, pipeline_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._c.transport.perform_request(
            "PUT", f"/_search/pipeline/{pipeline_id}", body=body
        )

    def delete_search_pipeline(self, pipeline_id: str) -> dict[str, Any]:
        return self._c.transport.perform_request(
            "DELETE", f"/_search/pipeline/{pipeline_id}"
        )

    # --- search ---
    def search(self, index: str, body: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._c.search(index=index, body=body, params=params or {})
