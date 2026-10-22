"""Live test: hit our /speechmatics router via raw multipart REST."""
import pytest
import requests

from test.integration.conftest import make_silent_wav, run_live_server


@pytest.fixture(scope="module")
def base_url():
    from ovos_stt_http_server.routers.speechmatics import make_speechmatics_router

    def register(app, model):
        app.include_router(make_speechmatics_router(model))

    yield from run_live_server(register)


def test_submit_job(base_url):
    wav = make_silent_wav()
    r = requests.post(
        f"{base_url}/speechmatics/v2/jobs",
        files={"data_file": ("clip.wav", wav, "audio/wav")},
        data={"config": '{"type": "transcription", "transcription_config": {"language": "en"}}'},
    )
    r.raise_for_status()
    j = r.json()
    assert "id" in j
    # Speechmatics v2 is async: submit returns the job id, then you poll the
    # job for status — GET /v2/jobs/{id} reports {"job": {"status": "done"}}.
    poll = requests.get(f"{base_url}/speechmatics/v2/jobs/{j['id']}")
    poll.raise_for_status()
    assert poll.json()["job"]["status"] == "done"


def test_get_transcript_flow(base_url):
    wav = make_silent_wav()
    submit = requests.post(
        f"{base_url}/speechmatics/v2/jobs",
        files={"data_file": ("clip.wav", wav, "audio/wav")},
        data={"config": '{"type": "transcription", "transcription_config": {"language": "en"}}'},
    )
    job_id = submit.json()["id"]
    r = requests.get(f"{base_url}/speechmatics/v2/jobs/{job_id}/transcript")
    r.raise_for_status()
    j = r.json()
    assert "results" in j


def test_unknown_job_returns_404(base_url):
    r = requests.get(f"{base_url}/speechmatics/v2/jobs/does-not-exist/transcript")
    assert r.status_code == 404
