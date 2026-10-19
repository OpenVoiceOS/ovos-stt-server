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
"""Deprecated location of :mod:`ovos_stt_http_server.utcp`."""
import warnings

from fastapi import APIRouter

from ovos_stt_http_server import utcp
from ovos_stt_http_server.version import VERSION_MAJOR, VERSION_MINOR

warnings.warn(
    "ovos_stt_http_server.routers.utcp is deprecated, use ovos_stt_http_server.utcp; "
    f"it will be removed in {VERSION_MAJOR}.{VERSION_MINOR + 1}.0",
    DeprecationWarning, stacklevel=2)


def build_utcp_manual(base_url: str) -> dict:
    return utcp.build_utcp_manual(None, base_url)


def make_utcp_router() -> APIRouter:
    return utcp.make_utcp_router(None)
