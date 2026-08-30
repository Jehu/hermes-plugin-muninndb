from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


def _load_plugin():
    agent_module = types.ModuleType("agent")
    memory_provider_module = types.ModuleType("agent.memory_provider")

    class MemoryProvider:
        pass

    memory_provider_module.MemoryProvider = MemoryProvider
    agent_module.memory_provider = memory_provider_module

    tools_module = types.ModuleType("tools")
    registry_module = types.ModuleType("tools.registry")
    registry_module.tool_error = lambda message: json.dumps({"error": message})
    tools_module.registry = registry_module

    sys.modules["agent"] = agent_module
    sys.modules["agent.memory_provider"] = memory_provider_module
    sys.modules["tools"] = tools_module
    sys.modules["tools.registry"] = registry_module

    plugin_path = Path(__file__).resolve().parents[1] / "__init__.py"
    spec = importlib.util.spec_from_file_location("hermes_plugin_muninndb", plugin_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


plugin = _load_plugin()


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = plugin.MuninnDBProvider()
        self.provider._session_id = "session-123"
        self.provider._hermes_home = ""
        self.provider._platform = "cli"
        self.provider._agent_context = "primary"
        self.provider._tenant = ""
        self.provider._host = "localhost:8475"
        self.provider._vault = "hermes"
        self.provider._threshold = 0.42
        self.provider._base_url = "http://localhost:8475"
        self.provider._api_key = ""
        self.provider._cb_failures = 0
        self.provider._cb_open_until = 0.0
        self.provider._sync_thread = None

    def test_exposes_expected_tools(self):
        names = {schema["name"] for schema in self.provider.get_tool_schemas()}
        self.assertEqual(
            names,
            {
                "muninn_remember",
                "muninn_recall",
                "muninn_read",
                "muninn_forget",
                "muninn_link",
                "muninn_update",
            },
        )

    def test_remember_uses_type_field_and_never_memory_type(self):
        with mock.patch.object(plugin, "_json_request", return_value={"id": "01TEST"}) as request:
            result = json.loads(
                self.provider.handle_tool_call(
                    "muninn_remember",
                    {
                        "concept": "decision",
                        "content": "Use Astro",
                        "memory_type": "Decision",
                        "confidence": 0.9,
                    },
                )
            )
        payload = request.call_args.kwargs["payload"]
        self.assertEqual(payload["type"], 1)
        self.assertNotIn("memory_type", payload)
        self.assertEqual(result["id"], "01TEST")

    def test_recall_uses_configured_threshold_and_coerces_limit(self):
        with mock.patch.object(
            plugin,
            "_json_request",
            return_value={"activations": [], "total_found": 0},
        ) as request:
            self.provider.handle_tool_call("muninn_recall", {"query": "Astro", "limit": "99"})
        payload = request.call_args.kwargs["payload"]
        self.assertEqual(payload["threshold"], 0.42)
        self.assertEqual(payload["max_results"], 20)

    def test_tenant_scopes_concepts_and_tags(self):
        self.provider._tenant = "acme"
        self.assertEqual(self.provider._tenant_prefix("turn"), "acme:turn")
        self.assertEqual(self.provider._tenant_tags(["auto-sync"]), ["auto-sync", "tenant:acme"])

    def test_circuit_breaker_opens_after_threshold(self):
        def fail():
            raise RuntimeError("offline")

        for _ in range(self.provider._CB_FAILURE_THRESHOLD):
            ok, result = self.provider._cb_wrap(fail)
            self.assertFalse(ok)
            self.assertIn("offline", result)
        ok, result = self.provider._cb_wrap(lambda: "unreachable")
        self.assertFalse(ok)
        self.assertIn("Circuit breaker open", result)

    def test_initialize_accepts_url_and_invalid_threshold(self):
        with tempfile.TemporaryDirectory() as hermes_home:
            config_path = Path(hermes_home) / "muninndb.json"
            config_path.write_text(
                '{"host":"https://memory.example.test/","vault":"demo","threshold":"invalid"}',
                encoding="utf-8",
            )
            self.provider.initialize("session", hermes_home=hermes_home)
        self.assertEqual(self.provider._base_url, "https://memory.example.test")
        self.assertEqual(self.provider._threshold, 0.5)


class JsonRequestTests(unittest.TestCase):
    def test_authorization_header_is_omitted_without_key(self):
        response = mock.MagicMock()
        response.read.return_value = b"{}"
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with mock.patch.object(plugin.urllib.request, "urlopen", return_value=response) as urlopen:
            plugin._json_request("http://localhost:8475", "", "GET", "/api/health", max_retries=0)
        request = urlopen.call_args.args[0]
        self.assertNotIn("Authorization", request.headers)

    def test_authorization_header_is_added_for_locked_vault(self):
        response = mock.MagicMock()
        response.read.return_value = b"{}"
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with mock.patch.object(plugin.urllib.request, "urlopen", return_value=response) as urlopen:
            plugin._json_request("http://localhost:8475", "test-key", "GET", "/api/health", max_retries=0)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.headers["Authorization"], "Bearer test-key")


if __name__ == "__main__":
    unittest.main()
