# Examples

Runnable scripts that drive a running `ovos-stt-http-server`. Each vendor script
points that vendor's **own client** at the matching compat router via a base-URL
/ endpoint override — no request rewriting — which is exactly what a DNS
redirect to the server would achieve.

## Run a server first

```bash
pip install ovos-stt-http-server ovos-stt-plugin-fasterwhisper
ovos-stt-server --engine ovos-stt-plugin-fasterwhisper --port 8080
```

All scripts target `http://localhost:8080` (edit `OVOS_HOST` to change it).

## Scripts

| Script | Drives | Prefix | Install |
|--------|--------|--------|---------|
| `native_example.py` | native `/stt`, `/status` | — | — (standard library) |
| `openai_whisper_example.py` | official `openai` | `/v1` | `pip install openai` |
| `deepgram_example.py` | official `deepgram-sdk` | `/deepgram` | `pip install deepgram-sdk` |
| `assemblyai_example.py` | official `assemblyai` | `/assemblyai` | `pip install assemblyai` |
| `azure_stt_example.py` | HTTP (`requests`) | `/azure-stt` | `pip install requests` |
| `aws_transcribe_example.py` | official `boto3` | `/aws` | `pip install boto3` |
| `ibm_watson_example.py` | official `ibm-watson` | `/watson/speech-to-text` | `pip install ibm-watson` |
| `wit_ai_example.py` | official `wit` | `/wit` | `pip install wit` |
| `chromium_example.py` | `ovos-stt-plugin-chromium` | `/speech-api` | `pip install ovos-stt-plugin-chromium SpeechRecognition` |
| `whisper_cpp_example.py` | HTTP (`requests`) | `/inference` | `pip install requests` |
| `speechmatics_example.py` | official `speechmatics-batch` | `/speechmatics` | `pip install speechmatics-batch` |
| `vosk_grpc_example.py` | gRPC stubs | `--vosk-grpc-port` | `pip install grpcio` (separate process) |
| `vosk_mqtt_example.py` | `paho-mqtt` | `--vosk-mqtt-broker` | `pip install paho-mqtt` (separate process) |

`native_example.py` reads a mono 16-bit WAV and posts its raw PCM frames:

```bash
python examples/native_example.py path/to/clip.wav en
python examples/native_example.py status
```

The `vosk_grpc_example.py` and `vosk_mqtt_example.py` scripts target the
gRPC/MQTT vosk surfaces, which run as separate processes and are not mounted in
the default HTTP app — see [docs/api-compatibility.md](../docs/api-compatibility.md).
