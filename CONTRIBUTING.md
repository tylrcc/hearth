# Contributing to hearth

Thanks for taking the time to help! hearth aims to stay small, readable, and
fully local. Pull requests of any size are welcome.

## Getting set up

```bash
git clone https://github.com/tylrcc/hearth
cd hearth
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

The test suite is **fully offline** — embeddings and LLM calls are stubbed, so
you do not need Ollama running to develop or to pass CI.

## Good first contributions

- **New redaction detectors.** Add a `Detector` to `hearth/redact/detectors.py`
  with a high-precision pattern (and a `validate` callback if false positives are
  likely, like the Luhn check on credit cards). Add a case to
  `tests/test_redact.py`.
- **Language-aware chunking** for search, so snippets align to function and class
  boundaries instead of fixed line windows.
- **Docs and examples.**

## Principles

1. **Nothing leaves the machine.** No network calls except to the local Ollama
   host. No telemetry.
2. **Deterministic core, optional intelligence.** Regex/validation should do the
   high-confidence work; the LLM is an opt-in enhancement, never a requirement.
3. **Keep dependencies minimal.** Right now: `click`, `rich`, `numpy`. Please
   discuss before adding more.
4. **Readable over clever.** Someone should be able to read the whole codebase in
   one sitting.

## Submitting

- Run `pytest` and make sure it passes.
- Keep PRs focused; one idea per PR is easiest to review.
- Describe the user-facing behaviour change in the PR description.
