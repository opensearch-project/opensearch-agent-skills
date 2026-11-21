import hashlib
import json
import logging
from typing import Dict, Any, Optional
from opensearchpy import OpenSearch
from .ppl_validation import PPLValidator
from .redaction import Redactor

logger = logging.getLogger(__name__)

class QueryExecutor:
    # Bounds how many datarows are surfaced into the *agent's* context by
    # default, independent of max_rows (which bounds what OpenSearch is asked
    # to compute/return -- a cluster-load and network concern, not a context
    # one). PPL's schema+datarows shape already avoids repeating field names
    # per row, but per-row cost is still linear in row count: an unbounded
    # result at max_rows=500 can cost tens of thousands of tokens, and this
    # skill's own workflow issues several queries per investigation. 20 rows
    # is enough to see the shape of a result and decide the next query; a
    # hypothesis that needs an exact count should aggregate (stats/count),
    # not rely on being handed every row.
    DEFAULT_MAX_ROWS_IN_CONTEXT = 20

    def __init__(self, client: OpenSearch):
        self.client = client

    def execute_ppl(
        self,
        query: str,
        timeout_seconds: int = 10,
        max_rows: int = 500,
        max_rows_in_context: Optional[int] = DEFAULT_MAX_ROWS_IN_CONTEXT,
    ) -> Dict[str, Any]:
        """
        Executes a PPL query against OpenSearch safely.
        Records raw result hash and provenance for auditability.
        """
        is_valid, validation_result = PPLValidator.validate(query, max_rows)

        if not is_valid:
            return {
                "status": "QUERY_FAILED",
                "error": validation_result,
                "query": query
            }

        try:
            # PPL endpoint expects POST to /_plugins/_ppl
            body = {"query": validation_result}

            # Use raw transport since PPL is a plugin. `timeout` is a dedicated
            # perform_request kwarg (seconds, numeric) -- passing it inside `params`
            # collides with the connection layer's own timeout handling and raises
            # "Timeout value ... must be an int, float or None" on every call.
            response = self.client.transport.perform_request(
                "POST",
                "/_plugins/_ppl",
                body=body,
                timeout=timeout_seconds
            )

            # Redact sensitive fields (secrets, tokens, emails) before the response
            # is surfaced or hashed, so provenance hashes match what's actually exposed.
            # The hash is computed over the FULL redacted response (before any
            # context-bounding below) so it stays a true fingerprint of everything
            # OpenSearch actually returned -- auditability shouldn't degrade just
            # because the agent only got shown a sample of it.
            redacted_response = Redactor.redact_dict(response)
            raw_json = json.dumps(redacted_response, sort_keys=True)
            result_hash = hashlib.sha256(raw_json.encode('utf-8')).hexdigest()

            context_data = self._bound_for_context(redacted_response, max_rows_in_context)

            return {
                "status": "SUCCESS",
                "data": context_data,
                "query": validation_result,
                "result_hash": result_hash
            }
        except Exception as e:
            # QUERY_FAILED is already surfaced in the return value -- this also
            # writes it server-side, since "the agent saw an error string" and
            # "an operator can see this cluster is failing queries" are different
            # audiences.
            logger.warning("execute_ppl(query=%r) failed: %s", validation_result, e)
            return {
                "status": "QUERY_FAILED",
                "error": str(e),
                "query": validation_result
            }

    @staticmethod
    def _bound_for_context(data: Dict[str, Any], max_rows_in_context: Optional[int]) -> Dict[str, Any]:
        """
        Truncates `datarows` to at most max_rows_in_context, preserving the
        true row count so the agent knows more exist without paying the token
        cost for all of them. A no-op when max_rows_in_context is None, or the
        response has no datarows, or it's already within the bound.
        """
        if max_rows_in_context is None:
            return data

        datarows = data.get("datarows")
        if not isinstance(datarows, list) or len(datarows) <= max_rows_in_context:
            return data

        bounded = dict(data)
        bounded["datarows"] = datarows[:max_rows_in_context]
        bounded["rows_shown"] = max_rows_in_context
        bounded["rows_truncated_for_context"] = len(datarows) - max_rows_in_context
        return bounded
