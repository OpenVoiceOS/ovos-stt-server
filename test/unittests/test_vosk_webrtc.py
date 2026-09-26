"""Unit tests for the vosk-webrtc router.

aiortc is an optional dependency; when it is absent the router factory must
raise ImportError with a clear message and the server must still boot without
the WebRTC router mounted.
"""
import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


class TestVoskWebRTCWithoutAiortc(unittest.TestCase):
    """Router behaviour when aiortc / av are not installed."""

    def _import_fresh(self):
        """Import the router module with a clean sys.modules slate."""
        mod_name = "ovos_stt_http_server.routers.vosk_webrtc"
        # Remove cached copy so the import runs fresh under the patched env.
        sys.modules.pop(mod_name, None)
        return importlib.import_module(mod_name)

    def test_importerror_when_aiortc_missing(self):
        """make_vosk_webrtc_router must raise ImportError if aiortc is absent."""
        with patch.dict(sys.modules, {"aiortc": None, "av": None,
                                      "av.audio": None,
                                      "av.audio.resampler": None}):
            mod = self._import_fresh()
            with self.assertRaises(ImportError) as ctx:
                mod.make_vosk_webrtc_router(MagicMock())
            self.assertIn("webrtc", str(ctx.exception).lower())

    def test_importerror_message_mentions_extra(self):
        """The ImportError message must name the [webrtc] extra."""
        with patch.dict(sys.modules, {"aiortc": None, "av": None,
                                      "av.audio": None,
                                      "av.audio.resampler": None}):
            mod = self._import_fresh()
            try:
                mod.make_vosk_webrtc_router(MagicMock())
            except ImportError as exc:
                self.assertIn("[webrtc]", str(exc))

    def test_sdp_models_importable_without_aiortc(self):
        """SDPOffer and SDPAnswer are plain pydantic models — importable without aiortc."""
        with patch.dict(sys.modules, {"aiortc": None, "av": None,
                                      "av.audio": None,
                                      "av.audio.resampler": None}):
            mod = self._import_fresh()
            offer = mod.SDPOffer(sdp="v=0\r\n", type="offer")
            answer = mod.SDPAnswer(sdp="v=0\r\n", type="answer")
            self.assertEqual(offer.type, "offer")
            self.assertEqual(answer.type, "answer")

    def test_server_boots_without_webrtc_router(self):
        """The FastAPI app mounts successfully even when the WebRTC router is absent."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()

        # Simulate the guarded mount in __init__.py — skip when ImportError.
        with patch.dict(sys.modules, {"aiortc": None, "av": None,
                                      "av.audio": None,
                                      "av.audio.resampler": None}):
            sys.modules.pop("ovos_stt_http_server.routers.vosk_webrtc", None)
            from ovos_stt_http_server.routers import vosk_webrtc as wrtc_mod
            try:
                router = wrtc_mod.make_vosk_webrtc_router(MagicMock())
                app.include_router(router)
            except ImportError:
                pass  # expected — router is optional

        client = TestClient(app)
        # The /offer endpoint must NOT be present.
        resp = client.post("/vosk-webrtc/offer", json={"sdp": "v=0\r\n", "type": "offer"})
        self.assertEqual(resp.status_code, 404)

    def test_active_pcs_set_exists(self):
        """Module-level _active_pcs tracking set must be present."""
        with patch.dict(sys.modules, {"aiortc": None, "av": None,
                                      "av.audio": None,
                                      "av.audio.resampler": None}):
            mod = self._import_fresh()
            self.assertIsInstance(mod._active_pcs, set)


if __name__ == "__main__":
    unittest.main()
