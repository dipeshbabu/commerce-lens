# Contributing to CommerceLens

Thank you for helping improve CommerceLens. Bug reports, focused design proposals,
documentation fixes, tests, and code changes are welcome.

## Before you contribute

Search the issue tracker before opening a new issue. For a substantial feature or
architecture change, open an issue first so maintainers and contributors can agree on the
problem, scope, and acceptance criteria before implementation starts.

Do not include credentials, customer URLs, captured customer pages, personal data, or other
sensitive material in an issue, fixture, log, or pull request. Follow [SECURITY.md](SECURITY.md)
for vulnerability reports.

## Current license status

The repository is public, but its current `LICENSE` and package metadata are proprietary.
Public source visibility is not the same as an open source license. Issue
[#14](https://github.com/dipeshbabu/commerce-lens/issues/14) tracks the maintainer decision
needed to adopt an open source license and define permanent inbound contribution terms.

Until that decision is complete, discuss nontrivial code contributions with the maintainer
before investing significant work. A pull request does not change the license or grant rights
beyond the current `LICENSE`.

## Development setup

CommerceLens supports Python 3.10, 3.11, and 3.12.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
ruff check .
pytest -q
```

The default test suite must be deterministic and must not require live commerce sites,
customer accounts, or paid services.

## Working on an issue

1. Comment on the issue you intend to address when coordination would help.
2. Create a focused branch from the latest `main`.
3. Keep the change limited to one problem and preserve compatibility unless the issue says
   otherwise.
4. Add tests that fail before the fix and pass afterward.
5. Update user or operator documentation when behavior or configuration changes.
6. Run the same checks as CI before opening the pull request.

For extractor or matching changes, include representative local fixtures and run the relevant
quality or benchmark commands documented in `docs/extraction_quality.md`. Never replace a
deterministic fixture with a live network test.

## Pull request expectations

Every pull request should:

* link its issue with `Closes #<number>` when it fully resolves the issue;
* explain the user or operator problem, not only the implementation;
* state compatibility, security, data migration, and deployment effects;
* list the exact validation performed;
* avoid drive by formatting or unrelated refactoring;
* pass all required CI checks before merge.

Maintainers may ask to split a broad pull request into smaller changes. Pull requests are
squash merged after review and successful CI.

## Style and design

Prefer small modules, explicit boundaries, typed models, and deterministic behavior. Reuse
the existing public interfaces unless a breaking change is intentional and documented.
Treat all fetched URLs and remote content as untrusted input. Keep secrets out of errors and
logs, preserve tenant scoping, and add negative tests for security sensitive code.

All project interactions must follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
