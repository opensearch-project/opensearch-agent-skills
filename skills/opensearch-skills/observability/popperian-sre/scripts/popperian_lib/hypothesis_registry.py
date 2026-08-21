from typing import List
from .models import HypothesisCard

class HypothesisRegistry:
    """A deterministic taxonomy of incident hypotheses."""
    
    TAXONOMY = {
        "H_DB_LOCK": {
            "id": "H_DB_LOCK",
            "statement": "Checkout latency was caused by database lock contention.",
            "required_observations": [
                "database wait duration increased",
                "checkout traces accumulated time in the database span"
            ],
            "contradicting_observations": [
                "database wait duration remained at baseline",
                "latency accumulated entirely before the database span"
            ],
            "alternative_explanations": [
                "dependency latency",
                "connection-pool exhaustion",
                "CPU saturation"
            ]
        },
        "H_CONN_POOL": {
            "id": "H_CONN_POOL",
            "statement": "Connection-pool exhaustion blocked threads.",
            "required_observations": [
                "connection pool WARN/ERROR logs present",
                "thread wait times spiked before external calls"
            ],
            "contradicting_observations": [
                "no connection pool logs observed",
                "connection usage metric remained below capacity"
            ],
            "alternative_explanations": [
                "database lock contention",
                "CPU saturation"
            ]
        },
        "H_DEP_LATENCY": {
            "id": "H_DEP_LATENCY",
            "statement": "Downstream dependency latency caused upstream queuing.",
            "required_observations": [
                "external network calls show increased latency in traces",
                "network timeout logs present"
            ],
            "contradicting_observations": [
                "external calls completed quickly",
                "spans for external calls show normal duration"
            ],
            "alternative_explanations": [
                "database lock contention",
                "connection-pool exhaustion"
            ]
        },
        "H_CPU_SATURATION": {
            "id": "H_CPU_SATURATION",
            "statement": "Host CPU saturation caused request queuing and latency.",
            "required_observations": [
                "cpu_usage_percent metric spiked during the incident window",
                "latency rose in step with CPU pressure"
            ],
            "contradicting_observations": [
                "cpu_usage_percent remained at baseline during the incident window",
                "no metrics signal exists to correlate with the latency spike"
            ],
            "alternative_explanations": [
                "database lock contention",
                "connection-pool exhaustion",
                "dependency latency"
            ]
        },
        "H_DEPLOYMENT_REGRESSION": {
            "id": "H_DEPLOYMENT_REGRESSION",
            "statement": "A recent deployment introduced a performance regression.",
            "required_observations": [
                "a deployment event lands shortly before the incident window begins",
                "latency rose after the deployment, not before it"
            ],
            "contradicting_observations": [
                "no deployment event exists near the incident window",
                "latency was already elevated before the nearest deployment"
            ],
            "alternative_explanations": [
                "database lock contention",
                "CPU saturation"
            ]
        }
    }

    @classmethod
    def get_hypothesis(cls, hyp_id: str) -> HypothesisCard:
        data = cls.TAXONOMY.get(hyp_id)
        if not data:
            raise ValueError(f"Unknown hypothesis: {hyp_id}")
        return HypothesisCard(**data)
        
    @classmethod
    def get_all(cls) -> List[HypothesisCard]:
        return [HypothesisCard(**data) for data in cls.TAXONOMY.values()]
