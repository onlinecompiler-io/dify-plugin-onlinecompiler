from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from _onlinecompiler import compilers_result, compilers_summary, list_compilers


class ListCompilersTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        """GET /api/compilers/, which needs no key: every compiler id with its name and installed packages."""
        result = compilers_result(list_compilers())
        yield self.create_text_message(compilers_summary(result))
        yield self.create_json_message(result)
