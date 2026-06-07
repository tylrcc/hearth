<div align="center">

# 🔥 hearth

**Local-LLM tools for your terminal. No cloud, no API keys, nothing leaves your machine.**

[![CI](https://github.com/tylrcc/hearth/actions/workflows/ci.yml/badge.svg)](https://github.com/tylrcc/hearth/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![Powered by Ollama](https://img.shields.io/badge/powered%20by-Ollama-black.svg)](https://ollama.com)

</div>

---

`hearth` is a small kit of privacy-first command-line tools powered by your **own** local models through [Ollama](https://ollama.com). Two tools today, both designed around one idea: the most sensitive things you do, like your secrets and your source code, should never have to touch someone else's server.

| Tool | What it does |
|------|--------------|
| 🛡️ **`hearth redact`** | Strip API keys, tokens, and PII out of text **before** you paste it into ChatGPT, Claude, a bug report, or a screenshot. Reversible. |
| 🔎 **`hearth search`** | Search your codebase by **meaning** instead of keywords, fully offline. "where do we retry failed payments?" → ranked code. |

Everything runs against `localhost`. There is no telemetry, no account, and no network call that leaves your machine.

---

## Why

Every day people paste production logs, stack traces, and `.env` snippets into a cloud chatbot to debug them, quietly shipping live credentials and customer data to a third party. And every code-search tool that understands *meaning* wants to upload your repo to do it.

`hearth` flips that: the model lives on your laptop, so the privacy problem disappears instead of being managed.

```
┌─────────────┐     ┌──────────┐     ┌─────────────────┐
│  your logs  │ ──▶ │  hearth  │ ──▶ │  safe to share  │
│  your code  │     │ (local)  │     │  ranked results │
└─────────────┘     └────┬─────┘     └─────────────────┘
                         │
                    localhost:11434
                     (Ollama, offline)
```

## Install

```bash
# 1. Install Ollama and pull the models hearth uses
#    https://ollama.com/download
ollama pull nomic-embed-text   # embeddings for search (~270 MB)
ollama pull qwen3.5:9b         # any chat model works; used by --llm / --explain

# 2. Install hearth
pip install hearth-cli         # or: pipx install hearth-cli

# 3. Make sure everything is wired up
hearth doctor
```

```
✓ Ollama       http://localhost:11434
✓ embeddings   nomic-embed-text
✓ chat         qwen3.5:9b
```

> No GPU required. Any model in `ollama list` works; point hearth at a different one with `--model` or the `HEARTH_CHAT_MODEL` / `HEARTH_EMBED_MODEL` env vars.

---

## 🛡️ `hearth redact` — scrub secrets before they leak

Pipe anything in. hearth replaces secrets and PII with stable placeholders and writes a **reversible** map so you can put the real values back into the model's reply.

```bash
$ cat examples/sample.log | hearth redact
```

```text
2026-06-07T09:14:02Z INFO  user <EMAIL_1> signed in from <IPV4_1>
2026-06-07T09:14:03Z DEBUG issuing session jwt <JWT_1>
2026-06-07T09:14:05Z INFO  charging card <CREDIT_CARD_1> via stripe key <STRIPE_KEY_1>
2026-06-07T09:14:06Z WARN  retry against db at <IPV4_2> using token <GITHUB_TOKEN_1>
2026-06-07T09:14:09Z INFO  support callback queued for <PHONE_1>

redacted 2 ipv4, 1 email, 1 jwt, 1 credit_card, 1 stripe_key, 1 github_token, 1 phone
reversible map → .hearth-map.json (restore with `hearth restore`)
```

Now the redacted text is safe to paste into any cloud LLM. When it answers, pipe the answer back through `restore` to recover the originals:

```bash
$ pbpaste | hearth restore   # placeholders → real values again
```

**Detected out of the box (high-precision, regex-validated):** emails, IPv4/IPv6, MAC addresses, phone numbers, US SSNs, credit cards (Luhn-checked), AWS keys, GitHub/Slack/Stripe/OpenAI/Google keys, JWTs, private-key blocks, and generic `SECRET=...` assignments.

**Catch the fuzzy stuff too** — names, street addresses, org names — with an optional local-LLM pass:

```bash
$ hearth redact --llm incident-report.md > safe-report.md
```

The LLM only ever sees your data locally, and hearth trusts only verbatim substrings it returns, so redaction stays reliable even with small models.

---

## 🔎 `hearth search` — find code by meaning, offline

Index once, then ask questions in plain English. Great for landing in an unfamiliar repo or finding "that thing we wrote months ago."

```bash
$ hearth index .                       # build a local embedding index
indexed 482 chunks → ./.hearth  (model: nomic-embed-text)

$ hearth search "where do we validate auth tokens"
```

```text
3 results for where do we validate auth tokens

1. auth/session.py:88   0.91
   def verify_token(raw: str) -> Claims:
       payload = jwt.decode(raw, _public_key(), algorithms=["RS256"])
       if payload["exp"] < time.time():
           raise TokenExpired(payload["sub"])
       ...

2. middleware/guard.py:41   0.84
   ...
```

Add `--explain` for a one-line, locally-generated reason each result matched:

```bash
$ hearth search "rate limiting logic" --explain -k 3
```

The index is just `.hearth/index.npz` (NumPy vectors) plus a small JSON of metadata inside your project. Delete the folder to forget everything. It respects `.gitignore` and skips `node_modules`, `.venv`, build dirs, and binaries automatically.

---

## How it works

- **One dependency-free Ollama client** (`hearth/ollama.py`) talks to `localhost:11434` using only the standard library.
- **Redaction** is a hybrid: deterministic, validated regex detectors do the heavy lifting (a credit-card match must pass a Luhn check, etc.), with an *optional* LLM pass for free-text PII. Overlapping matches are resolved leftmost-longest so spans never collide.
- **Search** chunks files into overlapping windows, embeds them with `nomic-embed-text`, and stores L2-normalised vectors so a query is a single dot product. No vector database to run.

It's ~700 lines of readable Python. Read it in one sitting.

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `OLLAMA_HOST` | `http://localhost:11434` | Where your Ollama server lives |
| `HEARTH_CHAT_MODEL` | `qwen3.5:9b` | Model for `--llm` and `--explain` |
| `HEARTH_EMBED_MODEL` | `nomic-embed-text` | Model for the search index |

## Develop

```bash
git clone https://github.com/tylrcc/hearth
cd hearth
pip install -e ".[dev]"
pytest            # the suite is fully offline; no Ollama needed
```

Contributions welcome, especially new redaction detectors and language-aware chunking. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

- [ ] `hearth redact --diff` to preview spans before writing
- [ ] Tree-sitter chunking so search snippets align to functions
- [ ] Incremental re-indexing (only changed files)
- [ ] A `hearth ask` command: RAG over the local index

## License

[MIT](LICENSE) © tuwfy

<div align="center">
<sub>Built for people who would rather keep their secrets at home. If hearth saved you from a leak, consider leaving a ⭐.</sub>
</div>
