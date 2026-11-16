from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from _onlinecompiler import (
    RUN_VARIABLES,
    api_key_of,
    file_blobs,
    run_code,
    run_code_body,
    run_result,
    run_summary,
    variables,
)


class RunCodeTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        """POST /api/run-code-sync/: a short summary, the result as JSON, its fields as workflow variables, and
        each file the program wrote as a Dify file."""
        api_key = api_key_of(self.runtime.credentials)
        body = run_code_body(tool_parameters)
        api = run_code(api_key, body)
        result = run_result(api)
        yield self.create_text_message(run_summary(body["compiler"], result))
        yield self.create_json_message(result)
        for name, value in variables(result, RUN_VARIABLES):
            yield self.create_variable_message(name, value)
        for blob, meta in file_blobs(api.get("files")):
            yield self.create_blob_message(blob, meta=meta)
