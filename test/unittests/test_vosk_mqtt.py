"""Unit tests for VoskMQTTBridge.

All tests call message/connect handlers directly with fake MQTT objects —
no live broker required.
"""
import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeModel:
    """Minimal STT model stub that always returns 'hello world'."""

    def process_audio(self, audio, lang="en") -> str:
        """Return a fixed transcript regardless of input."""
        return "hello world"


def _make_msg(topic: str, payload: bytes) -> SimpleNamespace:
    """Build a minimal paho-style message object."""
    return SimpleNamespace(topic=topic, payload=payload)


def _make_bridge(pid="test", **kwargs):
    """Return a VoskMQTTBridge with a patched paho client (no real socket)."""
    import paho.mqtt.client as _mqtt

    with patch("paho.mqtt.client.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        from ovos_stt_http_server.vosk_mqtt_server import VoskMQTTBridge

        bridge = VoskMQTTBridge(FakeModel(), pid=pid, **kwargs)
        # Replace the real client with our mock so later assertions work.
        bridge._client = mock_client
        return bridge, mock_client


# ---------------------------------------------------------------------------
# Tests: constructor
# ---------------------------------------------------------------------------

class TestVoskMQTTBridgeInit:
    """VoskMQTTBridge initialises with correct defaults."""

    def test_defaults(self):
        """Constructor stores pid, sample_rate, and language defaults."""
        bridge, _ = _make_bridge()
        assert bridge._pid == "test"
        assert bridge._sample_rate == 16000
        assert bridge._language == "en"
        assert isinstance(bridge._buffer, bytearray)
        assert bridge._loop_thread is None

    def test_custom_language_and_rate(self):
        """Custom language and sample_rate are stored."""
        bridge, _ = _make_bridge(language="pt", sample_rate=8000)
        assert bridge._language == "pt"
        assert bridge._sample_rate == 8000

    def test_username_password_forwarded(self):
        """username/password are passed to paho's username_pw_set."""
        bridge, mock_client = _make_bridge(username="user", password="pass")
        mock_client.username_pw_set.assert_called_once_with("user", "pass")

    def test_no_credentials_no_call(self):
        """username_pw_set is not called when no credentials are given."""
        bridge, mock_client = _make_bridge()
        mock_client.username_pw_set.assert_not_called()

    def test_paho_v1_fallback(self):
        """Constructor uses the v1 Client() signature when CallbackAPIVersion is absent."""
        import paho.mqtt.client as _mqtt
        with patch("paho.mqtt.client.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client
            # Hide the v2 attribute to simulate paho v1
            with patch.object(_mqtt, "CallbackAPIVersion", new=None, create=False):
                import importlib
                import ovos_stt_http_server.vosk_mqtt_server as _mod
                # Patch hasattr result by temporarily removing the attribute
                original = getattr(_mqtt, "CallbackAPIVersion", _sentinel := object())
                try:
                    delattr(_mqtt, "CallbackAPIVersion")
                except AttributeError:
                    pass
                try:
                    from ovos_stt_http_server.vosk_mqtt_server import VoskMQTTBridge
                    bridge = VoskMQTTBridge(FakeModel(), pid="v1test")
                    bridge._client = mock_client
                    # v1 path: Client called with only client_id
                    MockClient.assert_called_with(client_id="v1test")
                finally:
                    if original is not _sentinel:
                        _mqtt.CallbackAPIVersion = original


# ---------------------------------------------------------------------------
# Tests: _on_connect
# ---------------------------------------------------------------------------

class TestOnConnect:
    """_on_connect subscribes to the three vosk-mqtt protocol topics."""

    def test_subscribes_three_topics(self):
        """All three topic suffixes are subscribed on connect."""
        bridge, _ = _make_bridge(pid="sess1")
        fake_client = MagicMock()
        bridge._on_connect(fake_client, None, None, 0)
        calls = [c.args[0] for c in fake_client.subscribe.call_args_list]
        assert "sess1/lang" in calls
        assert "sess1/stream/voice" in calls
        assert "sess1/stop" in calls

    def test_uses_correct_pid_prefix(self):
        """Topic prefix matches the pid given at construction."""
        bridge, _ = _make_bridge(pid="mydevice")
        fake_client = MagicMock()
        bridge._on_connect(fake_client, None, {}, 0)
        for call in fake_client.subscribe.call_args_list:
            assert call.args[0].startswith("mydevice/")


# ---------------------------------------------------------------------------
# Tests: _on_message — /lang
# ---------------------------------------------------------------------------

class TestOnMessageLang:
    """Messages on {pid}/lang switch the recognition language."""

    def test_valid_utf8_lang(self):
        """A valid UTF-8 payload updates self._language."""
        bridge, mock_client = _make_bridge(pid="p")
        bridge._on_message(mock_client, None, _make_msg("p/lang", b"fr"))
        assert bridge._language == "fr"

    def test_invalid_utf8_logs_warning(self, caplog):
        """Invalid UTF-8 in /lang payload logs a warning and leaves language unchanged."""
        import logging
        bridge, mock_client = _make_bridge(pid="p", language="en")
        with caplog.at_level(logging.WARNING):
            bridge._on_message(mock_client, None, _make_msg("p/lang", b"\xff\xfe"))
        assert bridge._language == "en"
        assert "invalid utf-8" in caplog.text.lower()


# ---------------------------------------------------------------------------
# Tests: _on_message — /stream/voice
# ---------------------------------------------------------------------------

class TestOnMessageVoice:
    """Messages on {pid}/stream/voice accumulate audio chunks in the buffer."""

    def test_single_chunk_buffered(self):
        """A single audio chunk is appended to the buffer."""
        bridge, mock_client = _make_bridge(pid="p")
        bridge._on_message(mock_client, None, _make_msg("p/stream/voice", b"\x01\x02"))
        assert bridge._buffer == bytearray(b"\x01\x02")

    def test_multiple_chunks_concatenated(self):
        """Multiple consecutive chunks are concatenated in order."""
        bridge, mock_client = _make_bridge(pid="p")
        bridge._on_message(mock_client, None, _make_msg("p/stream/voice", b"AB"))
        bridge._on_message(mock_client, None, _make_msg("p/stream/voice", b"CD"))
        assert bridge._buffer == bytearray(b"ABCD")


# ---------------------------------------------------------------------------
# Tests: _on_message — /stop
# ---------------------------------------------------------------------------

class TestOnMessageStop:
    """Messages on {pid}/stop flush the buffer and publish the transcript."""

    def test_stop_with_audio_publishes_transcript(self):
        """After receiving audio chunks, /stop publishes the model's transcript."""
        bridge, mock_client = _make_bridge(pid="p")
        bridge._on_message(mock_client, None, _make_msg("p/stream/voice", b"\x00\x00" * 100))
        bridge._on_message(mock_client, None, _make_msg("p/stop", b""))
        mock_client.publish.assert_called_once()
        topic, payload = mock_client.publish.call_args.args
        assert topic == "p/finalTranscribe"
        assert json.loads(payload) == {"text": "hello world"}

    def test_stop_clears_buffer(self):
        """The audio buffer is empty after /stop is processed."""
        bridge, mock_client = _make_bridge(pid="p")
        bridge._on_message(mock_client, None, _make_msg("p/stream/voice", b"\x00" * 50))
        bridge._on_message(mock_client, None, _make_msg("p/stop", b""))
        assert bridge._buffer == bytearray()

    def test_stop_without_audio_publishes_empty_text(self):
        """A /stop with no prior audio publishes an empty transcript."""
        bridge, mock_client = _make_bridge(pid="p")
        bridge._on_message(mock_client, None, _make_msg("p/stop", b""))
        mock_client.publish.assert_called_once()
        _, payload = mock_client.publish.call_args.args
        assert json.loads(payload) == {"text": ""}

    def test_stop_uses_current_language(self):
        """STT is invoked with the language set by the last /lang message."""
        called_with = {}

        class RecordingModel:
            def process_audio(self, audio, lang="en"):
                called_with["lang"] = lang
                return "ok"

        bridge, _ = _make_bridge(pid="p")
        bridge._model = RecordingModel()
        bridge._on_message(bridge._client, None, _make_msg("p/lang", b"pt"))
        bridge._on_message(bridge._client, None, _make_msg("p/stream/voice", b"\x00" * 10))
        bridge._on_message(bridge._client, None, _make_msg("p/stop", b""))
        assert called_with.get("lang") == "pt"

    def test_model_returns_none_publishes_empty(self):
        """If process_audio returns None the published text is an empty string."""

        class NoneModel:
            def process_audio(self, audio, lang="en"):
                return None

        bridge, mock_client = _make_bridge(pid="p")
        bridge._model = NoneModel()
        bridge._on_message(mock_client, None, _make_msg("p/stream/voice", b"\x00" * 10))
        bridge._on_message(mock_client, None, _make_msg("p/stop", b""))
        _, payload = mock_client.publish.call_args.args
        assert json.loads(payload) == {"text": ""}


# ---------------------------------------------------------------------------
# Tests: unknown topic is silently ignored
# ---------------------------------------------------------------------------

class TestUnknownTopic:
    """Messages on unrecognised topics are silently dropped."""

    def test_unknown_topic_no_side_effect(self):
        """An unrecognised topic leaves buffer and language unchanged."""
        bridge, mock_client = _make_bridge(pid="p")
        bridge._on_message(mock_client, None, _make_msg("p/unknown", b"data"))
        assert bridge._buffer == bytearray()
        mock_client.publish.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: start / stop lifecycle (no real socket)
# ---------------------------------------------------------------------------

class TestStartStop:
    """start() and stop() exercise the paho lifecycle without a real broker."""

    def test_start_connects_and_spawns_thread(self):
        """start() calls connect and spawns the loop thread."""
        bridge, mock_client = _make_bridge(pid="p")
        mock_client.loop_forever = MagicMock()  # prevent real blocking
        bridge.start()
        mock_client.connect.assert_called_once()
        assert bridge._loop_thread is not None
        # Clean up
        bridge._loop_thread = None

    def test_stop_calls_disconnect(self):
        """stop() calls disconnect on the paho client."""
        bridge, mock_client = _make_bridge(pid="p")
        bridge.stop()
        mock_client.disconnect.assert_called_once()

    def test_stop_when_no_thread_is_safe(self):
        """stop() with no active loop thread does not raise."""
        bridge, mock_client = _make_bridge(pid="p")
        assert bridge._loop_thread is None
        bridge.stop()  # should not raise

    def test_stop_joins_thread(self):
        """stop() joins the loop thread and clears the reference."""
        bridge, mock_client = _make_bridge(pid="p")
        fake_thread = MagicMock()
        bridge._loop_thread = fake_thread
        bridge.stop()
        fake_thread.join.assert_called_once()
        assert bridge._loop_thread is None

    def test_stop_tolerates_disconnect_error(self):
        """stop() swallows exceptions from disconnect()."""
        bridge, mock_client = _make_bridge(pid="p")
        mock_client.disconnect.side_effect = RuntimeError("broker gone")
        bridge.stop()  # should not raise
