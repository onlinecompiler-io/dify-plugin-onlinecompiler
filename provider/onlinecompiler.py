from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from _onlinecompiler import OnlineCompilerError, api_key_of, check_key


class OnlineCompilerProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        """Check the key with GET /api/usage/, which needs a valid REST key and counts no run."""
        try:
            check_key(api_key_of(credentials))
        except OnlineCompilerError as exc:
            raise ToolProviderCredentialValidationError(str(exc)) from None
