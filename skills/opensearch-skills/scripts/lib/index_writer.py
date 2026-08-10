"""Create and manage permission-aware-search indexes, pipelines, and bulk indexing."""

import time
import uuid

from opensearchpy import helpers
from opensearchpy.exceptions import AuthorizationException, TransportError
from .dls_manager import DLSManager
from .operations import (
    DEFAULT_TEXT_EMBEDDING_MODEL,
    PRETRAINED_MODELS,
    attach_default_pipeline,
    find_registered_model,
    put_ingest_pipeline,
)
from .os_client import build_admin_client


class IndexWriter:
    def __init__(self, config: dict):
        self.config = config
        self.client = build_admin_client(config)
        cfg = config["opensearch"]
        self.index = cfg["index"]
        self.acl_index = f"{self.index}-acl"
        self.embedding_mode = config.get("embedding", {}).get("mode", "none")
        self.dimension = config.get("embedding", {}).get("dimension", 384)
        self._model_id: str | None = None

    def setup(self, force_recreate: bool = False):
        if force_recreate:
            if self.client.indices.exists(index=self.index):
                self.client.indices.delete(index=self.index)
            acl_targets = self._acl_target_indexes()
            if acl_targets:
                self.client.indices.delete(index=",".join(acl_targets))

        if not self.client.indices.exists(index=self.index):
            self.client.indices.create(index=self.index, body=self._content_mapping())

        if not self._acl_target_indexes():
            backing_index = self._new_acl_backing_name()
            body = self._acl_mapping()
            body["aliases"] = {self.acl_index: {"is_write_index": True}}
            self.client.indices.create(index=backing_index, body=body)

        acl_targets = self._acl_target_indexes()
        if len(acl_targets) != 1:
            raise RuntimeError(
                f"Expected one ACL lookup target, found {len(acl_targets)}"
            )

        if self.embedding_mode == "local":
            self._allow_ml_on_data_node()
            self._setup_ingest_pipeline()

        return acl_targets[0]

    def _allow_ml_on_data_node(self):
        # On a single-node cluster (e.g. the local demo) there is no dedicated ML
        # node, so model deployment fails unless we allow ML tasks on data nodes.
        try:
            self.client.cluster.put_settings(
                body={"persistent": {"plugins.ml_commons.only_run_on_ml_node": False}}
            )
        except AuthorizationException as exc:
            # A managed cluster may forbid cluster settings updates. Surface it,
            # because otherwise the cause resurfaces as an opaque deploy failure.
            raise RuntimeError(
                "Not permitted to set plugins.ml_commons.only_run_on_ml_node. "
                "Use --embedding-mode none, or have an administrator allow ML "
                "tasks on data nodes."
            ) from exc
        except TransportError:
            # Non-fatal: a properly provisioned cluster with ML nodes doesn't need this.
            pass

    def _content_mapping(self) -> dict:
        props = {
            "title":          {"type": "text", "analyzer": "english"},
            "content":        {"type": "text", "analyzer": "english"},
            "allowed_users":  {"type": "keyword"},
            "path":           {"type": "keyword"},
            "source_file":    {"type": "keyword"},
            "chunk_id":       {"type": "integer"},
            # Structure reported by the document converter, when available: the
            # heading trail is searchable, and the page number lets an answer
            # cite where a chunk came from.
            "headings":       {"type": "text", "analyzer": "english"},
            "page_number":    {"type": "integer"},
            "metadata":       {"type": "object", "enabled": False},
        }
        settings: dict = {"index": {}}

        if self.embedding_mode == "local":
            props["content_vector"] = {
                "type": "knn_vector",
                "dimension": self.dimension,
                "method": {"engine": "faiss", "name": "hnsw", "space_type": "l2"},
            }
            settings["index"]["knn"] = True
            settings["index"]["knn.algo_param.ef_search"] = 100

        return {"settings": settings, "mappings": {"properties": props}}

    def _acl_mapping(self) -> dict:
        return {
            "settings": {"index": {"number_of_shards": 1}},
            "mappings": {"properties": {"allowed_users": {"type": "keyword"}}},
        }

    def _get_or_deploy_model(self) -> str:
        if self._model_id:
            return self._model_id
        model_name = self.config.get("embedding", {}).get(
            "model", DEFAULT_TEXT_EMBEDDING_MODEL
        )
        model = find_registered_model(self.client, model_name)
        if model is not None:
            # Model already registered - reuse it. Deploy/wait only if not DEPLOYED.
            # (Re-registering an existing model returns a task with no model_id.)
            model_id = model["_id"]
            if model["_source"].get("model_state") != "DEPLOYED":
                self._deploy_and_wait(model_id)
            self._model_id = model_id
            return model_id

        # Version comes from the shared pretrained-model registry so this path
        # never drifts from opensearch_ops' deploy path. Fall back for a custom
        # model name not in the registry.
        version = PRETRAINED_MODELS.get(model_name, "1.0.2")
        reg = self.client.transport.perform_request(
            "POST", "/_plugins/_ml/models/_register",
            body={"name": model_name, "version": version, "model_format": "TORCH_SCRIPT"},
        )
        task_id = reg.get("task_id") if isinstance(reg, dict) else None
        if not task_id:
            raise RuntimeError("Model registration did not return a task_id")
        task = self._wait_task(task_id)
        model_id = task.get("model_id")
        if not model_id:
            raise RuntimeError(f"Model registration did not return a model_id: {task}")
        self._deploy_and_wait(model_id)
        self._model_id = model_id
        return model_id

    def _deploy_and_wait(self, model_id: str):
        # Deploy the model and wait until it reports DEPLOYED, so a following ingest
        # or query doesn't fail with "Model not ready yet".
        deploy = self.client.transport.perform_request("POST", f"/_plugins/_ml/models/{model_id}/_deploy")
        task_id = deploy.get("task_id") if isinstance(deploy, dict) else None
        if not task_id:
            raise RuntimeError("Model deployment did not return a task_id")
        self._wait_task(task_id)
        self._wait_for_state(
            path=f"/_plugins/_ml/models/{model_id}",
            state_field="model_state",
            success_state="DEPLOYED",
            pending_states={"REGISTERED", "DEPLOYING"},
            description=f"model {model_id} deployment",
        )

    def _wait_task(self, task_id: str) -> dict:
        # Not delegated to operations._wait_for_ml_task on purpose. That helper
        # treats only COMPLETED and FAILED as terminal, so CANCELLED,
        # COMPLETED_WITH_ERROR, EXPIRED, UNREACHABLE, and a missing state field
        # all keep polling until it gives up and reports a timeout with the error
        # detail discarded. Waiting ~300s to misreport a permanently failed task
        # is worse than duplicating a poll loop.
        return self._wait_for_state(
            path=f"/_plugins/_ml/tasks/{task_id}",
            state_field="state",
            success_state="COMPLETED",
            pending_states={"CREATED", "RUNNING"},
            description=f"ML task {task_id}",
        )

    def _wait_for_state(
        self,
        *,
        path: str,
        state_field: str,
        success_state: str,
        pending_states: set[str],
        description: str,
        timeout: float = 600,
        poll_interval: float = 5,
    ) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            result = self.client.transport.perform_request("GET", path)
            state = result.get(state_field)
            if state == success_state:
                return result
            if state not in pending_states:
                detail = f": {result['error']}" if result.get("error") else ""
                raise RuntimeError(f"{description} entered state {state!r}{detail}")

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"{description} timed out after {timeout:g}s in state {state!r}"
                )
            time.sleep(min(poll_interval, remaining))

    def _setup_ingest_pipeline(self):
        model_id = self._get_or_deploy_model()
        pipeline_id = f"{self.index}-ingest"
        put_ingest_pipeline(
            self.client,
            pipeline_id,
            {
                "description": "permission-aware-search text embedding",
                "processors": [{
                    "text_embedding": {
                        "model_id": model_id,
                        "field_map": {"content": "content_vector"},
                    }
                }],
            },
        )
        attach_default_pipeline(self.client, self.index, pipeline_id)

    def bulk_index(self, docs: list[dict]) -> dict:
        """Index documents and report per-document failures.

        A document may carry an `_id`, which makes re-ingesting the same source
        overwrite its chunks instead of duplicating them.
        """
        actions = []
        for document in docs:
            source = {key: value for key, value in document.items() if key != "_id"}
            action = {"_index": self.index, "_source": source}
            if document.get("_id"):
                action["_id"] = document["_id"]
            actions.append(action)

        if not actions:
            return {"indexed": 0, "errors": []}

        indexed, raw_errors = helpers.bulk(
            self.client, actions, raise_on_error=False, stats_only=False
        )
        errors = [
            f"{name}: {detail.get('error', detail)}"
            for failure in raw_errors
            for name, detail in failure.items()
        ]
        if indexed:
            self.client.indices.refresh(index=self.index)
        return {"indexed": indexed, "errors": errors}

    def replace_acl_documents(self, docs: list[dict]) -> str:
        """Build a complete ACL snapshot and switch DLS to it as one role update."""
        documents = self._validate_acl_documents(docs)
        backing_index = self._new_acl_backing_name()

        try:
            self.client.indices.create(index=backing_index, body=self._acl_mapping())
            if documents:
                helpers.bulk(self.client, [
                    {
                        "_index": backing_index,
                        "_id": document["_id"],
                        "_source": {"allowed_users": document["allowed_users"]},
                    }
                    for document in documents
                ])
            self.client.indices.refresh(index=backing_index)

            indexed_count = self.client.count(index=backing_index)["count"]
            if indexed_count != len(documents):
                raise RuntimeError(
                    "ACL snapshot validation failed: "
                    f"expected {len(documents)} documents, found {indexed_count}"
                )
        except Exception:
            self._delete_failed_acl_candidate(backing_index)
            raise

        previous_indexes = self._acl_target_indexes()
        manager = DLSManager(self.config)
        try:
            manager.create_role(acl_lookup_index=backing_index)
        except Exception:
            self._delete_failed_acl_candidate(backing_index)
            raise

        actions = [
            {"remove_index": {"index": index}}
            for index in previous_indexes
        ]
        actions.append({
            "add": {
                "index": backing_index,
                "alias": self.acl_index,
                "is_write_index": True,
            }
        })
        try:
            self.client.indices.update_aliases(body={"actions": actions})
            return backing_index
        except Exception as alias_error:
            try:
                if backing_index in self._acl_alias_backings():
                    return backing_index
            except Exception as reconciliation_error:
                raise RuntimeError(
                    f"ACL authorization now targets {backing_index!r}, but the "
                    f"state of alias {self.acl_index!r} could not be verified. "
                    "Repair the alias manually and do not delete the active backing index."
                ) from reconciliation_error
            raise RuntimeError(
                f"ACL authorization now targets {backing_index!r}, but alias "
                f"{self.acl_index!r} was not updated. Repair the alias manually "
                "and do not delete the active backing index."
            ) from alias_error

    def _delete_failed_acl_candidate(self, backing_index: str):
        try:
            if self.client.indices.exists(index=backing_index):
                self.client.indices.delete(index=backing_index)
        except Exception as cleanup_error:
            raise RuntimeError(
                "ACL snapshot failed before authorization changed, and candidate "
                f"{backing_index!r} could not be deleted. Delete it manually."
            ) from cleanup_error

    def _acl_alias_backings(self) -> list[str]:
        if not self.client.indices.exists_alias(name=self.acl_index):
            return []
        return sorted(self.client.indices.get_alias(name=self.acl_index).keys())

    def _acl_target_indexes(self) -> list[str]:
        backings = self._acl_alias_backings()
        if backings:
            return backings
        if self.client.indices.exists(index=self.acl_index):
            return [self.acl_index]
        return []

    def _new_acl_backing_name(self) -> str:
        return f"{self.acl_index}-{uuid.uuid4().hex}"

    @staticmethod
    def _validate_acl_documents(docs: list[dict]) -> list[dict]:
        validated = []
        seen_ids = set()
        for document in docs:
            user_id = document.get("_id")
            principals = document.get("allowed_users")
            if not isinstance(user_id, str) or not user_id:
                raise ValueError("Every ACL document requires a non-empty string _id")
            if user_id in seen_ids:
                raise ValueError(f"Duplicate ACL document _id: {user_id}")
            if (not isinstance(principals, list)
                    or any(not isinstance(value, str) or not value for value in principals)):
                raise ValueError(
                    f"ACL document {user_id!r} requires a list of non-empty principals"
                )
            seen_ids.add(user_id)
            validated.append({
                "_id": user_id,
                "allowed_users": list(dict.fromkeys(principals)),
            })
        return validated
