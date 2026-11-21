from typing import List
from .models import InvestigationState, HypothesisCard, TestResult

class EvidenceLedger:
    def __init__(self, state: InvestigationState = None):
        self.state = state or InvestigationState()

    def add_hypothesis(self, card: HypothesisCard):
        self.state.hypotheses[card.id] = card

    def record_test_result(self, result: TestResult):
        if result.hypothesis_id not in self.state.hypotheses:
            # Silently dropping evidence would be the exact failure mode this
            # system exists to prevent -- fail loudly instead of losing a test
            # result because of a hypothesis_id typo.
            raise ValueError(
                f"Cannot record a test result for unregistered hypothesis "
                f"'{result.hypothesis_id}'. Call add_hypothesis() first."
            )
        self.state.hypotheses[result.hypothesis_id].tests.append(result)

    def get_ranked_hypotheses(self) -> List[HypothesisCard]:
        return sorted(
            self.state.hypotheses.values(),
            key=lambda h: h.score(),
            reverse=True
        )
