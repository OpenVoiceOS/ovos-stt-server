# Licensed under the Apache License, Version 2.0
"""vosk-server MQTT variant.

Mirrors `alphacep/vosk-server/mqtt/asr_server_mqtt.py`:

  Subscribes:
    {pid}/lang          → switch recognition language (payload is the lang)
    {pid}/stream/voice  → audio chunks (binary payload, 16-bit PCM)
    {pid}/stop          → finalise: publish accumulated transcript

  Publishes:
    {pid}/finalTranscribe  → JSON-shaped string ({"text": "..."})

`{pid}` is a per-session identifier (the upstream impl reads it from the
`PID` env var). We accept it as a constructor arg so multiple bridges can
share a broker.
"""
import json
import logging
import threading
from typing import Optional

from ovos_plugin_manager.utils.audio import AudioData


_LOG = logging.getLogger(__name__)


class VoskMQTTBridge:
    """Bridge between an MQTT broker and an OVOS STT model container.

    `start()` is non-blocking — it spawns paho's network loop on a daemon
    thread. `stop()` cleanly disconnects and joins the loop thread.
    """

    def __init__(
            self,
            model,
            pid: str,
            broker_host: str = "127.0.0.1",
            broker_port: int = 1883,
            username: Optional[str] = None,
            password: Optional[str] = None,
            sample_rate: int = 16000,
            language: str = "en",
    ) -> None:
        import paho.mqtt.client as mqtt  # local import — optional dep

        self._model = model
        self._pid = pid
        self._sample_rate = sample_rate
        self._language = language
        self._buffer = bytearray()
        self._buffer_lock = threading.Lock()
        self._loop_thread: Optional[threading.Thread] = None

        # paho-mqtt v2 changed the API — default to v2 callbacks where present.
        if hasattr(mqtt, "CallbackAPIVersion"):
            self._client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=pid,
            )
        else:  # paho-mqtt v1
            self._client = mqtt.Client(client_id=pid)

        if username is not None:
            self._client.username_pw_set(username, password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._broker_host = broker_host
        self._broker_port = broker_port

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """Subscribe to the three vosk-mqtt protocol topics on successful connection."""
        _LOG.info("MQTT bridge connected (rc=%s)", rc)
        for suffix in ("/lang", "/stream/voice", "/stop"):
            client.subscribe(self._pid + suffix)

    def _on_message(self, client, userdata, msg):
        """Route an incoming MQTT message to the appropriate handler.

        ``{pid}/lang``         — switch the active recognition language.
        ``{pid}/stream/voice`` — accumulate a raw PCM chunk into the buffer.
        ``{pid}/stop``         — flush the buffer, run STT, publish ``{pid}/finalTranscribe``.
        """
        topic = msg.topic
        if topic.endswith("/lang"):
            try:
                self._language = msg.payload.decode("utf-8")
            except UnicodeDecodeError:
                _LOG.warning("invalid utf-8 in /lang payload")
        elif topic.endswith("/stream/voice"):
            with self._buffer_lock:
                self._buffer.extend(msg.payload)
        elif topic.endswith("/stop"):
            with self._buffer_lock:
                audio_bytes = bytes(self._buffer)
                self._buffer.clear()
            if audio_bytes:
                audio = AudioData(audio_bytes, self._sample_rate, 2)
                transcript = self._model.process_audio(
                    audio, self._language) or ""
            else:
                transcript = ""
            client.publish(
                self._pid + "/finalTranscribe",
                json.dumps({"text": transcript}),
            )

    def start(self) -> None:
        """Connect and spawn paho's network loop on a daemon thread."""
        self._client.connect(self._broker_host, self._broker_port)
        self._loop_thread = threading.Thread(
            target=self._client.loop_forever, daemon=True, name="vosk-mqtt",
        )
        self._loop_thread.start()
        _LOG.info("Vosk-MQTT bridge started; PID=%s", self._pid)

    def stop(self) -> None:
        """Disconnect from the broker and join the network-loop thread."""
        try:
            self._client.disconnect()
        except Exception:
            pass
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=2.0)
            self._loop_thread = None
