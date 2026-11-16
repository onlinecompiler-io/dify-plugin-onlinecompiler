"""Live checks against the real OnlineCompiler.io API, run only when ONLINECOMPILER_API_KEY is set:

    ONLINECOMPILER_API_KEY=your-key python -m pytest -q tests/test_live.py

They call the tool classes directly, as Dify would, and use about eight runs of the key's allowance."""

import os

import pytest
import yaml
from conftest import ROOT, messages
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from _onlinecompiler import OnlineCompilerError
from provider.onlinecompiler import OnlineCompilerProvider
from tools.list_compilers import ListCompilersTool
from tools.run_code import RunCodeTool
from tools.run_tests import RunTestsTool

KEY = os.environ.get("ONLINECOMPILER_API_KEY", "")
pytestmark = pytest.mark.skipif(not KEY, reason="set ONLINECOMPILER_API_KEY to run the live checks")


def creds():
    return {"api_key": KEY}


def test_provider_accepts_the_key_and_refuses_a_wrong_one():
    assert OnlineCompilerProvider().validate_credentials(creds()) is None
    with pytest.raises(ToolProviderCredentialValidationError, match="HTTP 404"):
        OnlineCompilerProvider().validate_credentials({"api_key": "not-a-real-key-000"})


def test_run_code_with_input():
    code = "name = input()\nprint(f'Hello, {name}!')\nimport sys\nprint('to stderr', file=sys.stderr)\n"
    out = messages(RunCodeTool, {"compiler": "python-3.14", "code": code, "input": "Dify\n", "time_limit": 5},
                   creds=creds())
    assert out.variables["output"] == "Hello, Dify!\n"
    assert out.variables["error"] == "to stderr\n"
    assert out.variables["status"] == "success"
    assert out.variables["exit_code"] == 0
    assert out.json[0]["time_limit"] == 5
    assert out.text.startswith("Ran python-3.14: success, exit code 0")


def test_run_code_in_c_with_a_runtime_error():
    code = "#include <stdio.h>\nint main(void) { printf(\"partial\\n\"); return 3; }\n"
    out = messages(RunCodeTool, {"compiler": "gcc-15", "code": code}, creds=creds())
    assert out.variables["output"] == "partial\n"
    assert out.variables["exit_code"] == 3
    assert out.variables["status"] == "error"


def test_run_code_returns_a_chart_as_an_image():
    code = (
        "import matplotlib.pyplot as plt\n"
        "plt.plot([1, 2, 3], [1, 4, 9])\n"
        "plt.title('squares')\n"
        "plt.show()\n"
    )
    out = messages(RunCodeTool, {"compiler": "python-3.14", "code": code}, creds=creds())
    assert out.variables["exit_code"] == 0, out.text
    pngs = [blob for blob in out.blobs if blob.meta["mime_type"] == "image/png"]
    assert pngs, out.text
    assert pngs[0].message.blob.startswith(b"\x89PNG")
    assert pngs[0].meta["filename"].endswith(".png")
    assert all("content_base64" not in entry for entry in out.json[0]["files"])


def test_run_tests_accepted_with_a_hidden_test():
    code = "a, b = map(int, input().split())\nprint(a + b)\n"
    tests = '[{"input": "2 3", "expected_output": "5"}, {"input": "10 -4", "expected_output": "6", "hidden": true}]'
    out = messages(RunTestsTool, {"compiler": "python-3.14", "code": code, "tests": tests}, creds=creds())
    result = out.json[0]
    assert result["verdict"] == "accepted", out.text
    assert result["score"] == 100
    assert (result["passed"], result["total"]) == (2, 2)
    assert result["tests"][0]["output"] == "5\n"
    assert result["tests"][1] == {"verdict": "accepted", "hidden": True}
    assert "receipt" not in result
    assert result["submission"].startswith("sub_")
    assert out.variables["verdict"] == "accepted"


def test_run_tests_wrong_answer_scores_the_share_passed():
    code = "print(int(input()) * 2)\n"
    tests = [{"input": "2", "expected_output": "4"}, {"input": "3", "expected_output": "9"}]
    out = messages(RunTestsTool, {"compiler": "python-3.14", "code": code, "tests": str(tests), "checker": "tokens"},
                   creds=creds())
    result = out.json[0]
    assert result["verdict"] == "wrong_answer"
    assert result["score"] == 50
    assert [t["verdict"] for t in result["tests"]] == ["accepted", "wrong_answer"]
    assert out.text.startswith("Verdict: wrong_answer. Score 50 (1 of 2 tests passed).")


def test_unknown_compiler_is_a_clear_error():
    with pytest.raises(OnlineCompilerError, match="HTTP 400\\): Unsupported or missing compiler"):
        messages(RunCodeTool, {"compiler": "cobol-1959", "code": "x"}, creds=creds())


def test_compiler_options_are_all_live():
    out = messages(ListCompilersTool, {}, creds={})
    live = {compiler["id"] for compiler in out.json[0]["compilers"]}
    tool = yaml.safe_load((ROOT / "tools" / "run_code.yaml").read_text(encoding="utf-8"))
    options = {option["value"] for option in tool["parameters"][0]["options"]}
    assert options == live, f"missing live: {options - live}, not offered: {live - options}"
