"""The manifest, provider and tool YAML against the rules the Dify plugin CLI (dify-plugin-daemon) checks when it
packages a plugin, and the Marketplace checks of langgenius/dify-plugins. Sources of the rules:
pkg/entities/plugin_entities/{plugin_declaration,tool_declaration,config,basic_type}.go and
pkg/entities/manifest_entities/tags.go in dify-plugin-daemon, docs/marketplace-curation-policy.md in dify-plugins,
and toolkit/checks/{manifest,readme}.py in dify-marketplace-toolkit."""

import ast
import importlib.util
import re
from datetime import datetime
from pathlib import Path

import pytest
import yaml

import _onlinecompiler as oc

ROOT = Path(__file__).resolve().parents[1]

# Tags the CLI accepts (tags.go) that the Marketplace's controlled vocabulary also lists.
CLI_TAGS = {
    "search", "image", "videos", "weather", "finance", "design", "travel", "social", "news", "medical",
    "productivity", "education", "business", "entertainment", "utilities", "agent", "rag", "other", "trigger",
}
MARKETPLACE_TAGS = {
    "agent", "business", "design", "education", "entertainment", "finance", "image", "news", "other",
    "productivity", "rag", "search", "social", "travel", "utilities", "videos", "weather",
    "llm", "model_provider", "audio", "document", "devtools", "database", "security", "translation",
}
PARAMETER_TYPES = {
    "string", "number", "boolean", "select", "secret-input", "file", "files", "app-selector", "model-selector",
    "any", "dynamic-select", "checkbox", "date", "date-range",
}
PARAMETER_FORMS = {"schema", "form", "llm"}
CREDENTIAL_TYPES = {"secret-input", "text-input", "select", "boolean", "app-selector", "model-selector", "tools-selector"}
LOCALES = {"en_US", "zh_Hans", "ja_JP", "pt_BR"}
NAME_RE = re.compile(r"^[a-z0-9_-]{1,128}$")
AUTHOR_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
IDENTITY_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
VERSION_RE = re.compile(r"^\d{1,4}(\.\d{1,4}){2}(-\w{1,16})?$")
EM_DASH = chr(0x2014)  # never written in this repository, so spelled as a code point
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")


def load(path):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


MANIFEST = load("manifest.yaml")
PROVIDER = load(MANIFEST["plugins"]["tools"][0])
TOOLS = {Path(path).stem: load(path) for path in PROVIDER["tools"]}


def check_i18n(value, where, *, required=True):
    if value is None and not required:
        return
    assert isinstance(value, dict), f"{where} must be an i18n object"
    assert set(value) <= LOCALES, f"{where} has unknown locales {set(value) - LOCALES}"
    assert isinstance(value.get("en_US"), str) and value["en_US"], f"{where}.en_US is required"
    for locale, text in value.items():
        assert isinstance(text, str) and len(text) < 1024, f"{where}.{locale} must be text under 1024 characters"


class TestManifest:
    def test_required_fields(self):
        for field in ("version", "type", "author", "name", "label", "description", "icon", "resource", "plugins",
                      "meta", "created_at", "privacy", "repo", "contact"):
            assert MANIFEST.get(field), f"manifest.yaml needs {field}"
        assert MANIFEST["type"] == "plugin"
        assert VERSION_RE.match(str(MANIFEST["version"]))
        assert MANIFEST["version"] == oc.VERSION
        assert NAME_RE.match(MANIFEST["name"])
        assert AUTHOR_RE.match(MANIFEST["author"])
        assert "dify" not in MANIFEST["author"] and "langgenius" not in MANIFEST["author"]
        check_i18n(MANIFEST["label"], "label")
        check_i18n(MANIFEST["description"], "description")
        assert isinstance(MANIFEST["resource"]["memory"], int)
        assert isinstance(MANIFEST["created_at"], datetime) or datetime.fromisoformat(str(MANIFEST["created_at"]))
        assert MANIFEST["repo"].startswith("https://github.com/onlinecompiler-io/")
        assert EMAIL_RE.match(MANIFEST["contact"])
        assert MANIFEST["verified"] is False

    def test_meta(self):
        meta = MANIFEST["meta"]
        assert VERSION_RE.match(str(meta["version"]))
        assert set(meta["arch"]) <= {"amd64", "arm64"} and meta["arch"]
        assert meta["runner"] == {"language": "python", "version": "3.12", "entrypoint": "main"}
        assert (ROOT / "main.py").is_file()
        assert meta["minimum_dify_version"]

    def test_tags(self):
        tags = MANIFEST["tags"]
        assert 1 <= len(tags) <= 3
        assert set(tags) <= CLI_TAGS & MARKETPLACE_TAGS
        # A tool provider's tags are the SDK's ToolLabelEnum, which has no "agent".
        from dify_plugin.entities.tool import ToolLabelEnum

        provider_tags = PROVIDER["identity"]["tags"]
        assert provider_tags and set(provider_tags) <= {label.value for label in ToolLabelEnum} & CLI_TAGS

    def test_the_sdk_loads_the_plugin(self, monkeypatch):
        # What the plugin runtime does at start-up: read every YAML into the SDK's models and import each class.
        from dify_plugin import DifyPluginEnv
        from dify_plugin.core.plugin_registration import PluginRegistration

        monkeypatch.chdir(ROOT)
        registration = PluginRegistration(DifyPluginEnv())
        assert registration.configuration.name == MANIFEST["name"]
        assert registration.get_tool_provider_cls("onlinecompiler").__name__ == "OnlineCompilerProvider"
        classes = {name: registration.get_tool_cls("onlinecompiler", name).__name__ for name in TOOLS}
        assert classes == {"run_code": "RunCodeTool", "run_tests": "RunTestsTool", "list_compilers": "ListCompilersTool"}

    def test_icon_and_privacy_files(self):
        assert (ROOT / "_assets" / MANIFEST["icon"]).is_file()
        assert (ROOT / "_assets" / PROVIDER["identity"]["icon"]).is_file()
        privacy = (ROOT / MANIFEST["privacy"]).read_text(encoding="utf-8")
        assert "please fill in the privacy policy" not in privacy.lower()
        assert "https://onlinecompiler.io/privacy" in privacy

    def test_network_domains(self):
        assert MANIFEST["network"]["domains"] == ["api.onlinecompiler.io"]
        assert oc.API_BASE == "https://api.onlinecompiler.io"

    def test_requirements_pin_the_sdk(self):
        lines = [line.strip() for line in (ROOT / "requirements.txt").read_text().splitlines() if line.strip()]
        assert "dify-plugin==0.11.0" in lines
        assert all(not line.startswith(("git+", "http", "-e")) for line in lines)


class TestProvider:
    def test_identity(self):
        identity = PROVIDER["identity"]
        assert identity["author"] == MANIFEST["author"]
        assert IDENTITY_RE.match(identity["name"])
        check_i18n(identity["label"], "provider.label")
        check_i18n(identity["description"], "provider.description")

    def test_credentials(self):
        creds = PROVIDER["credentials_for_provider"]
        assert list(creds) == ["api_key"]
        key = creds["api_key"]
        assert key["type"] in CREDENTIAL_TYPES and key["type"] == "secret-input"
        assert key["required"] is True
        assert key["url"] == oc.KEYS_URL
        for field in ("label", "placeholder", "help"):
            check_i18n(key[field], f"api_key.{field}")

    def test_source_files_exist(self):
        assert (ROOT / PROVIDER["extra"]["python"]["source"]).is_file()
        for path in PROVIDER["tools"]:
            assert (ROOT / path).is_file()


class TestTools:
    @pytest.mark.parametrize("name", sorted(TOOLS))
    def test_schema(self, name):
        tool = TOOLS[name]
        assert tool["identity"]["name"] == name
        assert IDENTITY_RE.match(tool["identity"]["name"])
        assert tool["identity"]["author"] == MANIFEST["author"]
        check_i18n(tool["identity"]["label"], f"{name}.label")
        check_i18n(tool["description"]["human"], f"{name}.description.human")
        assert isinstance(tool["description"]["llm"], str) and tool["description"]["llm"].strip()
        for param in tool.get("parameters") or []:
            where = f"{name}.{param['name']}"
            assert 0 < len(param["name"]) < 1024
            assert param["type"] in PARAMETER_TYPES, where
            assert param["form"] in PARAMETER_FORMS, where
            assert param["form"] == "llm" and param["llm_description"].strip(), where
            check_i18n(param["label"], f"{where}.label")
            check_i18n(param["human_description"], f"{where}.human_description")
            if param["type"] == "select":
                values = [option["value"] for option in param["options"]]
                assert len(values) == len(set(values)), where
                for option in param["options"]:
                    check_i18n(option["label"], f"{where} option {option['value']}")
                if "default" in param:
                    assert param["default"] in values, where

    @pytest.mark.parametrize("name", sorted(TOOLS))
    def test_source_defines_a_tool(self, name):
        source = ROOT / TOOLS[name]["extra"]["python"]["source"]
        spec = importlib.util.spec_from_file_location(f"source_{name}", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from dify_plugin import Tool

        assert any(isinstance(v, type) and issubclass(v, Tool) and v is not Tool for v in vars(module).values())

    def test_parameter_names_match_the_api(self):
        params = {name: [p["name"] for p in tool.get("parameters") or []] for name, tool in TOOLS.items()}
        assert params == {
            "run_code": ["compiler", "code", "input", "time_limit"],
            "run_tests": ["compiler", "code", "tests", "checker", "time_limit"],
            "list_compilers": [],
        }

    def test_compiler_options(self):
        run_code = TOOLS["run_code"]["parameters"][0]
        run_tests = TOOLS["run_tests"]["parameters"][0]
        assert run_code == run_tests
        values = [option["value"] for option in run_code["options"]]
        assert values[0] == oc.DEFAULT_COMPILER == run_code["default"]
        assert len(values) == 48
        assert not [v for v in values if v.endswith("-tests")]

    def test_checker_options(self):
        checker = TOOLS["run_tests"]["parameters"][3]
        assert tuple(option["value"] for option in checker["options"]) == oc.CHECKERS
        assert checker["default"] == "trim"

    def test_output_schemas_match_the_variables(self):
        assert tuple(TOOLS["run_code"]["output_schema"]["properties"]) == oc.RUN_VARIABLES
        assert tuple(TOOLS["run_tests"]["output_schema"]["properties"]) == oc.TESTS_VARIABLES
        assert "output_schema" not in TOOLS["list_compilers"]


class TestPackageFiles:
    TEXT_SUFFIXES = {".py", ".yaml", ".md", ".txt", ".toml", ".svg", ""}

    def files(self):
        skip = {".git", ".venv", "__pycache__", ".pytest_cache"}
        return [p for p in ROOT.rglob("*") if p.is_file() and not skip & set(p.relative_to(ROOT).parts)]

    def test_python_runs_on_3_12(self):
        for path in self.files():
            if path.suffix == ".py":
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 12))

    def test_no_em_dash_anywhere(self):
        for path in self.files():
            if path.suffix in self.TEXT_SUFFIXES:
                assert EM_DASH not in path.read_text(encoding="utf-8"), path

    def test_difyignore_keeps_development_files_out(self):
        ignored = {line.strip() for line in (ROOT / ".difyignore").read_text().splitlines()}
        for pattern in ("tests/", "pyproject.toml", ".venv/", "__pycache__/", "*.difypkg", ".git/", ".env"):
            assert pattern in ignored

    def test_readme_has_what_the_marketplace_checks(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert MANIFEST["repo"] in readme
        assert not re.search("[\u3400-\u4dbf\u4e00-\u9fff]", re.sub(r"```.*?```", "", readme, flags=re.S))
        lowered = readme.lower()
        for keyword in ("setup", "usage", "api key", "connection"):
            assert keyword in lowered
