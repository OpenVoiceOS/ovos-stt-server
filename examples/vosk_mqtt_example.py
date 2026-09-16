"""Drive the Vosk-MQTT bridge against an external MQTT broker.

The official paho-mqtt SDK is the canonical client.

Prerequisites:
    pip install paho-mqtt
    # A reachable MQTT broker (e.g. mosquitto on localhost:1883)
    ovos-stt-server --engine <some-ovos-stt-plugin> --port 8080 \\
                    --vosk-mqtt-broker 127.0.0.1:1883 \\
                    --vosk-mqtt-pid demo

Usage:
    python examples/vosk_mqtt_example.py path/to/clip.wav
"""
import sys
import threading
import wave

import paho.mqtt.client as mqtt


BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
PID = "demo"


def main(audio_path: str) -> None:
    with wave.open(audio_path) as wf:
        pcm = wf.readframes(wf.getnframes())

    done = threading.Event()
    result_box: list = []

    if hasattr(mqtt, "CallbackAPIVersion"):
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    else:
        client = mqtt.Client()

    @client.connect_callback() if hasattr(client, "connect_callback") else lambda f: f
    def _on_connect(*_a, **_kw):
        client.subscribe(f"{PID}/finalTranscribe")

    def _on_message(_client, _userdata, msg):
        result_box.append(msg.payload.decode("utf-8"))
        done.set()

    client.on_connect = _on_connect
    client.on_message = _on_message
    client.connect(BROKER_HOST, BROKER_PORT)
    client.loop_start()

    try:
        # Stream audio + finalise
        client.publish(f"{PID}/stream/voice", pcm).wait_for_publish(5)
        client.publish(f"{PID}/stop", b"").wait_for_publish(5)

        if not done.wait(timeout=15):
            sys.exit("timed out waiting for transcript")
        print(result_box[0])
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <audio.wav>")
    main(sys.argv[1])
