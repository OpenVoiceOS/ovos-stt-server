"""Ensure version.py executes and exposes __version__."""
from ovos_stt_http_server import version


def test_version_string():
    assert isinstance(version.__version__, str)
    assert version.__version__.startswith(f"{version.VERSION_MAJOR}.{version.VERSION_MINOR}.{version.VERSION_BUILD}")
