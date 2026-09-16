"""Shared fixtures for STT integration live tests."""
import io
import socket
import threading
import time
import wave
from typing import Optional, Tuple, Union, Set, List


class FakeSTTEngine:
    """Mock ModelContainer/MultiModelContainer surface used by all compat routers."""

    def process_audio(self, audio, lang: str = "auto") -> str:
        return "hello world"

    def detect_language(
        self,
        audio,
        valid_langs: Optional[Union[Set[str], List[str]]] = None,
    ) -> Tuple[str, float]:
        return ("en", 0.99)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def make_silent_wav(seconds: float = 0.1, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * int(seconds * sample_rate))
    return buf.getvalue()


def run_live_server(register):
    """Yield a base URL for a uvicorn server with `register(app, model)` applied."""
    import uvicorn
    from fastapi import FastAPI

    model = FakeSTTEngine()
    app = FastAPI()
    register(app, model)

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("uvicorn live server failed to start")

    base_url = f"http://127.0.0.1:{port}"
    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)
