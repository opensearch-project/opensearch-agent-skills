from typing import List, Dict, Literal, Optional
from pydantic import BaseModel

class TimeWindow(BaseModel):
    start: str
    end: str

# The full set of classifications a test result can carry, per SKILL.md step 9
# (UPDATE_EVIDENCE_STATE). A Literal here (rather than a plain str) means a
# typo like "SUPPORT" or "supports" is rejected at construction time by
# pydantic, instead of silently scoring as 0 and never showing up as an error
# anywhere -- the exact kind of silent failure an auditable system shouldn't allow.
Classification = Literal[
    "SUPPORTS", "CONTRADICTS", "MISSING", "NONDISCRIMINATING", "QUERY_FAILED", "SCHEMA_MISMATCH"
]

# Score = Supporting Weight - Contradicting Weight - Missing Penalty, per
# SKILL.md's "Constraints & Rules". NONDISCRIMINATING and SCHEMA_MISMATCH are
# intentionally absent (score 0 via .get default): a test that ran but
# distinguished nothing, or hit a schema mismatch, is neither evidence for nor
# against a hypothesis.
CLASSIFICATION_WEIGHTS: Dict[str, int] = {
    "SUPPORTS": 10,
    "CONTRADICTS": -20,
    "MISSING": -5,
    "QUERY_FAILED": -5,
}

class TestResult(BaseModel):
    # Tells pytest's collector this is a data model, not a test class it
    # should try to instantiate -- the name collision with pytest's own
    # "Test*" convention is coincidental (this predates any test file).
    __test__ = False

    test_id: str
    hypothesis_id: str
    signal: str
    query: str
    classification: Classification
    raw_result_hash: str
    interpretation: str

class HypothesisCard(BaseModel):
    id: str
    statement: str
    required_observations: List[str]
    contradicting_observations: List[str]
    alternative_explanations: List[str]
    tests: List[TestResult] = []

    def score(self) -> int:
        return sum(CLASSIFICATION_WEIGHTS.get(test.classification, 0) for test in self.tests)

class InvestigationState(BaseModel):
    incident_window: Optional[TimeWindow] = None
    hypotheses: Dict[str, HypothesisCard] = {}
    completed: bool = False
    refusal_reason: Optional[str] = None
