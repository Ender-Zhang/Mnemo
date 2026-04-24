# Implement CI Package Install Smoke Tests

## Goal

Add a lightweight CI gate that proves Mnemo can be tested from source, built as a package, installed from the wheel, and launched through both supported CLI entrypoints.

## Scope

- Add a GitHub Actions workflow for Python CI.
- Run the existing unit suite from source.
- Build source and wheel distributions.
- Install the built wheel.
- Run an installed-package smoke script from outside the repository root.
- Verify the console script, `python -m mnemo`, package metadata, and bundled web assets.
- Update the implementation checklist.

## Acceptance

- [x] CI workflow runs on pushes to `main` and pull requests.
- [x] CI uses supported Python versions and runs `python -m unittest discover -s tests`.
- [x] CI builds package distributions before install smoke checks.
- [x] Installed-package smoke verifies `mnemo --version`, `python -m mnemo --version`, import metadata, and bundled `web_assets`.
- [x] Smoke script fails if imports resolve to the checkout source tree instead of the installed package.
- [x] Local validation passes.
- [x] Changes are committed and pushed.
