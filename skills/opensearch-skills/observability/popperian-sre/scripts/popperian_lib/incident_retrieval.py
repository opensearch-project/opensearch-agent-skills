import logging
from typing import List, Dict, Any, Optional
from opensearchpy import OpenSearch

logger = logging.getLogger(__name__)

class IncidentRetrieval:
    def __init__(self, client: OpenSearch, index_name: str = "historical-incidents"):
        self.client = client
        self.index_name = index_name

    def retrieve_analogues(self, 
                           query_vector: List[float], 
                           service: Optional[str] = None,
                           k: int = 3) -> List[Dict[str, Any]]:
        """
        Retrieves analogous historical incidents using k-NN vector search.
        Applies metadata filtering if service is provided.
        """
        try:
            # Check if index exists
            if not self.client.indices.exists(index=self.index_name):
                return []
                
            query = {
                "size": k,
                "query": {
                    "knn": {
                        "incident_vector": {
                            "vector": query_vector,
                            "k": k
                        }
                    }
                }
            }
            
            # Apply filter if provided
            if service:
                query["query"]["knn"]["incident_vector"]["filter"] = {
                    "term": {"service": service}
                }

            response = self.client.search(
                index=self.index_name,
                body=query
            )
            
            return [hit["_source"] for hit in response["hits"]["hits"]]

        except Exception as e:
            logger.warning("retrieve_analogues(index=%r, k=%d) failed: %s", self.index_name, k, e)
            return []
