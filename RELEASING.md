# Releasing supra-sdk

This document is for maintainers. A maintainer publishes each release to PyPI by hand. When a tag `vX.Y.Z` is pushed,
the [`release.yaml`](.github/workflows/release.yaml) workflow builds the distributions from the tagged commit. The
maintainer then uploads the files from that workflow run to PyPI.

## One-time setup

1. On PyPI, get the Owner or Maintainer role on the `supra-sdk` project.
2. On PyPI, create an API token with the scope `Project: supra-sdk` (Account settings, API tokens). Keep the token out
   of the repository. Anyone who holds the token can publish, so keep the number of token holders small.
3. On GitHub, check that you can bypass the `release-tags` ruleset (repository settings, Rules, Rulesets). The ruleset
   restricts the creation, update and deletion of `refs/tags/v*`, so only a user who can bypass it can push a release
   tag.

PyPI accepts attestations only from trusted publishing. Releases uploaded with an API token have no attestations.

## Release steps

Release tags go only on commits on `master`.

1. Set `version` in `pyproject.toml` to `X.Y.Z`.
2. Add the entry for `X.Y.Z` to `CHANGELOG.md`.
3. Merge the release pull request into `master`.
4. Tag the commit that the release pull request produced on `master` and push the tag:
   `git tag -a vX.Y.Z -m "supra-sdk X.Y.Z" <commit> && git push origin vX.Y.Z`.
5. Wait for the `Release build` run of the tag to pass, and note its run ID from `gh run list --workflow release.yaml`.
   The run fails when the tag is not `v` followed by the version in `pyproject.toml`, or when the tagged commit is not
   an ancestor of `origin/master`.
6. Download the distributions of the run into a new, empty directory:

   ```bash
   gh run download <run-id> --name dist --dir <release-dir>
   ```

   The directory contains `supra_sdk-X.Y.Z-py3-none-any.whl` and `supra_sdk-X.Y.Z.tar.gz`.
7. Check the metadata of both files:

   ```bash
   uvx twine@7.0.0 check <release-dir>/*
   ```

8. Upload both files to PyPI. `read` takes the token without echoing it or saving it in the shell history:

   ```bash
   read -rs UV_PUBLISH_TOKEN && export UV_PUBLISH_TOKEN
   uv publish <release-dir>/*
   ```

   Upload only the files from the workflow run, not the files in your local `dist/`. A local build can include
   uncommitted changes, and `uv publish` without arguments uploads every file in `dist/`. PyPI does not accept the same
   file name twice, so you cannot replace a file after you upload it. To fix a bad release, yank it on PyPI and release
   a new version.
9. Create the GitHub release for the tag, with the `CHANGELOG.md` entry as its notes, and attach both files.
10. Check that the new version is on PyPI: `pip install supra-sdk==X.Y.Z` in a new virtual environment installs it.

The docs workflow builds the documentation site from `master`. The site shows the version of the installed package.
