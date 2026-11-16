"""Calls to the OnlineCompiler.io REST API, and the results the Dify tools return.

Every tool goes through this module, so request bodies, error messages and result shapes are tested in one place
(tests/test_onlinecompiler.py). The API is described at https://onlinecompiler.io/docs and in
https://api.onlinecompiler.io/openapi.json.
"""

from __future__ import annotations

import ast
import base64
import binascii
import json
import math
from collections.abc import Mapping
from typing import Any

import requests

VERSION = "0.0.1"
API_BASE = "https://api.onlinecompiler.io"
KEYS_URL = "https://api.onlinecompiler.io/compilers/api-keys/"
USER_AGENT = f"onlinecompiler-dify/{VERSION}"

DEFAULT_COMPILER = "python-3.14"
CHECKERS = ("trim", "exact", "tokens", "float", "rows", "table", "table_ordered")
MAX_TIME_LIMIT = 30  # seconds: the sandbox timeout (GET /api/limits/, timeout_seconds)

# (connect, read) timeouts in seconds. A run takes at most 30 seconds plus its compile step; one run-tests request
# at most about 60 seconds.
RUN_TIMEOUT = (10, 90)
TESTS_TIMEOUT = (10, 150)
INFO_TIMEOUT = (10, 30)

TEXT_MIMES = frozenset({"text/plain", "text/csv", "application/json"})
MAX_FILE_TEXT = 64 * 1024  # characters of a returned text file put into the JSON result
PREVIEW_CHARS = 500  # characters of output or errors in a text summary
MAX_ERROR_CHARS = 500  # characters of an API error message passed on

# What an exit code means, from the RunResult schema of the API.
EXIT_CODES = {
    124: "time limit exceeded",
    137: "memory limit exceeded",
    153: "output limit exceeded",
    71: "too many processes",
    -1: "the run failed on OnlineCompiler.io's side",
}

# Fields a tool also sets as workflow variables (see output_schema in its YAML).
RUN_VARIABLES = ("output", "error", "status", "exit_code", "time", "memory", "truncated")
TESTS_VARIABLES = ("verdict", "score", "passed", "total", "summary", "compile_error", "submission")


class OnlineCompilerError(Exception):
    """A request that could not be made, or that the API refused. The message never holds the API key."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------------------------------------------
# Credentials and parameters
# --------------------------------------------------------------------------------------------------------------


def api_key_of(credentials: Mapping[str, Any] | None) -> str:
    """The API key from the provider credentials, sent bare as the API expects."""
    key = str((credentials or {}).get("api_key") or "").strip()
    # The API refuses a "Bearer " prefix, so a key pasted with one is cut back to the key.
    if key[:7].lower() == "bearer ":
        key = key[7:].strip()
    if not key:
        raise OnlineCompilerError(
            f"Add your OnlineCompiler.io API key to this plugin's credentials. Create a free key at {KEYS_URL}"
        )
    return key


def _text(value: Any) -> str:
    """A parameter as text: Dify sends None for an empty optional field, and a model may send a number."""
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def compiler_of(params: Mapping[str, Any]) -> str:
    return _text(params.get("compiler")).strip() or DEFAULT_COMPILER


def code_of(params: Mapping[str, Any]) -> str:
    code = _text(params.get("code"))
    if not code:
        raise OnlineCompilerError("code is empty: pass the program's source code.")
    return code


def time_limit_of(params: Mapping[str, Any]) -> int | float | None:
    """Seconds the program may run, or None for the default. An empty field or 0 means the default."""
    value = params.get("time_limit")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    message = f"time_limit must be a number of seconds above 0 and at most {MAX_TIME_LIMIT}, got {value!r}."
    if isinstance(value, bool):
        raise OnlineCompilerError(message)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise OnlineCompilerError(message) from None
    if number == 0:
        return None
    if not math.isfinite(number) or not 0 < number <= MAX_TIME_LIMIT:
        raise OnlineCompilerError(message)
    return int(number) if number.is_integer() else number


def checker_of(params: Mapping[str, Any]) -> str | None:
    checker = _text(params.get("checker")).strip().lower()
    if not checker:
        return None
    if checker not in CHECKERS:
        raise OnlineCompilerError(f"checker must be one of {', '.join(CHECKERS)}, got {checker!r}.")
    return checker


TESTS_EXAMPLE = '[{"input": "2 3", "expected_output": "5"}]'


def _test_text(value: Any, where: str) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    # A model often writes numbers where text is meant: {"input": 4, "expected_output": 16}.
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    raise OnlineCompilerError(f"{where} must be text, got {type(value).__name__}.")


def tests_of(params: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The tests parameter, a JSON list of {input, expected_output} objects, as the API's tests list."""
    raw = params.get("tests")
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise OnlineCompilerError(f"tests is empty: pass a JSON list such as {TESTS_EXAMPLE}.")
        try:
            raw = json.loads(text)
        except ValueError:
            try:
                # A workflow variable holding a list reaches a string parameter as Python's repr of it, with
                # single quotes. literal_eval reads literals only and runs nothing.
                raw = ast.literal_eval(text)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                raise OnlineCompilerError(f"tests must be a JSON list such as {TESTS_EXAMPLE}.") from None
    if isinstance(raw, Mapping) and isinstance(raw.get("tests"), list):
        raw = raw["tests"]
    if not isinstance(raw, list) or not raw:
        raise OnlineCompilerError(f"tests must be a non-empty JSON list such as {TESTS_EXAMPLE}.")
    tests = []
    for index, test in enumerate(raw):
        where = f"tests[{index}]"
        if not isinstance(test, Mapping):
            raise OnlineCompilerError(f"{where} must be an object with input and expected_output.")
        if "expected_output" not in test:
            raise OnlineCompilerError(f"{where} has no expected_output.")
        entry: dict[str, Any] = {
            "input": _test_text(test.get("input"), f"{where}.input"),
            "expected_output": _test_text(test.get("expected_output"), f"{where}.expected_output"),
        }
        if test.get("hidden") is not None:
            entry["hidden"] = test["hidden"]
        tests.append(entry)
    return tests


def run_code_body(params: Mapping[str, Any]) -> dict[str, Any]:
    """The JSON body of POST /api/run-code-sync/."""
    body: dict[str, Any] = {
        "compiler": compiler_of(params),
        "code": code_of(params),
        "input": _text(params.get("input")),
    }
    time_limit = time_limit_of(params)
    if time_limit is not None:
        body["time_limit"] = time_limit
    return body


def run_tests_body(params: Mapping[str, Any]) -> dict[str, Any]:
    """The JSON body of POST /api/run-tests/. Scoring is percent, so every test runs and the score is the share
    passed."""
    body: dict[str, Any] = {
        "compiler": compiler_of(params),
        "code": code_of(params),
        "tests": tests_of(params),
        "scoring": "percent",
    }
    checker = checker_of(params)
    if checker is not None:
        body["checker"] = checker
    time_limit = time_limit_of(params)
    if time_limit is not None:
        body["time_limit"] = time_limit
    return body


# --------------------------------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------------------------------


def headers(api_key: str | None) -> dict[str, str]:
    result = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if api_key:
        result["Authorization"] = api_key  # the bare key: the API takes no Bearer prefix
    return result


def _detail(response: requests.Response) -> str:
    """The API's {"error": "..."} text, or the start of a body that is not JSON, on one line."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("error"), str):
        text = body["error"]
    else:
        text = response.text or ""
    return " ".join(text.split())[:MAX_ERROR_CHARS] or "no details"


def _sentence(text: str) -> str:
    return text if text.endswith((".", "!", "?")) else text + "."


def error_message(status: int, detail: str) -> str:
    """What a refused request tells the user, by HTTP status."""
    if status in (401, 404):
        return (
            f"OnlineCompiler.io did not accept the API key (HTTP {status}: {detail}). Check the key in this "
            f"plugin's credentials, or create a new one at {KEYS_URL}"
        )
    if status == 403:
        return (
            f"OnlineCompiler.io refused the API key (HTTP 403: {detail}). Use a key of type API (widget keys "
            f"are refused), and if the key is limited to an IP address, allow your Dify server's. Keys: {KEYS_URL}"
        )
    if status == 400:
        return f"OnlineCompiler.io refused the request (HTTP 400): {detail}"
    if status == 413:
        return f"The request is too large for OnlineCompiler.io (HTTP 413): {detail}"
    if status == 429:
        return (
            f"OnlineCompiler.io refused the run for a limit (HTTP 429): {_sentence(detail)} Nothing ran and "
            "nothing was counted."
        )
    if status >= 500:
        return (
            f"OnlineCompiler.io could not handle the request (HTTP {status}): {_sentence(detail)} Try again "
            "shortly."
        )
    return f"OnlineCompiler.io answered HTTP {status}: {detail}"


def call(
    method: str,
    path: str,
    *,
    api_key: str | None = None,
    body: Mapping[str, Any] | None = None,
    timeout: tuple[float, float] = INFO_TIMEOUT,
) -> Any:
    """Send one request to the API and return its JSON, or raise OnlineCompilerError. Nothing is retried: a run
    sent twice would count twice."""
    try:
        response = requests.request(
            method, API_BASE + path, headers=headers(api_key), json=body, timeout=timeout, allow_redirects=False
        )
    except requests.Timeout:
        raise OnlineCompilerError("OnlineCompiler.io did not answer in time. Try again shortly.") from None
    except requests.RequestException as exc:
        # The type only: an exception's text can repeat the request, and the request holds the key.
        raise OnlineCompilerError(
            f"Could not reach {API_BASE} ({type(exc).__name__}). Check that your Dify server can make HTTPS "
            "requests to api.onlinecompiler.io."
        ) from None
    if response.status_code != 200:
        raise OnlineCompilerError(error_message(response.status_code, _detail(response)), response.status_code)
    try:
        answer = response.json()
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        raise OnlineCompilerError("OnlineCompiler.io sent a response that is not a JSON object. Try again shortly.")
    return answer


def run_code(api_key: str, body: Mapping[str, Any]) -> dict[str, Any]:
    answer = call("POST", "/api/run-code-sync/", api_key=api_key, body=body, timeout=RUN_TIMEOUT)
    return answer


def run_tests(api_key: str, body: Mapping[str, Any]) -> dict[str, Any]:
    answer = call("POST", "/api/run-tests/", api_key=api_key, body=body, timeout=TESTS_TIMEOUT)
    return answer


def list_compilers() -> dict[str, Any]:
    return call("GET", "/api/compilers/")  # needs no key


def check_key(api_key: str) -> dict[str, Any]:
    """GET /api/usage/: answers 200 for a working key and counts no run."""
    answer = call("GET", "/api/usage/", api_key=api_key)
    return answer


# --------------------------------------------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------------------------------------------


def _decoded(entry: Mapping[str, Any]) -> bytes | None:
    content = entry.get("content_base64")
    if not isinstance(content, str) or not content:
        return None
    try:
        return base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError):
        return None


def file_entries(files: Any) -> list[dict[str, Any]]:
    """Output files by name, type, size and url, without their bytes. A text file (CSV, JSON, plain text) also
    carries its text, so a model can read it."""
    entries = []
    for file in files if isinstance(files, list) else []:
        if not isinstance(file, Mapping):
            continue
        entry = {key: file.get(key) for key in ("name", "mime", "size", "url")}
        if file.get("mime") in TEXT_MIMES:
            data = _decoded(file)
            if data is not None:
                try:
                    entry["text"] = data.decode("utf-8")[:MAX_FILE_TEXT]
                except UnicodeDecodeError:
                    pass
        entries.append(entry)
    return entries


def file_blobs(files: Any) -> list[tuple[bytes, dict[str, str]]]:
    """Each output file's bytes and the meta Dify stores it with. Images (PNG, SVG) show as images in Dify."""
    blobs = []
    for file in files if isinstance(files, list) else []:
        if not isinstance(file, Mapping):
            continue
        data = _decoded(file)
        if data is None:
            continue
        meta = {
            "mime_type": str(file.get("mime") or "application/octet-stream"),
            "filename": str(file.get("name") or "file"),
        }
        blobs.append((data, meta))
    return blobs


def run_result(api: Mapping[str, Any]) -> dict[str, Any]:
    """A run-code-sync result as the tool returns it: every field, with output files listed instead of embedded."""
    result = {key: value for key, value in api.items() if key != "files"}
    result["files"] = file_entries(api.get("files"))
    return result


def _test_entry(test: Any) -> Any:
    if not isinstance(test, Mapping):
        return test
    if test.get("hidden"):
        # The API already sends only these two for a hidden test; keep it so even if that changes.
        return {"verdict": test.get("verdict"), "hidden": True}
    entry = {key: value for key, value in test.items() if key != "files"}
    if "files" in test:
        entry["files"] = file_entries(test.get("files"))
    return entry


def tests_result(api: Mapping[str, Any]) -> dict[str, Any]:
    """A run-tests result as the tool returns it: the verdicts, score and summary, without the signed receipt."""
    result = {key: value for key, value in api.items() if key not in ("receipt", "tests")}
    tests = api.get("tests")
    result["tests"] = [_test_entry(test) for test in tests] if isinstance(tests, list) else []
    return result


def compilers_result(api: Mapping[str, Any]) -> dict[str, Any]:
    """The compiler list, without the test packs: those serve test suites, which this plugin does not send."""
    compilers = api.get("compilers")
    listed = [c for c in compilers if isinstance(c, Mapping) and "pack" not in c] if isinstance(compilers, list) else []
    return {"compilers": listed, "retired": api.get("retired") or {}}


def variables(result: Mapping[str, Any], names: tuple[str, ...]) -> list[tuple[str, Any]]:
    """The workflow variables a tool sets. An absent or null value becomes "", so a variable always exists."""
    return [(name, "" if result.get(name) is None else result[name]) for name in names]


def _preview(text: str) -> str:
    if len(text) <= PREVIEW_CHARS:
        return text.rstrip("\n")
    return f"{text[:PREVIEW_CHARS]}\n[{len(text) - PREVIEW_CHARS} more characters in the JSON result]"


def run_summary(compiler: str, result: Mapping[str, Any]) -> str:
    """A few lines about a run: how it ended, its time and memory, and the start of its output and errors."""
    exit_code = result.get("exit_code")
    head = f"Ran {compiler}: {result.get('status')}, exit code {exit_code}"
    meaning = EXIT_CODES.get(exit_code) if isinstance(exit_code, int) else None
    if meaning:
        head += f" ({meaning})"
    head += f", time {result.get('time')} s, memory {result.get('memory')} KB."
    lines = [head]
    for label, key in (("Output", "output"), ("Errors", "error")):
        text = result.get(key)
        if isinstance(text, str) and text:
            lines.append(f"{label}:\n{_preview(text)}")
    if not result.get("output") and not result.get("error"):
        lines.append("The program printed nothing.")
    if result.get("truncated"):
        lines.append("Output or errors went over the 64 KB cap and were cut.")
    files = result.get("files") or []
    if files:
        listed = ", ".join(f"{f.get('name')} ({f.get('mime')}, {f.get('size')} bytes)" for f in files)
        lines.append(f"Files: {listed}")
    if result.get("files_truncated"):
        lines.append("Some output files were left out (too many, too large, or of a type that is not returned).")
    return "\n".join(lines)


def _number(value: Any) -> str:
    return f"{value:g}" if isinstance(value, int | float) and not isinstance(value, bool) else str(value)


def tests_summary(result: Mapping[str, Any]) -> str:
    """The overall verdict and score, the API's own summary, and any compiler output."""
    lines = [
        f"Verdict: {result.get('verdict')}. Score {_number(result.get('score'))} "
        f"({result.get('passed')} of {result.get('total')} tests passed)."
    ]
    if result.get("summary"):
        lines.append(str(result["summary"]))
    compile_error = result.get("compile_error")
    if isinstance(compile_error, str) and compile_error:
        lines.append(f"Compiler output:\n{_preview(compile_error)}")
    return "\n".join(lines)


def compilers_summary(result: Mapping[str, Any]) -> str:
    """One line per compiler: its id, its name and any packages installed with it."""
    compilers = result.get("compilers") or []
    lines = [f"{len(compilers)} compilers. Pass the id as compiler to Run Code or Run Tests."]
    for compiler in compilers:
        line = f"{compiler.get('id')}: {compiler.get('name')}"
        packages = compiler.get("packages")
        if isinstance(packages, list) and packages:
            names = ", ".join(
                f"{p.get('name')} {p.get('version')}".strip() if isinstance(p, Mapping) else str(p) for p in packages
            )
            line += f" (packages: {names})"
        lines.append(line)
    return "\n".join(lines)
