"""Request building, error messages and result formatting in _onlinecompiler, with the HTTP layer faked."""

import base64
import json

import pytest
import requests
from conftest import FAKE_KEY

import _onlinecompiler as oc
from _onlinecompiler import OnlineCompilerError


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
CSV = b"x,y\n1,2\n"

RUN_RESULT = {
    "output": "Hello, World!\n",
    "error": "",
    "status": "success",
    "exit_code": 0,
    "signal": None,
    "truncated": False,
    "time": "0.0248",
    "total": "0.0330",
    "memory": "8192",
    "files": [],
    "files_truncated": False,
    "time_limit": 30,
    "memory_limit": 512,
}


# ----------------------------------------------------------------------------------------------------------------
# Credentials and parameters
# ----------------------------------------------------------------------------------------------------------------


class TestApiKey:
    def test_bare_key_is_kept(self):
        assert oc.api_key_of({"api_key": FAKE_KEY}) == FAKE_KEY

    def test_whitespace_and_bearer_prefix_are_removed(self):
        assert oc.api_key_of({"api_key": f"  Bearer {FAKE_KEY}\n"}) == FAKE_KEY
        assert oc.api_key_of({"api_key": f"bearer {FAKE_KEY}"}) == FAKE_KEY

    @pytest.mark.parametrize("creds", [None, {}, {"api_key": ""}, {"api_key": "   "}, {"api_key": None}])
    def test_missing_key_is_refused(self, creds):
        with pytest.raises(OnlineCompilerError, match="API key"):
            oc.api_key_of(creds)

    def test_headers_send_the_bare_key(self):
        headers = oc.headers(FAKE_KEY)
        assert headers["Authorization"] == FAKE_KEY
        assert "Bearer" not in headers["Authorization"]
        assert headers["User-Agent"] == f"onlinecompiler-dify/{oc.VERSION}"
        assert "Authorization" not in oc.headers(None)


class TestRunCodeBody:
    def test_minimal(self):
        assert oc.run_code_body({"code": "print(1)"}) == {"compiler": "python-3.14", "code": "print(1)", "input": ""}

    def test_all_fields(self):
        body = oc.run_code_body({"compiler": " gcc-15 ", "code": "int main(){}", "input": "1 2\n", "time_limit": 5})
        assert body == {"compiler": "gcc-15", "code": "int main(){}", "input": "1 2\n", "time_limit": 5}

    def test_none_values_from_dify_mean_defaults(self):
        body = oc.run_code_body({"compiler": None, "code": "x", "input": None, "time_limit": None})
        assert body == {"compiler": "python-3.14", "code": "x", "input": ""}

    @pytest.mark.parametrize(
        ("value", "sent"),
        [(2, 2), (2.0, 2), (2.5, 2.5), ("3", 3), ("0.5", 0.5), (30, 30), (0, None), ("", None), ("  ", None)],
    )
    def test_time_limit(self, value, sent):
        body = oc.run_code_body({"code": "x", "time_limit": value})
        assert body.get("time_limit") == sent
        if sent is None:
            assert "time_limit" not in body
        else:
            assert type(body["time_limit"]) is type(sent)

    @pytest.mark.parametrize("value", [-1, 31, 30.5, "abc", float("nan"), float("inf"), True, [5]])
    def test_bad_time_limit_is_refused(self, value):
        with pytest.raises(OnlineCompilerError, match="time_limit must be a number of seconds above 0 and at most 30"):
            oc.run_code_body({"code": "x", "time_limit": value})

    @pytest.mark.parametrize("code", [None, ""])
    def test_empty_code_is_refused(self, code):
        with pytest.raises(OnlineCompilerError, match="code is empty"):
            oc.run_code_body({"code": code})

    def test_non_text_input_becomes_text(self):
        assert oc.run_code_body({"code": "x", "input": 42})["input"] == "42"


class TestRunTestsBody:
    def test_json_tests(self):
        tests = '[{"input": "2 3", "expected_output": "5"}, {"expected_output": "0", "hidden": true}]'
        body = oc.run_tests_body({"compiler": "python-3.14", "code": "x", "tests": tests})
        assert body == {
            "compiler": "python-3.14",
            "code": "x",
            "tests": [
                {"input": "2 3", "expected_output": "5"},
                {"input": "", "expected_output": "0", "hidden": True},
            ],
            "scoring": "percent",
        }

    def test_python_repr_of_a_list_is_read(self):
        # What a Dify workflow sends when an array variable fills a string parameter.
        tests = str([{"input": "1", "expected_output": "1"}])
        assert "'" in tests
        assert oc.tests_of({"tests": tests}) == [{"input": "1", "expected_output": "1"}]

    def test_list_and_wrapped_list_are_read(self):
        tests = [{"input": "a", "expected_output": "b"}]
        assert oc.tests_of({"tests": tests}) == tests
        assert oc.tests_of({"tests": {"tests": tests}}) == tests
        assert oc.tests_of({"tests": json.dumps({"tests": tests})}) == tests

    def test_numbers_become_text(self):
        assert oc.tests_of({"tests": '[{"input": 4, "expected_output": 16.5}]'}) == [
            {"input": "4", "expected_output": "16.5"}
        ]

    def test_null_input_is_empty(self):
        assert oc.tests_of({"tests": '[{"input": null, "expected_output": "x"}]'}) == [
            {"input": "", "expected_output": "x"}
        ]

    def test_extra_keys_are_dropped(self):
        tests = '[{"input": "1", "expected_output": "1", "weight": 3, "args": ["a"]}]'
        assert oc.tests_of({"tests": tests}) == [{"input": "1", "expected_output": "1"}]

    @pytest.mark.parametrize(
        ("tests", "message"),
        [
            (None, "non-empty JSON list"),
            ("", "tests is empty"),
            ("   ", "tests is empty"),
            ("[]", "non-empty JSON list"),
            ("{not json", "tests must be a JSON list"),
            ("__import__('os')", "tests must be a JSON list"),
            ('{"input": "1"}', "non-empty JSON list"),
            ('["just text"]', r"tests\[0\] must be an object"),
            ('[{"input": "1"}]', r"tests\[0\] has no expected_output"),
            ('[{"input": ["a"], "expected_output": "1"}]', r"tests\[0\]\.input must be text"),
            ('[{"input": "1", "expected_output": true}]', r"tests\[0\]\.expected_output must be text"),
        ],
    )
    def test_bad_tests_are_refused(self, tests, message):
        with pytest.raises(OnlineCompilerError, match=message):
            oc.tests_of({"tests": tests})

    def test_checker_and_time_limit(self):
        body = oc.run_tests_body(
            {"code": "x", "tests": '[{"expected_output": "1"}]', "checker": " Float ", "time_limit": "1.5"}
        )
        assert body["checker"] == "float"
        assert body["time_limit"] == 1.5
        assert body["scoring"] == "percent"

    def test_empty_checker_is_left_out(self):
        body = oc.run_tests_body({"code": "x", "tests": '[{"expected_output": "1"}]', "checker": ""})
        assert "checker" not in body
        assert "time_limit" not in body

    def test_unknown_checker_is_refused(self):
        with pytest.raises(OnlineCompilerError, match="checker must be one of trim, exact, tokens"):
            oc.run_tests_body({"code": "x", "tests": '[{"expected_output": "1"}]', "checker": "fuzzy"})

    def test_checkers_match_the_api(self):
        assert oc.CHECKERS == ("trim", "exact", "tokens", "float", "rows", "table", "table_ordered")


# ----------------------------------------------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------------------------------------------


class TestCall:
    def test_run_code_request(self, http):
        http.answer(200, RUN_RESULT)
        body = oc.run_code_body({"code": "print(1)"})
        assert oc.run_code(FAKE_KEY, body) == RUN_RESULT
        call = http.last
        assert call.method == "POST"
        assert call.url == "https://api.onlinecompiler.io/api/run-code-sync/"
        assert call.json == body
        assert call.headers["Authorization"] == FAKE_KEY
        assert call.timeout == oc.RUN_TIMEOUT
        assert call.allow_redirects is False

    def test_run_tests_request(self, http):
        http.answer(200, {"verdict": "accepted"})
        body = oc.run_tests_body({"code": "x", "tests": '[{"expected_output": "1"}]'})
        oc.run_tests(FAKE_KEY, body)
        assert http.last.method == "POST"
        assert http.last.url == "https://api.onlinecompiler.io/api/run-tests/"
        assert http.last.json == body
        assert http.last.timeout == oc.TESTS_TIMEOUT

    def test_list_compilers_sends_no_key(self, http):
        http.answer(200, {"compilers": [], "retired": {}})
        oc.list_compilers()
        assert http.last.method == "GET"
        assert http.last.url == "https://api.onlinecompiler.io/api/compilers/"
        assert "Authorization" not in http.last.headers
        assert http.last.json is None

    def test_check_key_reads_usage(self, http):
        http.answer(200, {"month": "2026-11", "submissions": 1})
        oc.check_key(FAKE_KEY)
        assert http.last.method == "GET"
        assert http.last.url == "https://api.onlinecompiler.io/api/usage/"
        assert http.last.headers["Authorization"] == FAKE_KEY

    @pytest.mark.parametrize(
        ("status", "error", "expected"),
        [
            (400, "Unsupported or missing compiler", "refused the request (HTTP 400): Unsupported or missing compiler"),
            (401, "Unauthorized", "did not accept the API key (HTTP 401: Unauthorized)"),
            (403, "This key is not authorized for the REST API", "Use a key of type API (widget keys are refused)"),
            (404, "Invalid or inactive API key", "did not accept the API key (HTTP 404: Invalid or inactive API key)"),
            (413, "The request body is over 32 MB", "too large for OnlineCompiler.io (HTTP 413)"),
            (
                429,
                "Too many concurrent requests. Please try again shortly.",
                "refused the run for a limit (HTTP 429): Too many concurrent requests. Please try again shortly. "
                "Nothing ran and nothing was counted.",
            ),
            (429, "Monthly limit reached", "(HTTP 429): Monthly limit reached. Nothing ran"),
            (503, "Execution queue unavailable", "could not handle the request (HTTP 503): Execution queue unavailable."),
            (418, "teapot", "answered HTTP 418: teapot"),
        ],
    )
    def test_error_statuses(self, http, status, error, expected):
        http.answer(status, {"error": error})
        with pytest.raises(OnlineCompilerError) as caught:
            oc.run_code(FAKE_KEY, {"compiler": "python-3.14", "code": "x"})
        assert expected in str(caught.value)
        assert caught.value.status == status
        assert FAKE_KEY not in str(caught.value)

    def test_keys_page_is_linked_for_key_errors(self, http):
        for status in (401, 403, 404):
            http.answer(status, {"error": "no"})
            with pytest.raises(OnlineCompilerError, match="api.onlinecompiler.io/compilers/api-keys/"):
                oc.check_key(FAKE_KEY)

    def test_non_json_error_body(self, http):
        http.answer(502, None, text="<html>\n  <body>Bad   gateway</body>\n</html>")
        with pytest.raises(OnlineCompilerError, match=r"HTTP 502\): <html> <body>Bad gateway</body> </html>\."):
            oc.list_compilers()

    def test_long_error_is_cut(self, http):
        http.answer(400, {"error": "x" * 5000})
        with pytest.raises(OnlineCompilerError) as caught:
            oc.list_compilers()
        assert len(str(caught.value)) < 700

    def test_empty_error_body(self, http):
        http.answer(500, None, text="")
        with pytest.raises(OnlineCompilerError, match="no details"):
            oc.list_compilers()

    def test_timeout(self, http):
        http.fail(requests.ReadTimeout("read timed out"))
        with pytest.raises(OnlineCompilerError, match="did not answer in time"):
            oc.run_code(FAKE_KEY, {"code": "x"})

    def test_connection_error_hides_the_request(self, http):
        http.fail(requests.ConnectionError(f"failed with headers Authorization: {FAKE_KEY}"))
        with pytest.raises(OnlineCompilerError) as caught:
            oc.run_code(FAKE_KEY, {"code": "x"})
        assert "Could not reach https://api.onlinecompiler.io (ConnectionError)" in str(caught.value)
        assert FAKE_KEY not in str(caught.value)
        assert caught.value.__cause__ is None
        assert caught.value.__suppress_context__

    @pytest.mark.parametrize("body", [None, ["a list"], "text"])
    def test_success_that_is_not_a_json_object(self, http, body):
        http.answer(200, body, text="oops" if body is None else None)
        with pytest.raises(OnlineCompilerError, match="not a JSON object"):
            oc.list_compilers()


# ----------------------------------------------------------------------------------------------------------------
# Results
# ----------------------------------------------------------------------------------------------------------------


FILES = [
    {"name": "figure-1.png", "mime": "image/png", "size": len(PNG), "content_base64": b64(PNG), "url": None},
    {
        "name": "out.csv",
        "mime": "text/csv",
        "size": len(CSV),
        "content_base64": b64(CSV),
        "url": "https://api.onlinecompiler.io/api/files/7/",
    },
]


class TestRunResult:
    def test_fields_are_kept_and_file_bytes_left_out(self):
        result = oc.run_result({**RUN_RESULT, "files": FILES, "files_truncated": True})
        assert {k: v for k, v in result.items() if k != "files"} == {
            **{k: v for k, v in RUN_RESULT.items() if k != "files"},
            "files_truncated": True,
        }
        assert result["files"] == [
            {"name": "figure-1.png", "mime": "image/png", "size": len(PNG), "url": None},
            {
                "name": "out.csv",
                "mime": "text/csv",
                "size": len(CSV),
                "url": "https://api.onlinecompiler.io/api/files/7/",
                "text": "x,y\n1,2\n",
            },
        ]
        assert "content_base64" not in json.dumps(result)

    def test_missing_files_become_an_empty_list(self):
        result = oc.run_result({k: v for k, v in RUN_RESULT.items() if k != "files"})
        assert result["files"] == []

    def test_text_of_a_file_is_capped(self):
        big = b"a" * (oc.MAX_FILE_TEXT + 10)
        entries = oc.file_entries([{"name": "big.txt", "mime": "text/plain", "size": len(big), "content_base64": b64(big)}])
        assert len(entries[0]["text"]) == oc.MAX_FILE_TEXT

    def test_undecodable_files_have_no_text(self):
        entries = oc.file_entries(
            [
                {"name": "a.txt", "mime": "text/plain", "content_base64": "%%%"},
                {"name": "b.txt", "mime": "text/plain", "content_base64": b64(b"\xff\xfe")},
                "not a file",
            ]
        )
        assert [e["name"] for e in entries] == ["a.txt", "b.txt"]
        assert all("text" not in e for e in entries)

    def test_blobs(self):
        blobs = oc.file_blobs(FILES + [{"name": "bad.png", "mime": "image/png", "content_base64": "%%%"}, None])
        assert blobs == [
            (PNG, {"mime_type": "image/png", "filename": "figure-1.png"}),
            (CSV, {"mime_type": "text/csv", "filename": "out.csv"}),
        ]

    def test_blob_defaults(self):
        assert oc.file_blobs([{"content_base64": b64(b"x")}]) == [
            (b"x", {"mime_type": "application/octet-stream", "filename": "file"})
        ]
        assert oc.file_blobs(None) == []

    def test_variables(self):
        values = dict(oc.variables({**RUN_RESULT, "error": None}, oc.RUN_VARIABLES))
        assert values == {
            "output": "Hello, World!\n",
            "error": "",
            "status": "success",
            "exit_code": 0,
            "time": "0.0248",
            "memory": "8192",
            "truncated": False,
        }


class TestRunSummary:
    def test_success(self):
        summary = oc.run_summary("python-3.14", oc.run_result(RUN_RESULT))
        assert summary == (
            "Ran python-3.14: success, exit code 0, time 0.0248 s, memory 8192 KB.\nOutput:\nHello, World!"
        )

    def test_time_limit_with_errors_files_and_truncation(self):
        result = oc.run_result(
            {
                **RUN_RESULT,
                "status": "error",
                "exit_code": 124,
                "output": "",
                "error": "Killed\n",
                "truncated": True,
                "files": FILES[:1],
                "files_truncated": True,
            }
        )
        summary = oc.run_summary("gcc-15", result)
        assert summary.splitlines()[0] == (
            "Ran gcc-15: error, exit code 124 (time limit exceeded), time 0.0248 s, memory 8192 KB."
        )
        assert "Errors:\nKilled" in summary
        assert "Output:" not in summary
        assert "went over the 64 KB cap" in summary
        assert f"Files: figure-1.png (image/png, {len(PNG)} bytes)" in summary
        assert "Some output files were left out" in summary

    def test_long_output_is_previewed(self):
        result = oc.run_result({**RUN_RESULT, "output": "x" * 1200})
        summary = oc.run_summary("python-3.14", result)
        assert "x" * oc.PREVIEW_CHARS in summary
        assert "x" * (oc.PREVIEW_CHARS + 1) not in summary
        assert "[700 more characters in the JSON result]" in summary

    def test_silent_program(self):
        summary = oc.run_summary("python-3.14", oc.run_result({**RUN_RESULT, "output": ""}))
        assert summary.endswith("The program printed nothing.")

    @pytest.mark.parametrize("code", [137, 153, 71, -1])
    def test_exit_code_meanings(self, code):
        summary = oc.run_summary("python-3.14", oc.run_result({**RUN_RESULT, "exit_code": code}))
        assert f"exit code {code} ({oc.EXIT_CODES[code]})" in summary


TESTS_RESULT = {
    "verdict": "wrong_answer",
    "score": 66.67,
    "passed": 2,
    "total": 3,
    "time_limit": 2,
    "memory_limit": 512,
    "compile_error": None,
    "tests": [
        {
            "verdict": "accepted",
            "hidden": False,
            "time": "0.02",
            "memory": "8192",
            "exit_code": 0,
            "signal": None,
            "output": "5\n",
            "error": "",
            "truncated": False,
            "files": FILES[:1],
            "files_truncated": False,
        },
        {"verdict": "wrong_answer", "hidden": True},
        {"verdict": "accepted", "hidden": True, "output": "leak", "error": "leak"},
    ],
    "summary": "2 of 3 tests passed. A hidden test failed.",
    "submission": "sub_" + "a" * 24,
    "receipt": {"receipt": "rcpt_x", "signature": "sig"},
}


class TestTestsResult:
    def test_receipt_dropped_and_hidden_tests_verdict_only(self):
        result = oc.tests_result(TESTS_RESULT)
        assert "receipt" not in result
        assert result["submission"] == TESTS_RESULT["submission"]
        assert result["summary"] == TESTS_RESULT["summary"]
        assert result["tests"][1] == {"verdict": "wrong_answer", "hidden": True}
        assert result["tests"][2] == {"verdict": "accepted", "hidden": True}
        visible = result["tests"][0]
        assert visible["output"] == "5\n"
        assert visible["files"] == [{"name": "figure-1.png", "mime": "image/png", "size": len(PNG), "url": None}]
        assert "content_base64" not in json.dumps(result)
        assert "leak" not in json.dumps(result)

    def test_variables(self):
        values = dict(oc.variables(oc.tests_result(TESTS_RESULT), oc.TESTS_VARIABLES))
        assert values == {
            "verdict": "wrong_answer",
            "score": 66.67,
            "passed": 2,
            "total": 3,
            "summary": "2 of 3 tests passed. A hidden test failed.",
            "compile_error": "",
            "submission": "sub_" + "a" * 24,
        }

    def test_summary(self):
        summary = oc.tests_summary(oc.tests_result(TESTS_RESULT))
        assert summary == (
            "Verdict: wrong_answer. Score 66.67 (2 of 3 tests passed).\n2 of 3 tests passed. A hidden test failed."
        )

    def test_summary_with_compile_error_and_whole_score(self):
        result = {
            **TESTS_RESULT,
            "verdict": "compilation_error",
            "score": 0.0,
            "passed": 0,
            "compile_error": "main.c:1: error: expected ';'",
            "summary": "",
        }
        assert oc.tests_summary(result) == (
            "Verdict: compilation_error. Score 0 (0 of 3 tests passed).\nCompiler output:\nmain.c:1: error: expected ';'"
        )
        assert oc.tests_summary({**TESTS_RESULT, "score": 100})[:36] == "Verdict: wrong_answer. Score 100 (2 "


class TestCompilers:
    API = {
        "compilers": [
            {"id": "python-3.14", "name": "Python 3.14", "packages": [{"name": "numpy", "version": "2.5.4"}]},
            {"id": "gcc-15", "name": "C (gcc 15)"},
            {"id": "python-3.14-tests", "name": "Python 3.14 (tests)", "pack": {"version": "1.1"}},
        ],
        "retired": {"dotnet-csharp-9": "dotnet-csharp-10"},
    }

    def test_packs_are_left_out(self):
        result = oc.compilers_result(self.API)
        assert [c["id"] for c in result["compilers"]] == ["python-3.14", "gcc-15"]
        assert result["retired"] == {"dotnet-csharp-9": "dotnet-csharp-10"}

    def test_summary(self):
        assert oc.compilers_summary(oc.compilers_result(self.API)) == (
            "2 compilers. Pass the id as compiler to Run Code or Run Tests.\n"
            "python-3.14: Python 3.14 (packages: numpy 2.5.4)\n"
            "gcc-15: C (gcc 15)"
        )

    def test_odd_shapes(self):
        assert oc.compilers_result({}) == {"compilers": [], "retired": {}}
        assert oc.compilers_result({"compilers": "x", "retired": None}) == {"compilers": [], "retired": {}}
