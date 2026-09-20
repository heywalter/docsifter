# Contributing

Thanks for helping improve DocSifter.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -r requirements-dev.txt
```

Run the lightweight checks before opening a pull request:

```bash
ruff check .
ruff format --check .
python -m pytest tests/smoke
node --test tests/js/*.test.js
```

CI runs the same checks on every pull request (`.github/workflows/ci.yml`:
lint, the smoke suite on Python 3.10 and 3.13, the frontend tests, the
benchmark, and an install of the built wheel). Running them locally first still
saves a round trip.

Live model, GPU, SMTP delivery, and GitHub network checks are intentionally out
of the default path. Keep those as manual verification unless the test is fully
isolated and needs no external credentials or model downloads. The suite covers
isolated email and GitHub workflow behavior without touching the network.

The benchmark runner is worth running too when you change rules or protection
logic; it exits non-zero if a protection sample was modified or a rule produced
a wrong fix:

```bash
python3 benchmarks/run_benchmark.py
```

If you change the markup or the front-end scripts, regenerate the vendored Web
UI assets so the Tailwind subset still covers every class the UI uses, and
commit the result:

```bash
python3 tools/build_vendor_assets.py
```

## Pull Requests

- Keep changes focused and documented.
- Do not commit local credentials, generated reports, databases, logs, or large
  validation manuals.
- Add or update tests for behavior changes.
- Update README or docs when commands, configuration, or workflows change.
