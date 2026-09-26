# Changelog

## [0.27.6a1](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.27.6a1) (2026-09-26)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.27.5a2...0.27.6a1)

**Merged pull requests:**

- fix\(ci\): publish stable through the shared workflow, not setup.py [\#120](https://github.com/OpenVoiceOS/ovos-stt-server/pull/120) ([openvoiceos-bot](https://github.com/openvoiceos-bot))

## [0.27.5a2](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.27.5a2) (2026-09-26)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.27.5a1...0.27.5a2)

**Merged pull requests:**

- ci: replace the set-output command GitHub removed [\#117](https://github.com/OpenVoiceOS/ovos-stt-server/pull/117) ([openvoiceos-bot](https://github.com/openvoiceos-bot))

## [0.27.5a1](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.27.5a1) (2026-09-26)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.27.4a1...0.27.5a1)

**Merged pull requests:**

- fix\(openai\): answer with the language the engine transcribed in [\#116](https://github.com/OpenVoiceOS/ovos-stt-server/pull/116) ([openvoiceos-bot](https://github.com/openvoiceos-bot))

## [0.27.4a1](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.27.4a1) (2026-09-24)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.27.3a1...0.27.4a1)

**Merged pull requests:**

- fix: /stt hands lang=auto to process\_audio instead of detecting uncaught [\#114](https://github.com/OpenVoiceOS/ovos-stt-server/pull/114) ([openvoiceos-bot](https://github.com/openvoiceos-bot))

## [0.27.3a1](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.27.3a1) (2026-09-24)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.27.2a1...0.27.3a1)

**Merged pull requests:**

- fix: stop forwarding literal "auto" language to STT plugins [\#108](https://github.com/OpenVoiceOS/ovos-stt-server/pull/108) ([JarbasAl](https://github.com/JarbasAl))

## [0.27.2a1](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.27.2a1) (2026-09-24)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.27.1a1...0.27.2a1)

**Merged pull requests:**

- fix: actionlint deprecated-command finding keeping lint red on dev [\#111](https://github.com/OpenVoiceOS/ovos-stt-server/pull/111) ([openvoiceos-bot](https://github.com/openvoiceos-bot))

## [0.27.1a1](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.27.1a1) (2026-09-16)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.27.0a1...0.27.1a1)

**Merged pull requests:**

- fix: /lang\_detect answers 501 when the plugin cannot detect language [\#109](https://github.com/OpenVoiceOS/ovos-stt-server/pull/109) ([openvoiceos-bot](https://github.com/openvoiceos-bot))

## [0.27.0a1](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.27.0a1) (2026-09-01)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.26.0a1...0.27.0a1)

**Merged pull requests:**

- feat: Docker Compose proxy default and custom-container docs [\#76](https://github.com/OpenVoiceOS/ovos-stt-server/pull/76) ([JarbasAl](https://github.com/JarbasAl))

## [0.26.0a1](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.26.0a1) (2026-08-13)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.25.2a1...0.26.0a1)

**Merged pull requests:**

- feat: make MCP mounting opt-in via --mcp flag [\#103](https://github.com/OpenVoiceOS/ovos-stt-server/pull/103) ([JarbasAl](https://github.com/JarbasAl))

## [0.25.2a1](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.25.2a1) (2026-08-13)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.25.1a4...0.25.2a1)

**Merged pull requests:**

- fix: resolve plugin config from mycroft.conf when none is passed [\#97](https://github.com/OpenVoiceOS/ovos-stt-server/pull/97) ([JarbasAl](https://github.com/JarbasAl))

## [0.25.1a4](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.25.1a4) (2026-08-13)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.25.1a3...0.25.1a4)

**Merged pull requests:**

- refactor: migrate MCP server to the fastmcp package [\#100](https://github.com/OpenVoiceOS/ovos-stt-server/pull/100) ([JarbasAl](https://github.com/JarbasAl))

## [0.25.1a3](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.25.1a3) (2026-08-02)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.1.5a10...0.25.1a3)

**Closed issues:**

- feat: expose STT via MCP + UTCP [\#74](https://github.com/OpenVoiceOS/ovos-stt-server/issues/74)
- expose via UTCP and MCP [\#34](https://github.com/OpenVoiceOS/ovos-stt-server/issues/34)

**Merged pull requests:**

- ci: migrate release workflow to shared OpenVoiceOS automations [\#98](https://github.com/OpenVoiceOS/ovos-stt-server/pull/98) ([JarbasAl](https://github.com/JarbasAl))
- docs: rewrite README in Simplified Technical English [\#96](https://github.com/OpenVoiceOS/ovos-stt-server/pull/96) ([JarbasAl](https://github.com/JarbasAl))
- fix: declare python-multipart as a runtime dependency [\#93](https://github.com/OpenVoiceOS/ovos-stt-server/pull/93) ([JarbasAl](https://github.com/JarbasAl))
- feat: audio and utterance transformer pipelines [\#92](https://github.com/OpenVoiceOS/ovos-stt-server/pull/92) ([JarbasAl](https://github.com/JarbasAl))
- feat\(compat\): add ElevenLabs Scribe-compatible STT endpoint [\#90](https://github.com/OpenVoiceOS/ovos-stt-server/pull/90) ([JarbasAl](https://github.com/JarbasAl))
- feat\(compat\): add Gladia-compatible STT endpoint [\#89](https://github.com/OpenVoiceOS/ovos-stt-server/pull/89) ([JarbasAl](https://github.com/JarbasAl))
- feat\(compat\): add Groq-compatible STT endpoint [\#88](https://github.com/OpenVoiceOS/ovos-stt-server/pull/88) ([JarbasAl](https://github.com/JarbasAl))
- fix: router bugs, mount missing routers, and require all SDKs for e2e [\#87](https://github.com/OpenVoiceOS/ovos-stt-server/pull/87) ([JarbasAl](https://github.com/JarbasAl))
- fix: give the OpenAI and whisper.cpp routers dedicated vendor prefixes [\#86](https://github.com/OpenVoiceOS/ovos-stt-server/pull/86) ([JarbasAl](https://github.com/JarbasAl))
- docs: modernize README, docs/, and examples [\#85](https://github.com/OpenVoiceOS/ovos-stt-server/pull/85) ([JarbasAl](https://github.com/JarbasAl))
- docs: add NGI0 Commons Fund attribution [\#84](https://github.com/OpenVoiceOS/ovos-stt-server/pull/84) ([JarbasAl](https://github.com/JarbasAl))
- test: run official-SDK e2e tests in CI \(install vendor SDKs\) [\#82](https://github.com/OpenVoiceOS/ovos-stt-server/pull/82) ([JarbasAl](https://github.com/JarbasAl))
- feat\(compat\): vosk-server WebRTC variant \(/vosk-webrtc/offer\) [\#81](https://github.com/OpenVoiceOS/ovos-stt-server/pull/81) ([JarbasAl](https://github.com/JarbasAl))
- feat\(openai-whisper\): translate to English via OVOS translate plugin [\#80](https://github.com/OpenVoiceOS/ovos-stt-server/pull/80) ([JarbasAl](https://github.com/JarbasAl))
- feat\(compat\): vosk-server MQTT variant [\#79](https://github.com/OpenVoiceOS/ovos-stt-server/pull/79) ([JarbasAl](https://github.com/JarbasAl))
- feat\(compat\): vosk-server gRPC variant \(StreamingRecognize\) [\#78](https://github.com/OpenVoiceOS/ovos-stt-server/pull/78) ([JarbasAl](https://github.com/JarbasAl))
- feat\(compat\): OpenAI Whisper-compatible STT router \(/v1/audio/transcriptions\) [\#77](https://github.com/OpenVoiceOS/ovos-stt-server/pull/77) ([JarbasAl](https://github.com/JarbasAl))
- feat: expose STT via MCP and UTCP [\#75](https://github.com/OpenVoiceOS/ovos-stt-server/pull/75) ([JarbasAl](https://github.com/JarbasAl))
- ci: scope coverage to source package only [\#73](https://github.com/OpenVoiceOS/ovos-stt-server/pull/73) ([JarbasAl](https://github.com/JarbasAl))
- docs: voice-pihole hub — /docs index + centralised nginx recipes [\#70](https://github.com/OpenVoiceOS/ovos-stt-server/pull/70) ([JarbasAl](https://github.com/JarbasAl))
- feat: kaldi-gstreamer-server-compatible router \(/client\) [\#69](https://github.com/OpenVoiceOS/ovos-stt-server/pull/69) ([JarbasAl](https://github.com/JarbasAl))
- feat: Chromium / Chrome Web Speech API compat router \(/speech-api/v2\) [\#68](https://github.com/OpenVoiceOS/ovos-stt-server/pull/68) ([JarbasAl](https://github.com/JarbasAl))
- feat: whisper.cpp HTTP server-compatible router \(/whisper-cpp\) [\#64](https://github.com/OpenVoiceOS/ovos-stt-server/pull/64) ([JarbasAl](https://github.com/JarbasAl))
- feat: vosk-server-compatible WebSocket router \(/vosk\) [\#63](https://github.com/OpenVoiceOS/ovos-stt-server/pull/63) ([JarbasAl](https://github.com/JarbasAl))
- feat: Wit.ai-compatible /speech router \(/wit\) [\#62](https://github.com/OpenVoiceOS/ovos-stt-server/pull/62) ([JarbasAl](https://github.com/JarbasAl))
- feat: IBM Watson Speech-to-Text compat router \(/watson/speech-to-text\) [\#61](https://github.com/OpenVoiceOS/ovos-stt-server/pull/61) ([JarbasAl](https://github.com/JarbasAl))
- feat: AWS Transcribe compat router \(/aws\) [\#60](https://github.com/OpenVoiceOS/ovos-stt-server/pull/60) ([JarbasAl](https://github.com/JarbasAl))
- docs: Wyoming integration via TigreGotico adapter repos [\#59](https://github.com/OpenVoiceOS/ovos-stt-server/pull/59) ([JarbasAl](https://github.com/JarbasAl))
- feat: Microsoft Azure Speech STT compat router \(/azure-stt\) [\#58](https://github.com/OpenVoiceOS/ovos-stt-server/pull/58) ([JarbasAl](https://github.com/JarbasAl))
- feat: Speechmatics-compatible STT router \(/speechmatics\) [\#57](https://github.com/OpenVoiceOS/ovos-stt-server/pull/57) ([JarbasAl](https://github.com/JarbasAl))
- feat: AssemblyAI-compatible STT router \(/assemblyai\) [\#56](https://github.com/OpenVoiceOS/ovos-stt-server/pull/56) ([JarbasAl](https://github.com/JarbasAl))
- feat: Google Cloud STT-compatible router \(/google\) [\#55](https://github.com/OpenVoiceOS/ovos-stt-server/pull/55) ([JarbasAl](https://github.com/JarbasAl))
- feat: Deepgram-compatible STT router \(/deepgram\) [\#54](https://github.com/OpenVoiceOS/ovos-stt-server/pull/54) ([JarbasAl](https://github.com/JarbasAl))
- feat: modernize foundation \(no compat endpoints\) [\#52](https://github.com/OpenVoiceOS/ovos-stt-server/pull/52) ([JarbasAl](https://github.com/JarbasAl))

## [0.1.5a10](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.1.5a10) (2026-01-09)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.1.5a8...0.1.5a10)

**Closed issues:**

- ffmpeg requirement? [\#44](https://github.com/OpenVoiceOS/ovos-stt-server/issues/44)

## [0.1.5a8](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.1.5a8) (2026-01-09)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.1.5a7...0.1.5a8)

**Merged pull requests:**

- modernize: dont write audio to tmp file [\#45](https://github.com/OpenVoiceOS/ovos-stt-server/pull/45) ([JarbasAl](https://github.com/JarbasAl))

## [0.1.5a7](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.1.5a7) (2025-12-19)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.1.5a5...0.1.5a7)

**Merged pull requests:**

- Update dependency ovos-plugin-manager to v2 [\#43](https://github.com/OpenVoiceOS/ovos-stt-server/pull/43) ([renovate[bot]](https://github.com/apps/renovate))

## [0.1.5a5](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.1.5a5) (2025-12-18)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.1.5a3...0.1.5a5)

## [0.1.5a3](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.1.5a3) (2025-12-18)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.1.5a4...0.1.5a3)

## [0.1.5a4](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.1.5a4) (2025-12-18)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.1.5a2...0.1.5a4)

**Merged pull requests:**

- Update actions/setup-python action to v6 [\#41](https://github.com/OpenVoiceOS/ovos-stt-server/pull/41) ([renovate[bot]](https://github.com/apps/renovate))
- Update actions/checkout action to v6 [\#38](https://github.com/OpenVoiceOS/ovos-stt-server/pull/38) ([renovate[bot]](https://github.com/apps/renovate))
- Update dependency python to 3.14 [\#37](https://github.com/OpenVoiceOS/ovos-stt-server/pull/37) ([renovate[bot]](https://github.com/apps/renovate))

## [0.1.5a2](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.1.5a2) (2025-12-18)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.1.5a1...0.1.5a2)

**Merged pull requests:**

- Configure Renovate [\#36](https://github.com/OpenVoiceOS/ovos-stt-server/pull/36) ([renovate[bot]](https://github.com/apps/renovate))
- Add CORS middleware for STT web services [\#35](https://github.com/OpenVoiceOS/ovos-stt-server/pull/35) ([suvanbanerjee](https://github.com/suvanbanerjee))

## [0.1.5a1](https://github.com/OpenVoiceOS/ovos-stt-server/tree/0.1.5a1) (2025-04-05)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-stt-server/compare/0.1.4...0.1.5a1)



\* *This Changelog was automatically generated by [github_changelog_generator](https://github.com/github-changelog-generator/github-changelog-generator)*
