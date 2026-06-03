.PHONY: test test-evals benchmark benchmark-3 baseline compare help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

test: ## Run unit/integration tests (no evals)
	uv run pytest tests/ --ignore=tests/evals -v

test-evals: ## Run LLM eval tests (requires AWS credentials)
	uv run --group evals pytest tests/evals/ --run-eval -v

test-evals-analysis: ## Run eval analysis (aggregate results)
	uv run --group evals pytest tests/evals/ --run-eval-analysis

benchmark: ## Run benchmark (1 run, fast feedback)
	uv run --group evals python scripts/run_benchmark.py --runs 1

benchmark-3: ## Run benchmark with 3 runs (statistical stability)
	uv run --group evals python scripts/run_benchmark.py --runs 3

baseline: ## Run benchmark and save as baseline
	uv run --group evals python scripts/run_benchmark.py --runs 3 --tag baseline --output tests/evals/results/baseline.json

compare: ## Compare latest benchmark against baseline
	uv run --group evals python scripts/compare_baseline.py

benchmark-workflows: ## Run only the workflow evals (not routing/rules)
	uv run --group evals pytest tests/evals/test_skill_workflows.py --run-eval -v

benchmark-workflows-analysis: ## Analyze workflow eval results
	uv run --group evals pytest tests/evals/test_skill_workflows.py --run-eval-analysis
