"""Offline tests: local coder approvals and web-scraping boundaries."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from satoshi.coder import SatoshiCoder
from satoshi.coder_tools import WorkspaceTools
from satoshi.web_tools import validate_public_url
from satoshi.engine import SatoshiEngine


class FakeCall:
    def __init__(self, name, args):
        self.name = name
        self.arguments = args

class FakeAnswer:
    def __init__(self, text="ok", tool_calls=None):
        self.text = text
        self.tool_calls = tool_calls or []
        self.stop_reason = "end_turn"

class FakeProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
    def is_available(self):
        return None
    def complete(self, prompt, messages, schemas):
        return next(self.responses)


class TestCoderPermissions(unittest.TestCase):
    def test_read_safe_create_requires_explicit_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = WorkspaceTools(tmp)
            engine = SatoshiEngine("ollama")
            mock = FakeProvider([
                FakeAnswer(tool_calls=[FakeCall("write_file", {"path": "new.py", "content": "print('safe')\n"})]),
                FakeAnswer("Created new.py after operator approval")])
            coder = SatoshiCoder(engine=engine, tools=tools)
            with patch.object(engine, "_build_provider", return_value=mock):
                result = coder.run("Create a python file")
                self.assertEqual(result["state"], "approval_required")
                self.assertFalse((Path(tmp) / "new.py").exists())
                token = result["pending"]["token"]
                completed = coder.decide(result["session_id"], token, True)
                self.assertEqual(completed["state"], "completed")
                self.assertTrue((Path(tmp) / "new.py").exists())
                with self.assertRaises(ValueError):
                    coder.decide(result["session_id"], token, True)

    def test_denied_write_does_not_change_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            eng = SatoshiEngine("ollama")
            coder = SatoshiCoder(engine=eng, tools=WorkspaceTools(tmp))
            mock = FakeProvider([FakeAnswer(tool_calls=[FakeCall("write_file", {"path": "blocked.py", "content": "x=1"})])])
            with patch.object(eng, "_build_provider", return_value=mock):
                result = coder.run("Write blocked.py")
            denied = coder.decide(result["session_id"], result["pending"]["token"], False)
            self.assertEqual(denied["state"], "denied")
            self.assertFalse((Path(tmp) / "blocked.py").exists())

    def test_workspace_path_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = WorkspaceTools(tmp)
            self.assertEqual(len(tools.registry), 15)
            with self.assertRaises(ValueError):
                tools.execute("read_file", {"path": "../../etc/passwd"})
            with self.assertRaises(ValueError):
                tools.execute("write_file", {"path": ".env", "content": "private"})

    def test_fetch_disallows_internal(self):
        for target in ("http://example.com", "https://127.0.0.1/", "https://localhost/path", "https://metadata.google.internal/"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                validate_public_url(target)


if __name__ == "__main__":
    unittest.main()
