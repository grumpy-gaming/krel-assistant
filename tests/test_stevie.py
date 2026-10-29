"""Tests that need no AI: a fake provider plays the model's part.

Run from the repo root:  python3 -m unittest -v
Each test gets a throwaway HOME and XDG folders, so nothing touches the real home.
"""

import http.server
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from stevie import config
from stevie.agent import Agent
from stevie.providers import OpenAICompatible, ProviderError
from stevie.tools import TOOLS, Tool


class FakeProvider:
    """Replies with the scripted messages in order and records what it was sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.sent = []

    def chat(self, messages, tools):
        self.sent.append([dict(m) for m in messages])
        return self.replies.pop(0)


def tool_call(name, **args):
    return {"content": "", "tool_calls": [
        {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


class FakeHome(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        env = {"HOME": self.home.name, "XDG_CONFIG_HOME": os.path.join(self.home.name, ".config"),
               "XDG_CACHE_HOME": os.path.join(self.home.name, ".cache")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.home.cleanup)

    def write_config(self, text, mode=0o600):
        os.makedirs(config.config_dir())
        with open(config.config_path(), "w") as f:
            f.write(text)
        os.chmod(config.config_path(), mode)


class ConfigTests(FakeHome):
    def test_defaults_to_local_ollama(self):
        cfg = config.load()
        self.assertEqual(cfg.provider, "ollama")
        self.assertEqual(cfg.base_url, "http://localhost:11434/v1")
        self.assertIsNone(cfg.api_key)

    def test_provider_from_file_and_key_from_environment(self):
        self.write_config('provider = "gemini"\nmodel = "gemini-2.5-flash"\n')
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            cfg = config.load()
        self.assertEqual((cfg.provider, cfg.model, cfg.api_key), ("gemini", "gemini-2.5-flash", "test-key"))
        self.assertIn("generativelanguage.googleapis.com", cfg.base_url)

    def test_command_line_provider_drops_the_files_model(self):
        self.write_config('provider = "gemini"\nmodel = "gemini-2.5-flash"\n')
        cfg = config.load(provider="ollama")
        self.assertEqual(cfg.model, config.DEFAULT_MODEL)

    def test_refuses_a_key_other_users_can_read(self):
        self.write_config('provider = "openrouter"\napi_key = "test-key"\n', mode=0o644)
        with self.assertRaises(config.ConfigError):
            config.load()

    def test_unknown_provider(self):
        with self.assertRaises(config.ConfigError):
            config.load(provider="nope")


class AgentTests(FakeHome):
    def make_agent(self, provider, answer=True):
        self.ran = []
        self.asked = []
        safe = Tool("look", "Read something", lambda: self.ran.append("look") or "all good")
        risky = Tool("change", "Change something", lambda what: self.ran.append(what) or "changed",
                     {"what": ("string", "what to change")}, ("what",), changes=True)

        def confirm(tool, args):
            self.asked.append((tool.name, args))
            return answer
        return Agent(provider, [safe, risky], confirm)

    def test_plain_answer(self):
        agent = self.make_agent(FakeProvider({"content": "Hi there."}))
        self.assertEqual(agent.ask("hello"), "Hi there.")

    def test_read_only_tool_runs_without_asking(self):
        provider = FakeProvider(tool_call("look"), {"content": "Looks fine."})
        agent = self.make_agent(provider)
        self.assertEqual(agent.ask("check"), "Looks fine.")
        self.assertEqual((self.ran, self.asked), (["look"], []))
        self.assertEqual(provider.sent[1][-1], {"role": "tool", "tool_call_id": "call_look", "name": "look", "content": "all good"})

    def test_changing_tool_asks_first(self):
        agent = self.make_agent(FakeProvider(tool_call("change", what="x"), {"content": "Done."}))
        agent.ask("change x")
        self.assertEqual(self.asked, [("change", {"what": "x"})])
        self.assertEqual(self.ran, ["x"])

    def test_no_means_nothing_runs(self):
        provider = FakeProvider(tool_call("change", what="x"), {"content": "OK, left it."})
        agent = self.make_agent(provider, answer=False)
        agent.ask("change x")
        self.assertEqual(self.ran, [])
        self.assertIn("said no", provider.sent[1][-1]["content"])

    def test_bad_calls_are_reported_back_not_run(self):
        provider = FakeProvider(tool_call("nonexistent"), tool_call("change"), {"content": "Sorry."})
        agent = self.make_agent(provider)
        agent.ask("do things")
        self.assertIn("no tool called", provider.sent[1][-1]["content"])
        self.assertIn("Missing required", provider.sent[2][-1]["content"])
        self.assertEqual(self.ran, [])

    def test_extra_arguments_are_dropped(self):
        agent = self.make_agent(FakeProvider(tool_call("change", what="x", sneaky="y"), {"content": "Done."}))
        agent.ask("change x")
        self.assertEqual(self.asked, [("change", {"what": "x"})])

    def test_stops_after_too_many_rounds(self):
        agent = self.make_agent(FakeProvider(*[tool_call("look")] * 20))
        self.assertIn("stopped", agent.ask("loop"))


class ToolTests(FakeHome):
    def test_schemas_are_valid_and_risky_tools_say_what_they_do(self):
        for t in TOOLS:
            schema = t.schema()["function"]
            self.assertEqual(set(schema["parameters"]["required"]) - set(schema["parameters"]["properties"]), set(), t.name)
            json.dumps(schema)
            if t.changes:
                self.assertIsNotNone(t.summary, t.name)

    def test_system_overview_runs(self):
        text = next(t for t in TOOLS if t.name == "system_overview").run()
        self.assertIn("Memory:", text)
        self.assertIn("System disk", text)

    def test_disk_usage_quotes_the_path(self):
        folder = os.path.join(self.home.name, "odd name; echo nope")
        os.makedirs(folder)
        text = next(t for t in TOOLS if t.name == "disk_usage").run(folder)
        self.assertNotIn("\nnope", text)
        self.assertIn("odd name", text)


class ProviderTests(unittest.TestCase):
    """The real HTTP client against a tiny fake OpenAI-compatible server on localhost."""

    def serve(self, status, reply):
        received = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                received["path"] = self.path
                received["auth"] = self.headers.get("Authorization")
                received["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                data = json.dumps(reply).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        cfg = config.Config(provider="openrouter", model="m", base_url=f"http://127.0.0.1:{server.server_port}/v1",
                            api_key="test-key", timeout=5)
        return OpenAICompatible(cfg), received

    def test_sends_model_tools_and_key(self):
        provider, received = self.serve(200, {"choices": [{"message": {"role": "assistant", "content": "hi"}}]})
        tools = [TOOLS[0].schema()]
        reply = provider.chat([{"role": "user", "content": "hello"}], tools)
        self.assertEqual(reply["content"], "hi")
        self.assertEqual(received["path"], "/v1/chat/completions")
        self.assertEqual(received["auth"], "Bearer test-key")
        self.assertEqual((received["body"]["model"], received["body"]["tools"]), ("m", tools))

    def test_http_errors_become_provider_errors(self):
        provider, _ = self.serve(401, {"error": "bad key"})
        with self.assertRaisesRegex(ProviderError, "401"):
            provider.chat([{"role": "user", "content": "hello"}], [])


if __name__ == "__main__":
    unittest.main()
