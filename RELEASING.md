# Releasing supra-sdk

This document is for maintainers. A release is published to PyPI by the
[`publish.yaml`](.github/workflows/publish.yaml) workflow when a tag `vX.Y.Z` is pushed.

PyPI already has 0.1.0 and 0.1.1, so the first version published by this workflow must be above 0.1.1.

## One-time setup

The PyPI trusted publisher checks only the repository, the workflow file name and the environment name, and a tag push
runs the workflow as it exists at the tagged commit. Steps 2 and 3 are therefore required: they decide who can publish.

1. On PyPI, add a trusted publisher to the `supra-sdk` project (Manage, Publishing): owner `Entropy-Foundation`,
   repository `supra-python-sdk`, workflow `publish.yaml`, environment `pypi`.
2. In the repository settings, create an environment named `pypi` with required reviewers.
3. In the repository settings, add a tag ruleset for `refs/tags/v*` that restricts creation, update and deletion to
   maintainers.

The workflow uses PyPI trusted publishing; it needs no API token or repository secret. The publish action uploads
attestations with the distributions.

## Release steps

Release tags go only on commits on `master`.

1. Set `version` in `pyproject.toml` to `X.Y.Z`.
2. Add the entry for `X.Y.Z` to `CHANGELOG.md`.
3. Merge the release pull request into `master`.
4. Tag the commit that the release pull request produced on `master` and push the tag:
   `git tag -a vX.Y.Z -m "supra-sdk X.Y.Z" <commit> && git push origin vX.Y.Z`.
5. The workflow fails without publishing when the tag is not `v` followed by the version in `pyproject.toml`, or when
   the tagged commit is not an ancestor of `origin/master`. These checks catch mistakes; the environment reviewers and
   the tag ruleset are what restrict publishing. A reviewer approves the `pypi` environment deployment.
6. Create the GitHub release for the tag, with the `CHANGELOG.md` entry as its notes. The workflow does not create it.
7. Check that the new version is on PyPI.

The documentation site is built from `master` by the docs workflow and shows the version of the installed package.
