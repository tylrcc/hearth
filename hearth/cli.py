"""hearth command-line interface."""

from __future__ import annotations

import os
import sys

import click
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from . import __version__
from .backends import BACKEND_CHOICES, BackendError, get_backend
from .ollama import DEFAULT_CHAT_MODEL, DEFAULT_EMBED_MODEL
from .redact import load_map, redact, restore, save_map
from .search import build_index, search

console = Console()
err = Console(stderr=True)

DEFAULT_MAP = ".hearth-map.json"


def _fail(message: str) -> None:
    err.print(f"[bold red]error[/] {message}")
    sys.exit(1)


def backend_options(f):
    """Shared --backend / --url options for commands that run a model."""
    f = click.option("--url", "base_url", default=None, metavar="URL",
                     help="Override the backend base URL "
                          "(e.g. http://localhost:8080/v1).")(f)
    f = click.option("--backend", default=None,
                     help=f"Inference backend: {', '.join(BACKEND_CHOICES)} "
                          "(default: ollama, or $HEARTH_BACKEND).")(f)
    return f


def _open_backend(backend: str | None, base_url: str | None):
    """Build a backend and make sure it is reachable, or exit with a clear error."""
    try:
        client = get_backend(backend, base_url)
    except BackendError as exc:
        _fail(str(exc))
    if not client.is_up():
        err.print(f"[bold red]error[/] {client.label} not reachable at "
                  f"{client.endpoint}. {client.start_hint}")
        sys.exit(1)
    return client


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="hearth")
def main() -> None:
    """Local-LLM tools for your terminal. No cloud, no API keys.

    \b
    hearth redact   strip secrets & PII from text before pasting to any LLM
    hearth restore  put the originals back into the model's reply
    hearth index    build a local semantic index of a codebase
    hearth search   find code by meaning, fully offline

    \b
    Backends: Ollama (default), llama.cpp, MLX, LM Studio, vLLM, or any
    OpenAI-compatible server. Pick one with --backend / $HEARTH_BACKEND.
    """


# --------------------------------------------------------------------------- #
# redact / restore
# --------------------------------------------------------------------------- #
@main.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True, dir_okay=False))
@click.option("--llm", "use_llm", is_flag=True,
              help="Add a local-LLM pass for names, addresses, and orgs.")
@click.option("--model", default=DEFAULT_CHAT_MODEL, show_default=True,
              help="Chat model for the --llm pass.")
@click.option("--map", "map_path", default=DEFAULT_MAP, show_default=True,
              help="Where to write the reversible redaction map.")
@click.option("--no-map", is_flag=True, help="Do not write a map (irreversible).")
@click.option("-i", "--in-place", is_flag=True, help="Rewrite the input files.")
@click.option("--stats/--no-stats", default=True, help="Print a summary to stderr.")
@backend_options
def redact_cmd(files, use_llm, model, map_path, no_map, in_place, stats,
               backend, base_url):
    """Redact secrets & PII from FILES or stdin."""
    client = _open_backend(backend, base_url) if use_llm else None
    source = (
        {f: open(f, encoding="utf-8", errors="ignore").read() for f in files}
        if files else {"-": sys.stdin.read()}
    )

    merged_map: dict[str, str] = {}
    total = 0
    label_counts: dict[str, int] = {}
    for name, text in source.items():
        result = redact(text, use_llm=use_llm, model=model, client=client)
        # Offset placeholder numbers so maps across files don't collide.
        merged_map.update(result.mapping)
        total += result.total
        for label, n in result.counts.items():
            label_counts[label] = label_counts.get(label, 0) + n
        if in_place and name != "-":
            with open(name, "w", encoding="utf-8") as fh:
                fh.write(result.text)
        else:
            sys.stdout.write(result.text)
            if not result.text.endswith("\n"):
                sys.stdout.write("\n")

    if not no_map and merged_map:
        save_map(map_path, merged_map)

    if stats:
        if total:
            summary = ", ".join(f"{n} {lbl.lower()}" for lbl, n in
                                sorted(label_counts.items(), key=lambda x: -x[1]))
            err.print(f"[bold green]redacted[/] {summary}")
            if not no_map:
                err.print(f"[dim]reversible map -> {map_path} "
                          f"(restore with `hearth restore`)[/]")
        else:
            err.print("[dim]no secrets or PII found[/]")


main.add_command(redact_cmd, name="redact")


@main.command(name="restore")
@click.argument("files", nargs=-1, type=click.Path(exists=True, dir_okay=False))
@click.option("--map", "map_path", default=DEFAULT_MAP, show_default=True,
              help="The map written by `hearth redact`.")
def restore_cmd(files, map_path):
    """Reverse redaction: swap placeholders back to the originals.

    Handy for un-redacting an LLM's reply: paste it in, get real values back.
    """
    if not os.path.exists(map_path):
        _fail(f"map not found: {map_path}")
    mapping = load_map(map_path)
    text = (
        "".join(open(f, encoding="utf-8").read() for f in files)
        if files else sys.stdin.read()
    )
    sys.stdout.write(restore(text, mapping))


# --------------------------------------------------------------------------- #
# index / search
# --------------------------------------------------------------------------- #
@main.command(name="index")
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--model", default=DEFAULT_EMBED_MODEL, show_default=True,
              help="Embedding model (must be served by your backend).")
@backend_options
def index_cmd(path, model, backend, base_url):
    """Build a local semantic index of the codebase at PATH."""
    client = _open_backend(backend, base_url)
    with console.status(f"[bold]Indexing[/] {os.path.abspath(path)} ..."):
        def progress(done, total):
            console.print(f"  embedded {done}/{total} chunks", end="\r")
        try:
            store = build_index(path, model=model, client=client, progress=progress)
        except ValueError as exc:
            _fail(str(exc))
    console.print(
        f"[bold green]indexed[/] {len(store.chunks)} chunks "
        f"-> {os.path.join(path, '.hearth')}  [dim](model: {model})[/]"
    )


@main.command(name="search")
@click.argument("query")
@click.option("--path", default=".", type=click.Path(exists=True, file_okay=False),
              help="Project root containing the .hearth index.")
@click.option("-k", "--top", default=5, show_default=True, help="Number of results.")
@click.option("--explain/--no-explain", default=False,
              help="Add a one-line LLM explanation per hit.")
@click.option("--model", default=DEFAULT_CHAT_MODEL, show_default=True,
              help="Chat model used for --explain.")
@backend_options
def search_cmd(query, path, top, explain, model, backend, base_url):
    """Find code by MEANING, e.g. hearth search "where we retry payments"."""
    client = _open_backend(backend, base_url)
    try:
        hits = search(path, query, k=top, explain=explain, chat_model=model,
                      client=client)
    except FileNotFoundError as exc:
        _fail(str(exc))
    except BackendError as exc:
        _fail(str(exc))

    if not hits:
        console.print("[dim]no matches[/]")
        return

    console.print(f"\n[bold]{len(hits)}[/] results for [italic cyan]{query}[/]\n")
    for rank, hit in enumerate(hits, 1):
        loc = f"{hit.chunk.path}:{hit.chunk.start_line}"
        header = Text()
        header.append(f"{rank}. ", style="bold")
        header.append(loc, style="bold cyan")
        header.append(f"  {hit.score:.2f}", style="dim")
        console.print(header)
        if hit.explanation:
            console.print(f"   [italic]{hit.explanation}[/]")
        preview = "\n".join(hit.chunk.text.splitlines()[:6])
        lang = os.path.splitext(hit.chunk.path)[1].lstrip(".") or "text"
        console.print(Syntax(preview, lang, theme="ansi_dark",
                             line_numbers=False, background_color="default"))
        console.print()


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
@main.command()
@backend_options
def doctor(backend, base_url):
    """Check that your inference backend is reachable and has the right models."""
    try:
        client = get_backend(backend, base_url)
    except BackendError as exc:
        _fail(str(exc))
    table = Table(show_header=False, box=None)
    if not client.is_up():
        err.print(f"[bold red]✗[/] {client.label} not reachable at {client.endpoint}")
        err.print(f"[dim]  {client.start_hint}[/]")
        sys.exit(1)
    table.add_row(f"[green]✓[/] {client.label}", f"[dim]{client.endpoint}[/]")
    models = client.models()
    if client.kind == "ollama":
        for label, want in [("embeddings", DEFAULT_EMBED_MODEL),
                            ("chat", DEFAULT_CHAT_MODEL)]:
            present = any(m == want or m.startswith(want + ":") for m in models)
            mark = "[green]✓[/]" if present else "[yellow]•[/]"
            hint = "" if present else f"  [dim](ollama pull {want})[/]"
            table.add_row(f"{mark} {label}", f"{want}{hint}")
    else:
        served = ", ".join(models[:4]) if models else "none reported"
        table.add_row("[green]✓[/] served", f"[dim]{served}[/]")
    console.print(table)


if __name__ == "__main__":
    main()
