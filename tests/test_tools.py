"""The Dify tool and provider classes, with the HTTP layer faked."""

import base64

import pytest
from conftest import FAKE_KEY, messages
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from _onlinecompiler import OnlineCompilerError
from provider.onlinecompiler import OnlineCompilerProvider
from tools.list_compilers import ListCompilersTool
from tools.run_code import RunCodeTool
from tools.run_tests import RunTestsTool

PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 8


def run_answer(**fields):
    return {
        "output": "42\n",
        "error": "",
        "status": "success",
        "exit_code": 0,
        "signal": None,
        "truncated": False,
        "time": "0.0310",
        "total": "0.0400",
        "memory": "9000",
        "files": [],
        "files_truncated": False,
        "time_limit": 30,
        "memory_limit": 512,
        **fields,
    }


class TestRunCodeTool:
    def test_messages(self, http):
        http.answer(200, run_answer())
        out = messages(RunCodeTool, {"compiler": "python-3.14", "code": "print(6*7)", "input": None})
        assert http.last.url.endswith("/api/run-code-sync/")
        assert http.last.json == {"compiler": "python-3.14", "code": "print(6*7)", "input": ""}
        assert http.last.headers["Authorization"] == FAKE_KEY
        assert out.types == ["text"] + ["json"] + ["variable"] * 7
        assert out.text.startswith("Ran python-3.14: success, exit code 0")
        assert out.json[0]["output"] == "42\n"
        assert out.json[0]["files"] == []
        assert out.variables == {
            "output": "42\n",
            "error": "",
            "status": "success",
            "exit_code": 0,
            "time": "0.0310",
            "memory": "9000",
            "truncated": False,
        }
        assert out.blobs == []

    def test_files_come_back_as_blobs(self, http):
        png = {
            "name": "figure-1.png",
            "mime": "image/png",
            "size": len(PNG),
            "content_base64": base64.b64encode(PNG).decode(),
            "url": "https://api.onlinecompiler.io/api/files/9/",
        }
        http.answer(200, run_answer(output="", files=[png]))
        out = messages(RunCodeTool, {"code": "import matplotlib"})
        assert len(out.blobs) == 1
        assert out.blobs[0].message.blob == PNG
        assert out.blobs[0].meta == {"mime_type": "image/png", "filename": "figure-1.png"}
        assert out.json[0]["files"] == [
            {"name": "figure-1.png", "mime": "image/png", "size": len(PNG), "url": png["url"]}
        ]
        assert "Files: figure-1.png (image/png" in out.text

    def test_failed_run_is_a_normal_result(self, http):
        http.answer(200, run_answer(status="error", exit_code=1, output="", error="NameError: x\n"))
        out = messages(RunCodeTool, {"code": "x"})
        assert out.variables["status"] == "error"
        assert "Errors:\nNameError: x" in out.text

    def test_api_refusal_raises_without_the_key(self, http):
        http.answer(404, {"error": "Invalid or inactive API key"})
        with pytest.raises(OnlineCompilerError) as caught:
            messages(RunCodeTool, {"code": "print(1)"})
        assert "HTTP 404" in str(caught.value)
        assert FAKE_KEY not in str(caught.value)

    def test_bad_parameters_make_no_request(self, http):
        with pytest.raises(OnlineCompilerError, match="time_limit"):
            messages(RunCodeTool, {"code": "print(1)", "time_limit": 99})
        assert http.calls == []

    def test_missing_key_makes_no_request(self, http):
        with pytest.raises(OnlineCompilerError, match="API key"):
            messages(RunCodeTool, {"code": "print(1)"}, creds={})
        assert http.calls == []


class TestRunTestsTool:
    ANSWER = {
        "verdict": "accepted",
        "score": 100.0,
        "passed": 2,
        "total": 2,
        "time_limit": 2,
        "memory_limit": 512,
        "compile_error": None,
        "tests": [
            {
                "verdict": "accepted",
                "hidden": False,
                "time": "0.02",
                "memory": "8000",
                "exit_code": 0,
                "signal": None,
                "output": "5\n",
                "error": "",
                "truncated": False,
                "files": [],
                "files_truncated": False,
            },
            {"verdict": "accepted", "hidden": True},
        ],
        "summary": "All 2 tests passed.",
        "submission": "sub_" + "b" * 24,
        "receipt": {"receipt": "rcpt_1"},
    }

    def test_messages(self, http):
        http.answer(200, self.ANSWER)
        tests = '[{"input": "2 3", "expected_output": "5"}, {"input": "1 1", "expected_output": "2", "hidden": true}]'
        out = messages(RunTestsTool, {"compiler": "python-3.14", "code": "print(sum(map(int, input().split())))",
                                      "tests": tests, "checker": "tokens"})
        assert http.last.url.endswith("/api/run-tests/")
        assert http.last.json["tests"][1] == {"input": "1 1", "expected_output": "2", "hidden": True}
        assert http.last.json["checker"] == "tokens"
        assert http.last.json["scoring"] == "percent"
        assert out.types == ["text"] + ["json"] + ["variable"] * 7
        assert out.text == "Verdict: accepted. Score 100 (2 of 2 tests passed).\nAll 2 tests passed."
        assert "receipt" not in out.json[0]
        assert out.json[0]["tests"][1] == {"verdict": "accepted", "hidden": True}
        assert out.variables["verdict"] == "accepted"
        assert out.variables["compile_error"] == ""
        assert out.blobs == []

    def test_bad_tests_make_no_request(self, http):
        with pytest.raises(OnlineCompilerError, match="expected_output"):
            messages(RunTestsTool, {"code": "x", "tests": '[{"input": "1"}]'})
        assert http.calls == []

    def test_plan_limit(self, http):
        http.answer(400, {"error": "tests must be a list of 1 to 10 tests on this plan"})
        with pytest.raises(OnlineCompilerError, match="HTTP 400\\): tests must be a list of 1 to 10 tests"):
            messages(RunTestsTool, {"code": "x", "tests": '[{"expected_output": "1"}]'})


class TestListCompilersTool:
    def test_messages(self, http):
        http.answer(
            200,
            {
                "compilers": [
                    {"id": "python-3.14", "name": "Python 3.14"},
                    {"id": "nodejs-24-tests", "name": "Node.js 24 (tests)", "pack": {}},
                ],
                "retired": {},
            },
        )
        out = messages(ListCompilersTool, {}, creds={})
        assert "Authorization" not in http.last.headers
        assert out.types == ["text", "json"]
        assert out.json[0] == {"compilers": [{"id": "python-3.14", "name": "Python 3.14"}], "retired": {}}
        assert "python-3.14: Python 3.14" in out.text


class TestProvider:
    def test_valid_key(self, http):
        http.answer(200, {"month": "2026-11"})
        assert OnlineCompilerProvider().validate_credentials({"api_key": f"Bearer {FAKE_KEY}"}) is None
        assert http.last.url.endswith("/api/usage/")
        assert http.last.headers["Authorization"] == FAKE_KEY

    @pytest.mark.parametrize(("status", "text"), [(404, "HTTP 404"), (403, "type API"), (503, "HTTP 503")])
    def test_refused_key(self, http, status, text):
        http.answer(status, {"error": "nope"})
        with pytest.raises(ToolProviderCredentialValidationError, match=text) as caught:
            OnlineCompilerProvider().validate_credentials({"api_key": FAKE_KEY})
        assert FAKE_KEY not in str(caught.value)

    def test_empty_key(self, http):
        with pytest.raises(ToolProviderCredentialValidationError, match="API key"):
            OnlineCompilerProvider().validate_credentials({"api_key": ""})
        assert http.calls == []
