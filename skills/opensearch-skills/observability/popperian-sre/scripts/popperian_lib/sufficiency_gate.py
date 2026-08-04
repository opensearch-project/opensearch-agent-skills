from .evidence_ledger import EvidenceLedger
from typing import Tuple

class SufficiencyGate:
    """Evaluates whether the investigation has enough evidence to recommend remediation."""

    @staticmethod
    def evaluate(ledger: EvidenceLedger) -> Tuple[bool, str]:
        ranked = ledger.get_ranked_hypotheses()
        
        if not ranked:
            return False, "No hypotheses were generated."

        top_hypothesis = ranked[0]
        
        # Check predicates
        has_supporting = any(t.classification == "SUPPORTS" for t in top_hypothesis.tests)
        has_discriminating = len(top_hypothesis.tests) >= 2 # Simplistic check for now
        has_strong_contradiction = any(t.classification == "CONTRADICTS" for t in top_hypothesis.tests)
        
        if not has_supporting:
            return False, f"Leading hypothesis '{top_hypothesis.id}' lacks supporting evidence."

        if has_strong_contradiction:
            return False, f"Leading hypothesis '{top_hypothesis.id}' has unresolved contradicting evidence."

        if not has_discriminating:
            return False, (
                f"Leading hypothesis '{top_hypothesis.id}' was only tested once. "
                "A single confirming query is not a falsification attempt; at least "
                "one more discriminating test is required."
            )

        if len(ranked) < 2:
            return False, "At least one plausible alternative must be tested."

        runner_up = ranked[1]

        if not runner_up.tests:
            return False, (
                f"Alternative hypothesis '{runner_up.id}' was registered but never "
                "tested -- an untested alternative doesn't count as having been checked."
            )

        score_margin = top_hypothesis.score() - runner_up.score()
        
        if score_margin <= 0:
            return False, "Competing hypotheses remain observationally equivalent."
            
        # Check query failure rates across all tests
        all_tests = [t for h in ranked for t in h.tests]
        failed_tests = [t for t in all_tests if t.classification == "QUERY_FAILED"]
        
        if all_tests and (len(failed_tests) / len(all_tests)) > 0.3:
            return False, "Query failure rate exceeds threshold."
            
        return True, "Sufficiency gates passed."
