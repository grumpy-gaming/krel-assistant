"""The stevie command: one question, or a chat when run on its own."""

import argparse
import sys

from stevie import __version__, config
from stevie.agent import Agent
from stevie.providers import OpenAICompatible, ProviderError
from stevie.tools import TOOLS


def confirm(tool, args):
    """Ask before a tool changes anything. Without a terminal to ask in, the answer is no."""
    if not sys.stdin.isatty():
        print(f"Stevie wanted to {tool.describe(args)}, but there is no terminal to ask you in, so it did not.")
        return False
    try:
        answer = input(f"\nStevie wants to {tool.describe(args)}\nGo ahead? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def show_tool(tool, args):
    if not tool.changes:
        detail = ", ".join(f"{k}={v}" for k, v in args.items())
        print(f"  (checking: {tool.name}{' ' + detail if detail else ''})", file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="stevie", description="Stevie, the KrelboyneOS assistant.")
    parser.add_argument("question", nargs="*", help="ask one question; leave out to chat")
    parser.add_argument("--provider", help=f"AI provider: {', '.join(config.PROVIDERS)}")
    parser.add_argument("--model", help="model name for that provider")
    parser.add_argument("--tools", action="store_true", help="list what Stevie can do, then exit")
    parser.add_argument("--version", action="version", version=f"stevie {__version__}")
    args = parser.parse_args(argv)

    if args.tools:
        for t in TOOLS:
            print(f"{t.name:20} {'asks first  ' if t.changes else 'read-only   '}{t.description}")
        return 0

    try:
        cfg = config.load(args.provider, args.model)
    except config.ConfigError as e:
        print(f"stevie: {e}", file=sys.stderr)
        return 1
    agent = Agent(OpenAICompatible(cfg), TOOLS, confirm)

    if args.question:
        return answer(agent, " ".join(args.question))

    print(f"Stevie here ({cfg.provider}, {cfg.model}). Ask away; 'exit' or Ctrl+D to leave.")
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if text.lower() in ("exit", "quit", "bye"):
            return 0
        if text:
            answer(agent, text)


def answer(agent, text):
    try:
        reply = agent.ask(text, on_tool=show_tool)
    except ProviderError as e:
        print(f"stevie: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n(stopped)")
        return 130
    print(f"\nStevie: {reply}")
    return 0
