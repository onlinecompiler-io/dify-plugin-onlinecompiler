from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from _onlinecompiler import (
    TESTS_VARIABLES,
    api_key_of,
    run_tests,
    run_tests_body,
    tests_result,
    tests_summary,
    variables,
)


class RunTestsTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        """POST /api/run-tests/: a short summary, the verdicts and score as JSON (a hidden test by its verdict only),
        and the overall fields as workflow variables."""
        api_key = api_key_of(self.runtime.credentials)
        body = run_tests_body(tool_parameters)
        result = tests_result(run_tests(api_key, body))
        yield self.create_text_message(tests_summary(result))
        yield self.create_json_message(result)
        for name, value in variables(result, TESTS_VARIABLES):
            yield self.create_variable_message(name, value)
