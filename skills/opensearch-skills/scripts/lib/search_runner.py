"""Execute permission-aware search and optional RAG. DLS is enforced by OpenSearch - no ACL filter here."""

import json
import math
from urllib.request import Request

from .http_safe import build_safe_opener, validate_url
from .operations import DEFAULT_TEXT_EMBEDDING_MODEL, find_registered_model
from .os_client import build_app_client
from .search import _build_default_lexical_query

_SNIPPET_CHARS = 200
# Searchable text fields of the content mapping; title outranks body text.
_TEXT_FIELDS = ["title^2", "content"]


class LLMProviderError(RuntimeError):
    """A sanitized failure from a configured answer-generation provider."""

    def __init__(self, provider: str, category: str, message: str):
        super().__init__(message)
        self.provider = provider
        self.category = category


def _load_bedrock_sdk():
    import boto3

    return boto3


class SearchRunner:
    def __init__(self, config: dict, username: str, password: str):
        if not username or not password:
            raise ValueError("Explicit end-user credentials are required for DLS queries")
        self.config = config
        self.client = build_app_client(config, username=username, password=password)
        self.index = config["opensearch"]["index"]
        self.embedding_mode = config.get("embedding", {}).get("mode", "none")
        self.dimension = config.get("embedding", {}).get("dimension", 384)
        self._model_id: str | None = None

    def query(self, question: str, top_k: int = 5, rag: bool = False) -> dict:
        """Run a permission-enforced search.

        Default (rag=False): return ranked hits only - no LLM call. RAG mode
        (rag=True): additionally generate an answer over the permitted chunks.
        """
        hits = self._search(question, top_k)
        result = {
            "mode": "rag" if rag else "search",
            "hits": [self._to_source(h) for h in hits],
            "answer": None,
        }
        if not hits or not rag:
            return result
        context = "\n\n".join(
            f"[{i+1}] (source: {h['_source'].get('source_file','')}, "
            f"path: {h['_source'].get('path','')})\n{h['_source'].get('content','')}"
            for i, h in enumerate(hits)
        )
        result["answer"] = self._call_llm(question, context)
        return result

    @staticmethod
    def _to_source(hit: dict) -> dict:
        src = hit.get("_source", {})
        content = src.get("content", "")
        return {
            "title": src.get("title", ""),
            "source_file": src.get("source_file", ""),
            "path": src.get("path", ""),
            "chunk_id": src.get("chunk_id", 0),
            "snippet": content[:_SNIPPET_CHARS].strip(),
        }

    def find_document(self, doc_id: str) -> bool:
        """Return True if the authenticated user can see the document (DLS test)."""
        response = self.client.search(
            index=self.index,
            body={
                "size": 1,
                "query": {"ids": {"values": [doc_id]}},
            },
        )
        return response["hits"]["total"]["value"] > 0

    def _search(self, question: str, top_k: int) -> list[dict]:
        # Exact matching: this index has a fixed mapping, so the shared builder's
        # default fuzziness is switched off to keep lexical scoring predictable.
        lexical = _build_default_lexical_query(
            query=question, fields=_TEXT_FIELDS, fuzziness=None
        )
        if self.embedding_mode == "local":
            embedding = self._embed(question)
            # TLQ DLS runs at filter level and wraps the request query. OpenSearch's
            # hybrid query cannot be wrapped, so use standard Boolean score summation
            # to combine lexical and vector recall without weakening DLS.
            body = {
                "size": top_k,
                "query": {
                    "bool": {
                        "should": [
                            lexical,
                            {"knn": {"content_vector": {"vector": embedding, "k": top_k}}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
            }
        else:
            body = {"size": top_k, "query": lexical}
        response = self.client.search(index=self.index, body=body)
        return response["hits"]["hits"]

    def _embed(self, text: str) -> list[float]:
        model_id = self._get_model_id()
        # TorchScript text-embedding models expect `text_docs`, not `parameters.texts`.
        response = self.client.transport.perform_request(
            "POST",
            f"/_plugins/_ml/models/{model_id}/_predict",
            body={
                "text_docs": [text],
                "return_number": True,
                "target_response": ["sentence_embedding"],
            },
        )
        try:
            outputs = response["inference_results"][0]["output"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                "ML prediction response is missing inference_results[0].output"
            ) from exc
        if not isinstance(outputs, list):
            raise RuntimeError("ML prediction output must be a list")

        embeddings = [
            output.get("data")
            for output in outputs
            if isinstance(output, dict) and output.get("name") == "sentence_embedding"
        ]
        if len(embeddings) != 1:
            raise RuntimeError(
                "ML prediction response must contain exactly one sentence_embedding"
            )
        embedding = embeddings[0]
        if not isinstance(embedding, list) or len(embedding) != self.dimension:
            actual = len(embedding) if isinstance(embedding, list) else "non-list"
            raise RuntimeError(
                f"Embedding dimension mismatch: expected {self.dimension}, got {actual}"
            )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in embedding
        ):
            raise RuntimeError("Embedding must contain only finite numeric values")
        return embedding

    def _get_model_id(self) -> str:
        # Cached: the model id cannot change during a run, and a lookup per
        # query would double the request count of benchmark and RAG loops.
        if self._model_id:
            return self._model_id
        model_name = self.config.get("embedding", {}).get(
            "model", DEFAULT_TEXT_EMBEDDING_MODEL
        )
        model = find_registered_model(self.client, model_name)
        if model is None:
            raise RuntimeError(f"Model '{model_name}' not deployed. Run setup first.")
        self._model_id = model["_id"]
        return self._model_id

    def _call_llm(self, question: str, context: str) -> str:
        prompt = (
            "Answer the question using only the provided context. "
            "Cite source numbers [1], [2], etc. for each fact.\n\n"
            f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"
        )
        llm_cfg = self.config.get("llm")
        if not llm_cfg or llm_cfg.get("provider") in (None, "none", "disabled"):
            first = context.split("\n\n")[0] if context else ""
            return f"(No LLM configured - excerpt) {first[:500]}"

        provider = llm_cfg["provider"]

        if provider in ("openai_compatible", "dmr"):
            return self._call_openai_compatible(llm_cfg, prompt)
        elif provider == "bedrock":
            return self._call_bedrock(llm_cfg, prompt)

        raise LLMProviderError(
            provider=str(provider),
            category="configuration",
            message=f"Unsupported LLM provider: {provider!r}.",
        )

    @staticmethod
    def _call_openai_compatible(llm_cfg: dict, prompt: str) -> str:
        """Call an OpenAI-compatible /chat/completions endpoint (Docker Model Runner).

        Provider details are intentionally omitted from raised errors.
        """
        try:
            base_url = llm_cfg.get("base_url", "http://localhost:12434/engines/v1")
            url = f"{base_url.rstrip('/')}/chat/completions"
            # A local model runner is the common case, so loopback is permitted.
            # Every other address range is still rejected, and the prompt may
            # contain content the caller is authorized to read.
            validate_url(url, allow_loopback=True)
            request = Request(
                url,
                data=json.dumps({
                    "model": llm_cfg.get("model", "ai/smollm2"),
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": llm_cfg.get("max_tokens", 1024),
                    "temperature": 0,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            opener = build_safe_opener(allow_loopback=True)
            with opener.open(request, timeout=llm_cfg.get("timeout", 120)) as response:
                payload = json.loads(response.read())
        except Exception as exc:
            raise LLMProviderError(
                "openai_compatible", "provider", "OpenAI-compatible LLM request failed."
            ) from exc

        try:
            answer = payload["choices"][0]["message"]["content"]
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("empty answer")
            return answer
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMProviderError(
                "openai_compatible", "invalid_response", "OpenAI-compatible LLM returned an invalid response."
            ) from exc

    @staticmethod
    def _call_bedrock(llm_cfg: dict, prompt: str) -> str:
        """Call Amazon Bedrock (Claude) and expose only sanitized failures."""
        try:
            boto3 = _load_bedrock_sdk()
        except ImportError as exc:
            raise LLMProviderError(
                "bedrock",
                "configuration",
                "Amazon Bedrock RAG requires boto3. Re-run with "
                "`uv run --group ingestion python scripts/permission_search.py ...`.",
            ) from exc

        try:
            bedrock = boto3.client(
                "bedrock-runtime",
                region_name=llm_cfg.get("region", "us-east-1"),
            )
            response = bedrock.invoke_model(
                modelId=llm_cfg.get("model_id", "anthropic.claude-3-haiku-20240307-v1:0"),
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": llm_cfg.get("max_tokens", 1024),
                    "messages": [{"role": "user", "content": prompt}],
                }),
            )
        except Exception as exc:
            raise LLMProviderError(
                "bedrock", "provider", "Amazon Bedrock request failed."
            ) from exc

        try:
            answer = json.loads(response["body"].read())["content"][0]["text"]
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("empty answer")
            return answer
        except Exception as exc:
            raise LLMProviderError(
                "bedrock", "invalid_response", "Amazon Bedrock returned an invalid response."
            ) from exc
