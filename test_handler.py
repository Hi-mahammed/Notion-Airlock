import importlib.util
import io
import json
import pathlib
import unittest
import urllib.error
from unittest.mock import patch


MODULE_DIR = pathlib.Path(__file__).parent
HANDLER_PATH = MODULE_DIR / "handlers" / "handler.py"


spec = importlib.util.spec_from_file_location("notion_handler", HANDLER_PATH)
handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler)


class FakeResponse:
    def __init__(self, payload, status=200):
        self.body = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.body


class NotionHandlerTests(unittest.TestCase):
    def setUp(self):
        handler.__rc_helpers__ = {
            "vault_get": lambda provider: {
                "api_key": "vault-token"
            } if provider == "notion" else None
        }

    def test_credentials_are_read_from_vault_without_environment_fallback(self):
        handler_source = HANDLER_PATH.read_text()
        self.assertNotIn("os.environ", handler_source)
        self.assertNotIn("os.getenv", handler_source)
        self.assertNotIn("environ.get", handler_source)
        self.assertEqual(handler._get_token(), "vault-token")

        handler.__rc_helpers__ = {"vault_get": lambda provider: {}}
        self.assertIsNone(handler._get_token())

    def test_missing_credentials_return_explicit_error(self):
        handler.__rc_helpers__ = {"vault_get": lambda provider: None}

        result = handler.notion_get_page({"page_id": "page-1"}, {})

        self.assertEqual(result["object"], "error")
        self.assertEqual(result["code"], "auth_missing")

    def test_search_uses_vault_token_and_returns_cursor(self):
        payload = {
            "results": [
                {
                    "object": "page",
                    "id": "page-1",
                    "url": "https://www.notion.so/page-1",
                    "archived": False,
                    "parent": {"type": "workspace"},
                    "last_edited_time": "2026-01-01T00:00:00.000Z",
                    "properties": {
                        "Name": {
                            "type": "title",
                            "title": [{"plain_text": "Meeting notes"}],
                        }
                    },
                }
            ],
            "has_more": True,
            "next_cursor": "next-page",
        }

        with patch.object(handler.urllib.request, "urlopen", return_value=FakeResponse(payload)) as urlopen:
            result = handler.notion_search({"query": "meeting", "page_size": 5}, {})

        request = urlopen.call_args.args[0]
        self.assertEqual(result["count"], 1)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["next_cursor"], "next-page")
        self.assertEqual(result["results"][0]["title"], "Meeting notes")
        self.assertEqual(request.headers["Authorization"], "Bearer vault-token")
        self.assertEqual(request.headers["Notion-version"], "2022-06-28")
        self.assertEqual(json.loads(request.data.decode("utf-8"))["page_size"], 5)

    def test_write_failure_is_not_retried(self):
        error = urllib.error.HTTPError(
            "https://api.notion.com/v1/pages/page-1",
            503,
            "temporarily unavailable",
            {},
            io.BytesIO(b'{"code":"service_unavailable","message":"try later"}'),
        )

        with patch.object(handler.urllib.request, "urlopen", side_effect=error) as urlopen:
            result = handler.notion_archive_page({"page_id": "page-1"}, {})

        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(result["code"], "service_unavailable")
        self.assertEqual(result["status"], 503)

    def test_invalid_write_input_fails_before_network(self):
        with patch.object(handler.urllib.request, "urlopen") as urlopen:
            result = handler.notion_append_blocks(
                {"block_id": "page-1", "children": []},
                {},
            )

        self.assertEqual(result["code"], "validation_error")
        urlopen.assert_not_called()

    def test_manifest_has_governed_commands_and_matching_handlers(self):
        manifest = json.loads((MODULE_DIR / "module.json").read_text())

        self.assertEqual(manifest["version"], "0.2.1")
        self.assertTrue(manifest["description"].endswith("contest:2026Q3"))
        self.assertEqual(len(manifest["commands"]), 8)
        for command in manifest["commands"]:
            self.assertTrue(command["id"].startswith("notion."))
            self.assertIn(command["mode"], {"read", "write_requires_approval"})
            self.assertIn(command["risk"], {"low", "high"})
            handler_name = command["id"].replace(".", "_")
            self.assertTrue(callable(getattr(handler, handler_name)))

        writes = [
            command
            for command in manifest["commands"]
            if command["side_effects"] == "external"
        ]
        self.assertEqual(len(writes), 4)
        self.assertTrue(all(command["mode"] == "write_requires_approval" for command in writes))
        self.assertTrue(all(command["preview"] and command["receipt_required"] for command in writes))


if __name__ == "__main__":
    unittest.main()
