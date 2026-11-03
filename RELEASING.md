# Releasing supra-sdk

This document is for maintainers. A release is published to PyPI by the
[`publish.yaml`](.github/workflows/publish.yaml) workflow when a tag `vX.Y.Z` is pushed.

## One-time setup

1. On PyPI, add a trusted publisher to the `supra-sdk` project (Manage, Publishing): owner `Entropy-Foundation`,
   repository `supra-python-sdk`, workflow `publish.yaml`, environment `pypi`.
2. In the repository settings, create an environment named `pypi`. Restricting it to required reviewers or to tags
   matching `v*` is optional.

The workflow uses PyPI trusted publishing; it needs no API token or repository secret. The publish action uploads
attestations with the distributions.

## Release steps

1. Set `version` in `pyproject.toml` to `X.Y.Z`.
2. Update the changelog.
3. Merge the release pull request into `master`.
4. Tag the merge commit and push the tag:
   `git tag -a vX.Y.Z -m "supra-sdk X.Y.Z" <merge commit> && git push origin vX.Y.Z`.
5. The workflow fails without publishing when the tag is not `v` followed by the version in `pyproject.toml`. Approve
   the `pypi` environment deployment if reviewers are required.
6. Create the GitHub release for the tag, with the changelog entry as its notes. The workflow does not create it.
7. Check that the new version is on PyPI.

The documentation site is built from `master` by the docs workflow and shows the version of the installed package.
