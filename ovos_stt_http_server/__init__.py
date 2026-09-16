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
from typing import List, Tuple, Optional, Set, Union
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from ovos_config import Configuration
from ovos_plugin_manager.audio_transformers import load_audio_transformer_plugin, AudioLanguageDetector
from ovos_plugin_manager.stt import load_stt_plugin
from ovos_plugin_manager.transformer_services import (AudioTransformersService,
                                                      UtteranceTransformersService)
from ovos_plugin_manager.utils.audio import AudioFile, AudioData
from ovos_utils.log import LOG
from starlette.requests import Request

LOG.set_level("ERROR")  # avoid server side logs


def _load_translator():
    """Load the configured OVOS translate plugin for /audio/translations.

    OpenAI's translations endpoint always returns English, so we run an extra
    translate step after ASR. Returns the translator, or ``None`` if no plugin
    is configured/available (the endpoint then returns the untranslated text).
    """
    try:
        from ovos_plugin_manager.language import OVOSLangTranslationFactory
        return OVOSLangTranslationFactory.create()
    except Exception as exc:
        LOG.debug(f"no translate plugin available for /audio/translations: {exc}")
        return None


class TransformerPipelines:
    """Transformer pipelines shared by the model containers.

    Loading is config-gated and opt-in via the mycroft.conf
    ``audio_transformers`` / ``utterance_transformers`` sections; with no
    config both chains are empty and audio/transcripts pass through
    untouched.
    """

    def init_transformers(self):
        self.audio_transformers = AudioTransformersService(
            config=Configuration().get("audio_transformers") or {})
        self.utterance_transformers = UtteranceTransformersService(
            config=Configuration().get("utterance_transformers") or {})

    def transform_audio(self, audio: AudioData) -> Tuple[AudioData, dict]:
        """Run the audio transformer chain before the STT stage.

        Returns the (possibly modified) audio and the chain's context —
        e.g. ``stt_lang`` when an AudioLanguageDetector is in the chain.
        """
        if not self.audio_transformers.plugins:
            return audio, {}
        chunk, context = self.audio_transformers.transform(audio.frame_data)
        audio = AudioData(chunk, audio.sample_rate, audio.sample_width)
        return audio, context

    def transform_utterance(self, utterance: str, lang: str) -> str:
        """Run the utterance transformer chain on a transcript."""
        if not utterance or not self.utterance_transformers.plugins:
            return utterance
        utterances, _ = self.utterance_transformers.transform(
            [utterance], {"lang": lang})
        return utterances[0] if utterances else utterance


class ModelContainer(TransformerPipelines):
    def __init__(self, plugin: str, lang_plugin: str = None, config: dict = None):
        self.init_transformers()
        if config is None:
            # match OVOSSTTFactory behaviour: pick up the plugin's section from
            # mycroft.conf so a mounted config file can select model/voice/etc.
            config = Configuration().get("stt", {}).get(plugin) or {}
        plugin = load_stt_plugin(plugin)
        self.lang_plugin = None
        if not plugin:
            raise ValueError(f"Failed to load STT: {plugin}")
        if lang_plugin:
            lang_plugin = load_audio_transformer_plugin(lang_plugin)
            if not lang_plugin:
                raise ValueError(f"Failed to load lang detection plugin: {lang_plugin}")
            assert issubclass(lang_plugin, AudioLanguageDetector)
            LOG.info(f"Loading Audio Language detector plugin: {lang_plugin}")
            self.lang_plugin = lang_plugin()
        LOG.info(f"Loading STT plugin: {plugin}")
        self.engine = plugin(config)
        if self.lang_plugin:
            self.engine.bind(self.lang_plugin)

    def detect_language(self, audio, valid_langs: Optional[Union[Set[str], List[str]]] = None) -> Tuple[str, float]:
        """Detect the spoken language.

        Prefers the dedicated lang plugin when one is bound, else the plugin's
        own detect_language. Raises NotImplementedError in a shape the caller
        can turn into HTTP 501 when neither path exists; a plugin that inherits
        the OPM stub without overriding it counts as not supported.
        """
        if self.lang_plugin is not None:
            return self.lang_plugin.detect(audio, valid_langs)
        if not hasattr(self.engine, "detect_language"):
            raise NotImplementedError(f"{type(self.engine).__name__} does not support audio language detection")
        # the OPM STT template stubs detect_language; an engine that did not
        # override it cannot detect anything, so accept the plugin's own
        # NotImplementedError wording as its answer rather than probing fakes
        try:
            return self.engine.detect_language(audio, valid_langs)
        except NotImplementedError:
            raise NotImplementedError(f"{type(self.engine).__name__} does not support audio language detection") from None

    def process_audio(self, audio: AudioData, lang: str = "auto"):
        audio, context = self.transform_audio(audio)
        if lang == "auto" and context.get("stt_lang"):
            lang = context["stt_lang"]
        utterance = self.engine.execute(audio, language=lang) or ""
        return self.transform_utterance(utterance, lang)


class MultiModelContainer(TransformerPipelines):
    """ loads 1 model per language """

    def __init__(self, plugin: str, lang_plugin: str = None, config: dict = None):
        # transformer chains are shared across the per-language engines
        self.init_transformers()
        if config is None:
            config = Configuration().get("stt", {}).get(plugin) or {}
        self.plugin_class = load_stt_plugin(plugin)
        self.lang_plugin = None
        if not self.plugin_class:
            raise ValueError(f"Failed to load STT: {plugin}")
        if lang_plugin:
            lang_plugin = load_audio_transformer_plugin(lang_plugin)
            if not lang_plugin:
                raise ValueError(f"Failed to load lang detection plugin: {lang_plugin}")
            assert issubclass(lang_plugin, AudioLanguageDetector)
            self.lang_plugin = lang_plugin()
        self.engines = {}
        self.config = config or {}

    def detect_language(self, audio, valid_langs: Optional[Union[Set[str], List[str]]] = None) -> Tuple[str, float]:
        if self.lang_plugin is None:
            raise NotImplementedError(f"{self.plugin_class.__name__} does not support audio language detection")
        return self.lang_plugin.detect(audio, valid_langs)

    def get_engine(self, lang: str):
        if lang not in self.engines:
            self.load_engine(lang)
        return self.engines[lang]

    def load_engine(self, lang: str, config=None):
        # might need to load multiple models per language
        config = config or self.config
        config["lang"] = lang
        self.engines[lang] = self.plugin_class(config=config)
        if self.lang_plugin:
            self.engines[lang].bind(self.lang_plugin)

    def unload_engine(self, lang: str):
        if lang in self.engines:
            self.engines.pop(lang)

    def process_audio(self, audio: AudioData, lang: str):
        """
        Transcribes the provided audio using the engine for the specified language.
        
        Parameters:
            audio (AudioData): Audio content to transcribe.
            lang (str): Language code identifying which engine to use.
        
        Returns:
            str: Transcribed text for the audio, or an empty string if no transcription is produced.
        """
        audio, context = self.transform_audio(audio)
        if lang == "auto" and context.get("stt_lang"):
            lang = context["stt_lang"]
        engine = self.get_engine(lang)
        utterance = engine.execute(audio, language=lang) or ""
        return self.transform_utterance(utterance, lang)


def create_app(stt_plugin: str, lang_plugin: str = None, multi: bool = False,
               enable_mcp: bool = False):
    """
    Create and configure a FastAPI app that exposes STT and language-detection endpoints.

    Initializes either a single-model or multi-model container using the provided plugins,
    and registers three endpoints:
    - GET /status: returns service and plugin metadata.
    - POST /stt: accepts raw audio bytes (query params: `lang`, `sample_rate`, `sample_width`),
      optionally performs language detection when `lang=auto`, and returns transcribed text.
    - POST /lang_detect: accepts raw audio bytes and returns detected language and confidence
      (supports `valid_langs` query param).

    Parameters:
        stt_plugin: Name or identifier of the STT plugin to load.
        lang_plugin: Name or identifier of an optional language-detection plugin.
        multi: If True, use a MultiModelContainer (one engine per language).
        enable_mcp: If True, mount the MCP server at /mcp (requires the `mcp` extra).

    Returns:
        tuple: (app, model) where `app` is the configured FastAPI application and `model` is
            the initialized ModelContainer or MultiModelContainer instance.
    """
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if multi:
        model = MultiModelContainer(stt_plugin, lang_plugin)
    else:
        model = ModelContainer(stt_plugin, lang_plugin)

    @app.get("/status")
    def stats(request: Request):
        return {"status": "ok",
                "plugin": stt_plugin,
                "lang_plugin": lang_plugin}

    @app.post("/stt", response_class=PlainTextResponse)
    async def get_stt(request: Request):
        """
        Handle an STT request: read audio from the request body, determine language if requested, and return the transcription.
        
        Parameters:
            request (Request): HTTP request whose body contains raw audio bytes. Query parameters:
                - lang: language code or "auto" (default from Configuration().get("lang", "auto")).
                - sample_rate: sample rate in Hz for the audio (default 16000).
                - sample_width: sample width in bytes (default 2).
        
        Returns:
            str: Transcribed text from the provided audio, or an empty string if no transcription is produced.
        """
        lang = str(request.query_params.get("lang", Configuration().get("lang", "auto"))).lower()
        sr = int(request.query_params.get("sample_rate", 16000))
        sw = int(request.query_params.get("sample_width", 2))
        audio_bytes = await request.body()
        audio = AudioData(audio_bytes, sr, sw)
        if lang == "auto":
            lang, prob = model.detect_language(audio_bytes)
        return model.process_audio(audio, lang)

    @app.post("/lang_detect")
    async def get_lang(request: Request):
        valid_param = request.query_params.get("valid_langs")
        valid = valid_param.split(",") if valid_param else None
        if valid and len(valid) == 1:
            return {"lang": valid[0], "conf": 1.0}
        audio_bytes = await request.body()
        try:
            lang, prob = model.detect_language(audio_bytes, valid_langs=valid)
        except NotImplementedError as exc:
            # the plugin cannot detect language at all; a 500 here reads as a
            # server fault, 501 names the limitation
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        return {"lang": lang, "conf": prob}

    from ovos_stt_http_server.routers.chromium import make_chromium_router
    from ovos_stt_http_server.routers.utcp import make_utcp_router
    from ovos_stt_http_server.routers.deepgram import make_deepgram_router
    app.include_router(make_chromium_router(model))
    app.include_router(make_utcp_router())
    # vosk-webrtc needs the optional aiortc dependency
    try:
        from ovos_stt_http_server.routers.vosk_webrtc import make_vosk_webrtc_router
        app.include_router(make_vosk_webrtc_router(model))
    except ImportError:
        LOG.debug("aiortc not installed; skipping vosk-webrtc router")
    from ovos_stt_http_server.routers.openai_whisper import make_openai_whisper_router
    app.include_router(make_openai_whisper_router(model, translator=_load_translator()))
    from ovos_stt_http_server.routers.whisper_cpp_server import make_whisper_cpp_server_router
    app.include_router(make_whisper_cpp_server_router(model))
    from ovos_stt_http_server.routers.speechmatics import make_speechmatics_router
    app.include_router(make_speechmatics_router(model))
    from ovos_stt_http_server.routers.google_stt import make_google_stt_router
    app.include_router(make_google_stt_router(model))
    from ovos_stt_http_server.routers.wit_ai import make_wit_ai_router
    app.include_router(make_wit_ai_router(model))
    from ovos_stt_http_server.routers.assemblyai import make_assemblyai_router
    app.include_router(make_assemblyai_router(model))
    from ovos_stt_http_server.routers.azure_stt import make_azure_stt_router
    app.include_router(make_azure_stt_router(model))
    from ovos_stt_http_server.routers.ibm_watson_stt import make_ibm_watson_stt_router
    app.include_router(make_ibm_watson_stt_router(model))
    from ovos_stt_http_server.routers.aws_transcribe import make_aws_transcribe_router
    app.include_router(make_aws_transcribe_router(model))
    app.include_router(make_deepgram_router(model))
    from ovos_stt_http_server.routers.vosk_server import make_vosk_server_router
    app.include_router(make_vosk_server_router(model))
    from ovos_stt_http_server.routers.kaldi_gstreamer import make_kaldi_gstreamer_router
    app.include_router(make_kaldi_gstreamer_router(model))
    from ovos_stt_http_server.routers.gladia import make_gladia_router
    app.include_router(make_gladia_router(model))
    from ovos_stt_http_server.routers.elevenlabs_scribe import make_elevenlabs_scribe_router
    app.include_router(make_elevenlabs_scribe_router(model))
    from ovos_stt_http_server.routers.groq import make_groq_router
    app.include_router(make_groq_router(model))

    # Mount MCP server only when explicitly requested via --mcp.
    if enable_mcp:
        try:
            from ovos_stt_http_server.mcp_server import mount_mcp_on_fastapi
            mount_mcp_on_fastapi(app, model)
        except ImportError:
            LOG.warning("MCP was requested (--mcp) but the optional dependency "
                        "is not installed; skipping MCP server. "
                        "Enable with: pip install 'ovos-stt-http-server[mcp]'")

    return app, model


def start_stt_server(engine: str,
                     lang_engine: str = None,
                     multi: bool = False,
                     enable_mcp: bool = False) -> tuple:
    """
    Initialize and return a configured FastAPI STT server and its model container.

    Parameters:
        engine: STT plugin name to load.
        lang_engine: Optional language-detection plugin name.
        multi: If True, load one engine per language via MultiModelContainer.
        enable_mcp: If True, mount the MCP server at /mcp (requires the `mcp` extra).

    Returns:
        tuple: (app, model) — the FastAPI application and the model container.
    """
    app, engine = create_app(engine, lang_engine, multi, enable_mcp)
    return app, engine