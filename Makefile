.PHONY: help test lint validate probe

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

test: ## Run the plugin script unit tests
	uv run --no-project python -m unittest discover -s plugins/wow-dev/scripts/tests -p 'test_*.py'

lint: ## Lint hot-path plugin docs (budgets, rationale, frontmatter)
	uv run --no-project plugins/wow-dev/scripts/doclint.py plugins/wow-dev

validate: ## Validate the plugin and marketplace manifests
	claude plugin validate --strict plugins/wow-dev && claude plugin validate --strict .

probe: ## Print repo_profile.py output for REPO=<path>
	uv run --no-project plugins/wow-dev/scripts/repo_profile.py --root $(REPO)

.DEFAULT_GOAL := help
