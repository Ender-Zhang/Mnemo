# Quality Guidelines

> Code quality standards for backend development.

## Package And CI Gate

### Scope / Trigger

Changes that affect public imports, CLI entrypoints, package data, or test discovery must keep the install smoke gate passing.

### Signatures

```bash
python -m unittest discover -s tests
cd "$RUNNER_TEMP"
python -m build "$GITHUB_WORKSPACE" --outdir "$GITHUB_WORKSPACE/dist"
python -m pip install --force-reinstall "$GITHUB_WORKSPACE"/dist/*.whl
MNEMO_REPO_ROOT="$GITHUB_WORKSPACE" python "$GITHUB_WORKSPACE/tests/package_install_smoke.py"
```

### Contracts

- The package name is `mnemo`.
- The console script entrypoint is `mnemo = mnemo.interfaces.cli:main`.
- `python -m mnemo --version` and `mnemo --version` must both return `mnemo <version>`.
- Packaged web assets must include `mnemo/interfaces/web_assets/index.html`, `app.css`, and `app.js`.
- Service/onboard helpers must be importable from an installed wheel because `mnemo service` is used by the one-click installer after installation.
- Installed-package smoke checks must run outside the repository root and fail if `mnemo` imports from the checkout.

### Validation & Error Matrix

| Case | Expected Result |
|------|-----------------|
| Source unit tests fail | CI fails before packaging smoke. |
| Wheel build fails | CI fails before install smoke. |
| Console script is missing or miswired | Install smoke fails on `mnemo --version`. |
| `python -m mnemo` is broken | Install smoke fails on module entrypoint. |
| Package data omits web assets | Install smoke reports missing asset names. |
| Service helper import is missing | Install smoke reports missing service command builder. |
| Smoke imports checkout source | Smoke fails with the resolved source path. |

### Good/Base/Bad Cases

- Good: run tests from source, build the package from a temp directory, install wheel, run smoke from a temp directory.
- Base: local development may run only `python -m unittest discover -s tests` for tight loops.
- Bad: running install smoke from the repo root, because local imports can hide packaging defects.

### Tests Required

- CI must run the source unit suite on supported Python versions.
- CI must build package distributions before install smoke.
- Install smoke must cover package metadata, console script, module entrypoint, service helper imports, and web asset package data.
