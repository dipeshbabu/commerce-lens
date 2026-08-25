# Release process

CommerceLens supports Python 3.10, 3.11, and 3.12. A release must pass the full test matrix,
type check, coverage floor, distribution build, metadata validation, and installed wheel smoke
test before a tag is created.

## Prepare

1. Start from a clean branch based on the latest `main`.
2. Confirm the intended license and distribution rights. Do not publish a proprietary build
   to a public package index by accident.
3. Update the version in both `pyproject.toml` and `commercelens/version.py`.
4. Move release notes into `CHANGELOG.md` and document migrations or breaking changes.
5. Run the complete local validation:

```bash
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
mypy commercelens
pytest --cov --cov-report=term-missing -q
python -m build
twine check dist/*
pip-audit . --strict --progress-spinner off --cache-dir /tmp/pip-audit-cache
```

The coverage floor begins at 70 percent, below the current measured baseline. Raise it as
high value tests are added; do not lower it to make a pull request pass.

## Verify the artifact

Install the wheel into a fresh virtual environment outside the repository. Confirm the
reported version, CLI help, package import, and deterministic fixture extraction. The CI
package job performs this check on every pull request.

Inspect the wheel and source distribution before publishing. They must include package code,
README, metadata, and the current license file, and must not include credentials, databases,
captured pages, customer data, or local environment files.

## Tag and publish

1. Merge the release pull request only after every required check succeeds.
2. Create a signed tag named `v<version>` at the verified `main` commit.
3. Build again from the tag in a clean checkout.
4. Publish only to the package index and deployment environment approved for that license.
5. Create a GitHub release from the changelog and attach the verified distributions.
6. Run API readiness and deterministic extraction smoke checks against the promoted build.

If any validation fails, do not move or replace the tag. Fix the problem in a new pull request
and create a new release version when the corrected commit is ready.
