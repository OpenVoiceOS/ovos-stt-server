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
#
import argparse

import uvicorn
from ovos_utils.log import LOG

from ovos_stt_http_server import start_stt_server


def main():
    """Entry point for the OVOS STT HTTP server CLI."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", help="stt plugin to be used", required=True)
    parser.add_argument("--lang-engine", help="audio language detection plugin to be used")
    parser.add_argument("--port", help="port number", default=8080)
    parser.add_argument("--host", help="host", default="0.0.0.0")
    parser.add_argument("--multi", help="Load a plugin instance per language (force lang support)",
                        action="store_true")
    parser.add_argument("--mcp", help="mount MCP server at /mcp (requires ovos-stt-http-server[mcp])",
                        action="store_true")
    args = parser.parse_args()

    server, engine = start_stt_server(args.engine, lang_engine=args.lang_engine,
                                      multi=bool(args.multi), enable_mcp=bool(args.mcp))
    LOG.info("Server Started")
    uvicorn.run(server, host=args.host, port=int(args.port))


if __name__ == '__main__':
    main()
