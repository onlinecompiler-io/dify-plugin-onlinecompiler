# dify_plugin patches the standard library with gevent when it is imported, as it is first in main.py at run time.
# Imported after ssl (which requests loads), the patch breaks HTTPS with a RecursionError, so it comes first here too.
import dify_plugin  # noqa: F401, I001

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import _onlinecompiler  # noqa: E402

FAKE_KEY = "fake-key-0123456789abcdef"
CREDS = {"api_key": FAKE_KEY}


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else (json.dumps(body) if body is not None else "")

    def json(self):
        if self._body is None:
            raise ValueError("not JSON")
        return self._body


class FakeHttp:
    """Stands in for requests.request: records each call and answers with the queued responses (or exceptions)."""

    def __init__(self):
        self.calls = []
        self.responses = []

    def answer(self, status_code=200, body=None, text=None):
        self.responses.append(FakeResponse(status_code, body, text))

    def fail(self, exc):
        self.responses.append(exc)

    def __call__(self, method, url, **kwargs):
        self.calls.append(SimpleNamespace(method=method, url=url, **kwargs))
        response = self.responses.pop(0) if self.responses else FakeResponse(200, {})
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def last(self):
        return self.calls[-1]


@pytest.fixture
def http(monkeypatch):
    fake = FakeHttp()
    monkeypatch.setattr(_onlinecompiler.requests, "request", fake)
    return fake


def messages(tool_cls, params, creds=None):
    """Run a tool's _invoke and sort its messages by type."""
    tool = tool_cls.from_credentials(CREDS if creds is None else creds)
    msgs = list(tool._invoke(params))
    by_type = {}
    for msg in msgs:
        by_type.setdefault(msg.type.value, []).append(msg)
    return SimpleNamespace(
        all=msgs,
        types=[m.type.value for m in msgs],
        text="\n".join(m.message.text for m in by_type.get("text", [])),
        json=[m.message.json_object for m in by_type.get("json", [])],
        variables={m.message.variable_name: m.message.variable_value for m in by_type.get("variable", [])},
        blobs=by_type.get("blob", []),
    )


__all__ = ["CREDS", "FAKE_KEY", "FakeHttp", "messages", "requests"]
