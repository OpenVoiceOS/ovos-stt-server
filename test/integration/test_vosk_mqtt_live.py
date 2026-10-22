"""Live test: drive the Vosk-MQTT bridge against an embedded amqtt broker.

Spins up a Python `amqtt` broker on a free port, starts our `VoskMQTTBridge`
pointed at it, then opens a second paho client that simulates a real
vosk-server MQTT client: publishes audio chunks, sends /stop, listens for
the /finalTranscribe message.
"""
import asyncio
import json
import socket
import threading
import time

import pytest

from test.integration.conftest import FakeSTTEngine


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def broker():
    import amqtt
    import paho.mqtt.client
    from amqtt.broker import Broker

    port = _free_port()
    cfg = {
        "listeners": {
            "default": {
                "type": "tcp",
                "bind": f"127.0.0.1:{port}",
                "max_connections": 100,
            },
        },
        "auth": {"allow-anonymous": True},
    }
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    broker_obj = Broker(cfg, loop=loop)
    loop.run_until_complete(broker_obj.start())
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    # Give the broker a beat to fully accept connections
    time.sleep(0.3)
    try:
        yield port
    finally:
        async def _stop():
            await broker_obj.shutdown()
        try:
            asyncio.run_coroutine_threadsafe(_stop(), loop).result(timeout=3)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=3)
        loop.close()


def test_voice_then_stop_publishes_transcript(broker):
    from ovos_stt_http_server.vosk_mqtt_server import VoskMQTTBridge
    import paho.mqtt.client as mqtt

    bridge = VoskMQTTBridge(
        FakeSTTEngine(),
        pid="livetest",
        broker_host="127.0.0.1",
        broker_port=broker,
    )
    bridge.start()
    # Allow the bridge's subscribe to land
    time.sleep(0.3)

    received: list = []
    received_evt = threading.Event()

    if hasattr(mqtt, "CallbackAPIVersion"):
        peer = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    else:
        peer = mqtt.Client()

    def _on_connect(*_a, **_kw):
        peer.subscribe("livetest/finalTranscribe")

    def _on_message(_client, _userdata, msg):
        received.append(msg.payload.decode("utf-8"))
        received_evt.set()

    peer.on_connect = _on_connect
    peer.on_message = _on_message
    peer.connect("127.0.0.1", broker)
    peer.loop_start()
    try:
        time.sleep(0.3)
        peer.publish("livetest/stream/voice", b"\x00\x00" * 1600).wait_for_publish(2)
        peer.publish("livetest/stop", b"").wait_for_publish(2)
        assert received_evt.wait(timeout=5), "no /finalTranscribe published"
    finally:
        peer.loop_stop()
        peer.disconnect()
        bridge.stop()

    payload = json.loads(received[0])
    assert payload == {"text": "hello world"}
