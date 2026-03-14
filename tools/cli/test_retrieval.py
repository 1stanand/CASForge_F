"""
scripts/test_retrieval.py
--------------------------
Interactive retrieval tester.

Type a query, see the top matching steps with their full scenario context -
exactly like IntelliJ autocomplete, but in the terminal.

Usage
-----
    python scripts/test_retrieval.py

Options inside the REPL
-----------------------
  Just type any query and press Enter.

  :top N          Change number of results shown  (default 5)
  :screen <name>  Filter by canonical screen name  (e.g. :screen Committee)
  :keyword <kw>   Filter by step keyword           (e.g. :keyword Then)
  :clear          Clear all active filters
  :filters        Show current active filters
  :context on/off Toggle showing full scenario context (default: on)
  :help           Show this help
  :quit  or  :q   Exit
"""

import os
import sys
import textwrap

# Suppress noisy INFO logs during interactive use
import logging
logging.basicConfig(level=logging.WARNING)
# Keep a clean channel just for our own messages
_log = logging.getLogger("test_retrieval")

from casforge.retrieval.retrieval import search

# -----------------------------------------------------------------------------
# Display helpers
# -----------------------------------------------------------------------------

_W = 78   # terminal width

def _bar(char="-"):
    print(char * _W)

def _wrap(text: str, indent: int = 5) -> str:
    prefix = " " * indent
    return textwrap.fill(text, width=_W, initial_indent=prefix, subsequent_indent=prefix)

def _kw_color(kw: str) -> str:
    """Add simple terminal colour codes to Given/When/Then."""
    colors = {
        "Given": "\033[94m",   # blue
        "When":  "\033[93m",   # yellow
        "Then":  "\033[92m",   # green
        "And":   "\033[96m",   # cyan
        "But":   "\033[95m",   # magenta
    }
    reset = "\033[0m"
    c = colors.get(kw, "")
    return f"{c}{kw}{reset}" if c else kw


def _display_results(results: list[dict], show_context: bool):
    if not results:
        print("\n  No results found.\n")
        return

    print()
    for i, r in enumerate(results, 1):
        _bar()
        # Header line
        score_bar = "â–ˆ" * int(r["score"] * 20)
        print(f"  [{i}]  score={r['score']:.3f}  {score_bar}")
        print()

        # Matched step (highlighted)
        kw   = r.get("keyword", "")
        text = r.get("step_text", "")
        screen = r.get("screen_context") or "-"
        print(f"  STEP   {_kw_color(kw)} {text[:_W - 12]}")
        print(f"  Screen  {screen}")
        print(f"  File    {r.get('file_name', '')}")
        scen = r.get("scenario_title") or "-"
        print(_wrap(f"Scenario  {scen}", indent=2))

        if show_context:
            steps = r.get("scenario_steps", [])
            if steps:
                print()
                print("  -- Scenario steps --------------------------------------")
                matched_text = text.strip().lower()
                for s in steps:
                    skw  = s.get("keyword", "")
                    stxt = s.get("step_text", "")
                    # Mark the matched step with >>
                    marker = ">> " if stxt.strip().lower() == matched_text else "   "
                    line = f"  {marker}{_kw_color(skw)} {stxt}"
                    print(line[:_W + 10])   # +10 for colour escape codes

    _bar("=")
    print(f"  {len(results)} result(s)\n")


# -----------------------------------------------------------------------------
# REPL
# -----------------------------------------------------------------------------

def _print_help():
    print("""
  Commands
  --------
  <query>          Search for steps (any text)
  :top N           Set number of results  (e.g. :top 10)
  :screen <name>   Filter by screen       (e.g. :screen Committee)
  :keyword <kw>    Filter by step keyword (Given / When / Then / And / But)
  :clear           Remove all filters
  :filters         Show current filters
  :context on|off  Show/hide scenario steps (default: on)
  :help            This message
  :q  or  :quit    Exit
""")


def run():
    # State
    top_k          = 5
    screen_filter  = None
    keyword_filter = None
    show_context   = True

    print()
    print("=" * _W)
    print("  CASForge - Interactive Retrieval Test")
    print("  Type a query to search. Type :help for commands.")
    print("=" * _W)
    print()

    while True:
        try:
            filters_hint = ""
            if screen_filter or keyword_filter:
                parts = []
                if screen_filter:  parts.append(f"screen={screen_filter}")
                if keyword_filter: parts.append(f"keyword={keyword_filter}")
                filters_hint = f"  [{', '.join(parts)}]"

            raw = input(f"query{filters_hint}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not raw:
            continue

        # -- Commands ------------------------------------------------------
        if raw.startswith(":"):
            parts = raw[1:].split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd in ("q", "quit", "exit"):
                print("Bye.")
                break

            elif cmd == "help":
                _print_help()

            elif cmd == "top":
                try:
                    top_k = int(arg)
                    print(f"  Showing top {top_k} results.\n")
                except ValueError:
                    print("  Usage: :top <number>\n")

            elif cmd == "screen":
                screen_filter = arg if arg else None
                print(f"  Screen filter: {screen_filter or 'cleared'}\n")

            elif cmd == "keyword":
                kw = arg.capitalize() if arg else None
                if kw and kw not in ("Given", "When", "Then", "And", "But"):
                    print("  Valid keywords: Given When Then And But\n")
                else:
                    keyword_filter = kw
                    print(f"  Keyword filter: {keyword_filter or 'cleared'}\n")

            elif cmd == "clear":
                screen_filter  = None
                keyword_filter = None
                print("  All filters cleared.\n")

            elif cmd == "filters":
                print(f"  top_k         : {top_k}")
                print(f"  screen_filter : {screen_filter or '-'}")
                print(f"  keyword_filter: {keyword_filter or '-'}")
                print(f"  show_context  : {show_context}\n")

            elif cmd == "context":
                if arg.lower() == "off":
                    show_context = False
                    print("  Context display: off\n")
                else:
                    show_context = True
                    print("  Context display: on\n")

            else:
                print(f"  Unknown command: :{cmd}  - type :help\n")

            continue

        # -- Search --------------------------------------------------------
        print(f"\n  Searching: {raw!r}  (top {top_k}) ...\n")
        try:
            results = search(
                query=raw,
                top_k=top_k,
                screen_filter=screen_filter,
                keyword_filter=keyword_filter,
            )
            _display_results(results, show_context)
        except Exception as exc:
            print(f"  ERROR: {exc}\n")


if __name__ == "__main__":
    run()


