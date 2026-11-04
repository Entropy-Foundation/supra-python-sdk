# Copyright © Supra
# SPDX-License-Identifier: Apache-2.0

# `make ci` runs the same checks as the CI workflow (only `audit` needs the
# network). Tests that need a node (tests/unit/test_supra_client.py) are skipped unless SUPRA_RPC_URL is
# set, for example SUPRA_RPC_URL=http://localhost:27001/ make test-unit.

test-unit:
	uv run python -m unittest discover -s tests/unit/ -p 'test_*.py' -t .

test-spec:
	uv run behave --format progress tests/features

test-all: test-spec test-unit

test-coverage:
	uv run coverage run -m unittest discover -s tests/unit/ -p 'test_*.py' -t .
	uv run coverage report

fmt:
	uv run ruff format supra_sdk tests/unit examples

fmt-check:
	uv run ruff format --check supra_sdk tests/unit examples

lint:
	uv run ruff check --no-fix supra_sdk tests/unit examples

typecheck:
	uv run mypy

build:
	uv build

audit:
	uv export --frozen --no-hashes --no-dev --no-emit-project -o requirements-audit.txt
	uvx pip-audit@2.10.1 --no-deps -r requirements-audit.txt
	rm -f requirements-audit.txt

ci: lint fmt-check typecheck test-unit test-spec test-coverage build audit

# `make examples` runs every example, in this order, against the node at
# SUPRA_RPC_NODE_URL. It runs all of them even when one fails, then fails if any
# failed and lists those. The examples send transactions, so the target needs
# SUPRA_RPC_NODE_URL set; see examples/README.md for the other variables. For example:
#   SUPRA_RPC_NODE_URL=http://localhost:27001 make examples
#   SUPRA_RPC_NODE_URL=https://rpc-devnet.supra.com SUPRA_EXAMPLES_PRIVATE_KEY=<key> make examples
EXAMPLES = automation faucet fee_payer_transfer_coin fungible_asset hello_blockchain multisig \
	rotate_key simple_nft simple_supra_token simulate_transfer_coin supra_token \
	transfer_coin transfer_two_by_two your_coin

examples:
	@if [ -z "$(strip $(SUPRA_RPC_NODE_URL))" ]; then \
		echo "Set SUPRA_RPC_NODE_URL to the node to run the examples against (see examples/README.md)"; \
		exit 1; \
	fi
	@failed=""; \
	for example in $(EXAMPLES); do \
		echo "=== examples.$$example ==="; \
		uv run python -m examples.$$example || failed="$$failed $$example"; \
	done; \
	if [ -n "$$failed" ]; then \
		echo "Failed examples:$$failed"; \
		exit 1; \
	fi; \
	echo "All examples passed"

generate-api-docs:
	uv run sphinx-apidoc -o docs supra_sdk

build-docs:
	rm -rf ./docs/_build && uv run sphinx-build -b html docs docs/_build

docs-all: generate-api-docs build-docs

.PHONY: test-unit test-spec test-all test-coverage fmt fmt-check lint typecheck build audit ci examples generate-api-docs build-docs docs-all
