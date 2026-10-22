# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for the UTCP manual endpoint."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ovos_stt_http_server.utcp import build_utcp_manual, make_utcp_router


# ---------------------------------------------------------------------------
# Unit tests for build_utcp_manual()
# ---------------------------------------------------------------------------

class TestBuildUtcpManual:
    BASE = "http://localhost:8080"

    def setup_method(self):
        self.manual = build_utcp_manual(None, self.BASE)

    def test_top_level_keys(self):
        assert "utcp_version" in self.manual
        assert "manual_version" in self.manual
        assert "tools" in self.manual

    def test_utcp_version_is_string(self):
        assert isinstance(self.manual["utcp_version"], str)
        assert self.manual["utcp_version"]

    def test_manual_version_is_string(self):
        assert isinstance(self.manual["manual_version"], str)

    def test_tools_is_list(self):
        assert isinstance(self.manual["tools"], list)

    def test_three_tools_registered(self):
        """Expect stt, lang_detect, status."""
        names = {t["name"] for t in self.manual["tools"]}
        assert names == {"stt", "lang_detect", "status"}

    def test_stt_tool_structure(self):
        stt = next(t for t in self.manual["tools"] if t["name"] == "stt")
        assert "description" in stt
        assert "inputs" in stt
        assert "outputs" in stt
        assert "tool_call_template" in stt

    def test_stt_tool_call_template_url(self):
        stt = next(t for t in self.manual["tools"] if t["name"] == "stt")
        assert stt["tool_call_template"]["url"] == f"{self.BASE}/stt/json"
        assert stt["tool_call_template"]["http_method"] == "POST"

    def test_lang_detect_tool_call_template_url(self):
        ld = next(t for t in self.manual["tools"] if t["name"] == "lang_detect")
        assert ld["tool_call_template"]["url"] == f"{self.BASE}/lang_detect"

    def test_status_tool_call_template_url(self):
        st = next(t for t in self.manual["tools"] if t["name"] == "status")
        assert st["tool_call_template"]["url"] == f"{self.BASE}/status"
        assert st["tool_call_template"]["http_method"] == "GET"

    def test_stt_inputs_has_body_field(self):
        stt = next(t for t in self.manual["tools"] if t["name"] == "stt")
        assert "body" in stt["inputs"]["properties"]
        assert "body" in stt["inputs"]["required"]

    def test_lang_detect_valid_langs_is_optional(self):
        """/lang_detect works without valid_langs."""
        ld = next(t for t in self.manual["tools"] if t["name"] == "lang_detect")
        assert "valid_langs" in ld["inputs"]["properties"]
        assert ld["inputs"]["required"] == ["body"]

    def test_trailing_slash_stripped(self):
        """base_url with trailing slash must produce clean URLs."""
        manual = build_utcp_manual(None, self.BASE + "/")
        stt = next(t for t in manual["tools"] if t["name"] == "stt")
        assert not stt["tool_call_template"]["url"].endswith("//stt")

    def test_all_tools_have_tags(self):
        for tool in self.manual["tools"]:
            assert isinstance(tool.get("tags"), list)
            assert len(tool["tags"]) > 0

    def test_all_tools_have_average_response_size(self):
        for tool in self.manual["tools"]:
            assert isinstance(tool.get("average_response_size"), int)
            assert tool["average_response_size"] > 0

    def test_manual_validates_against_utcp_1x(self):
        from utcp.data.utcp_manual import UtcpManualSerializer
        manual = UtcpManualSerializer().validate_dict(self.manual)
        assert [t.tool_call_template.call_template_type for t in manual.tools] == ["http"] * 3
        assert all(t.tool_call_template.auth is None for t in manual.tools)


# ---------------------------------------------------------------------------
# Integration test: GET /utcp via TestClient
# ---------------------------------------------------------------------------

class TestUtcpEndpoint:
    """Mount only the UTCP router on a bare FastAPI app and test the endpoint."""

    @pytest.fixture(autouse=True)
    def _client(self):
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(make_utcp_router(None))
        self.client = TestClient(app)

    def test_get_utcp_returns_200(self):
        resp = self.client.get("/utcp")
        assert resp.status_code == 200

    def test_get_utcp_content_type_json(self):
        resp = self.client.get("/utcp")
        assert "application/json" in resp.headers["content-type"]

    def test_get_utcp_body_has_tools(self):
        data = self.client.get("/utcp").json()
        assert "tools" in data
        assert len(data["tools"]) == 3

    def test_get_utcp_tool_names(self):
        data = self.client.get("/utcp").json()
        names = {t["name"] for t in data["tools"]}
        assert names == {"stt", "lang_detect", "status"}

    def test_get_utcp_base_url_inferred(self):
        """URLs in the manual must use the request base URL."""
        data = self.client.get("/utcp").json()
        stt = next(t for t in data["tools"] if t["name"] == "stt")
        # TestClient uses http://testserver by default
        assert "testserver" in stt["tool_call_template"]["url"]

    def test_get_utcp_version_fields_present(self):
        data = self.client.get("/utcp").json()
        assert "utcp_version" in data
        assert "manual_version" in data

    def test_get_utcp_no_proxy_header_support(self):
        """Document gap: X-Forwarded-Host/-Proto are NOT used.

        The endpoint derives base_url from Starlette's request.base_url, which
        does not honour X-Forwarded-* headers unless a TrustedHostMiddleware /
        ProxyHeadersMiddleware is configured.  When those headers are sent the
        returned URLs still reflect the direct-connection base URL.
        """
        data = self.client.get(
            "/utcp",
            headers={"X-Forwarded-Host": "proxy.example.com", "X-Forwarded-Proto": "https"},
        ).json()
        stt = next(t for t in data["tools"] if t["name"] == "stt")
        # Without proxy middleware the URL still references testserver, NOT the
        # forwarded host — this is a known limitation / future enhancement.
        url = stt["tool_call_template"]["url"]
        assert "proxy.example.com" not in url, (
            "X-Forwarded-Host is now honoured — remove this gap note and add a "
            "positive assertion instead."
        )


# ---------------------------------------------------------------------------
# Additional build_utcp_manual() structural tests
# ---------------------------------------------------------------------------

class TestBuildUtcpManualExtra:
    BASE = "http://myserver.example.com:9090"

    def setup_method(self):
        self.manual = build_utcp_manual(None, self.BASE)

    def test_non_standard_port_preserved_in_urls(self):
        """Port 9090 must appear in every tool URL."""
        for tool in self.manual["tools"]:
            url = tool["tool_call_template"]["url"]
            assert "9090" in url, f"Port missing from URL in tool {tool['name']!r}: {url}"

    def test_stt_body_carries_the_audio_and_format(self):
        """The whole stt request travels in the JSON body."""
        stt = next(t for t in self.manual["tools"] if t["name"] == "stt")
        body = stt["inputs"]["properties"]["body"]
        assert set(body["properties"]) == {"audio_b64", "lang", "sample_rate", "sample_width"}
        assert body["required"] == ["audio_b64"]

    def test_all_tools_have_http_call_template(self):
        for tool in self.manual["tools"]:
            assert tool["tool_call_template"]["call_template_type"] == "http"

    def test_outputs_match_response_types(self):
        """/stt/json, /lang_detect and /status answer JSON objects."""
        types = {t["name"]: t["outputs"]["type"] for t in self.manual["tools"]}
        assert types == {"stt": "object", "lang_detect": "object", "status": "object"}

    def test_lang_detect_outputs_has_lang_and_conf(self):
        ld = next(t for t in self.manual["tools"] if t["name"] == "lang_detect")
        props = ld["outputs"]["properties"]
        assert "lang" in props
        assert "conf" in props

    def test_status_outputs_has_status_field(self):
        st = next(t for t in self.manual["tools"] if t["name"] == "status")
        assert "status" in st["outputs"]["properties"]

    def test_stt_content_type_header(self):
        """The stt tool sends a JSON body."""
        stt = next(t for t in self.manual["tools"] if t["name"] == "stt")
        assert stt["tool_call_template"]["content_type"] == "application/json"
        assert stt["tool_call_template"]["body_field"] == "body"

    def test_lang_detect_content_type_header(self):
        ld = next(t for t in self.manual["tools"] if t["name"] == "lang_detect")
        assert ld["tool_call_template"]["content_type"] == "application/octet-stream"
        assert ld["tool_call_template"]["body_field"] == "body"

    def test_status_tool_no_required_inputs(self):
        st = next(t for t in self.manual["tools"] if t["name"] == "status")
        assert st["inputs"]["required"] == []


class TestDeprecatedModule:
    def test_routers_utcp_warns_and_serves_the_same_manual(self):
        import importlib
        import sys
        from ovos_stt_http_server.version import VERSION_MAJOR, VERSION_MINOR
        sys.modules.pop("ovos_stt_http_server.routers.utcp", None)
        with pytest.warns(DeprecationWarning, match=f"removed in {VERSION_MAJOR}.{VERSION_MINOR + 1}.0"):
            legacy = importlib.import_module("ovos_stt_http_server.routers.utcp")
        base = "http://localhost:8080"
        assert legacy.build_utcp_manual(base) == build_utcp_manual(None, base)
        app = FastAPI()
        app.include_router(legacy.make_utcp_router())
        assert TestClient(app).get("/utcp").json() == build_utcp_manual(None, "http://testserver")


class TestManualVersions:
    def test_versions(self):
        from ovos_stt_http_server.version import VERSION_MAJOR, VERSION_MINOR, VERSION_BUILD, VERSION_ALPHA
        manual = build_utcp_manual(None, "http://localhost:8080")
        expected = f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_BUILD}" + (f"a{VERSION_ALPHA}" if VERSION_ALPHA else "")
        assert (manual["utcp_version"], manual["manual_version"]) == ("1.0.0", expected)
