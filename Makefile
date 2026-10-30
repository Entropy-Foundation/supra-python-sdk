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

examples:
	uv run python -m examples.automation
	uv run python -m examples.fee_payer_transfer_coin
	uv run python -m examples.multisig
	uv run python -m examples.rotate_key
	uv run python -m examples.simple_nft
	uv run python -m examples.simple_supra_token
	uv run python -m examples.simulate_transfer_coin
	uv run python -m examples.supra_token
	uv run python -m examples.transfer_coin
	uv run python -m examples.transfer_two_by_two
	uv run python -m examples.your_coin

generate-api-docs:
	uv run sphinx-apidoc -o docs supra_sdk

build-docs:
	rm -rf ./docs/_build && uv run sphinx-build -b html docs docs/_build

docs-all: generate-api-docs build-docs

.PHONY: test-unit test-spec test-all test-coverage fmt fmt-check lint typecheck build audit ci examples generate-api-docs build-docs docs-all
