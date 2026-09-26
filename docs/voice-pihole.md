# Voice Pihole

A single network-layer interception recipe per cloud STT vendor, so that
**unmodified consumer apps stop calling cloud services** and land on your
`ovos-stt-http-server` box instead. No client SDK changes, no API key
swaps, no app-config edits. Just DNS and a TLS-terminating reverse proxy.

The pattern across every vendor is the same:

1. **DNS interception.** Pin the vendor's hostname to your server's IP via
   `/etc/hosts` (single host) or your LAN's DNS (Pi-hole / Unbound /
   dnsmasq / pfSense / OPNsense).
2. **TLS termination.** Run nginx (or Caddy / HAProxy / Envoy) on `443`
   for the vendor's hostname, holding a cert your clients trust.
3. **Path rewrite.** Map the vendor's upstream path to our internal prefix
   so the rest of FastAPI's routing works.
4. **CA trust.** Either sign the proxy cert with a CA the client already
   trusts (corporate PKI, mkcert root) or push the CA into the client's
   trust store (`REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`, system trust).

This document holds the consolidated config. Each per-vendor section in
[`api-compatibility.md`](api-compatibility.md) references the matching
block here.

> :warning: **Intercepting a hostname catches *every* request to it.**
> `www.google.com` is shared with chat, search, Drive, etc. Intercepting
> it without forwarding the non-STT paths back upstream breaks those
> features on the client. The example configs below isolate the STT path
> and either 404 or transparent-proxy everything else.

---

## Common nginx prelude

Every server block below assumes this `map` directive is in your
`nginx.conf` (or in a `conf.d/*.conf` snippet loaded into `http {}`):

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}
```

It's needed any time a WS upgrade is forwarded.

---

## Cert + CA trust setup

For each hostname you intercept you need an X.509 cert with the vendor's
hostname in the SAN list. Two common approaches:

### A) Internal CA (production)

1. Generate an internal CA (e.g. via `step-ca`, `cfssl`, or even
   `openssl`).
2. Install the CA cert in the client device's trust store (corporate
   MDM, dotfiles, system keychain, `update-ca-certificates`).
3. Issue per-hostname leaf certs from this CA.

This is what corporate VPN + DLP deployments already do. Re-use that
trust chain.

### B) mkcert (lab / dev)

```bash
brew install mkcert  # or apt / scoop / cargo
mkcert -install
mkcert api.openai.com api.deepgram.com '*.googleapis.com' \
       api.assemblyai.com api.wit.ai \
       '*.speech.microsoft.com' \
       'transcribe.*.amazonaws.com' \
       'api.*.speech-to-text.watson.cloud.ibm.com' \
       'asr.api.speechmatics.com'
```

mkcert installs its CA into the system trust automatically.

---

## Per-vendor nginx blocks

### OpenAI Whisper (`api.openai.com`)

```nginx
server {
    listen 443 ssl;
    server_name api.openai.com;
    ssl_certificate     /etc/ssl/private/api.openai.com.crt;
    ssl_certificate_key /etc/ssl/private/api.openai.com.key;

    # Audio endpoints → /openai/v1/audio/*
    location /v1/audio/ {
        proxy_pass         http://127.0.0.1:8080/openai/v1/audio/;
        proxy_set_header   Host $host;
        proxy_buffering    off;
    }
    # Some SDKs probe /v1/models at startup; return a benign stub
    location /v1/models {
        return 200 '{"data":[]}';
        add_header Content-Type application/json;
    }
    location / { return 404; }
}
```

### Deepgram (`api.deepgram.com`, REST + WS)

```nginx
server {
    listen 443 ssl;
    server_name api.deepgram.com;
    ssl_certificate     /etc/ssl/private/api.deepgram.com.crt;
    ssl_certificate_key /etc/ssl/private/api.deepgram.com.key;

    location /v1/listen {
        proxy_pass         http://127.0.0.1:8080/deepgram/v1/listen;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection $connection_upgrade;
        proxy_set_header   Host $host;
        proxy_buffering    off;
        proxy_read_timeout 300s;
    }
    location / { return 404; }
}
```

### Google Cloud STT (`speech.googleapis.com`)

```nginx
server {
    listen 443 ssl;
    server_name speech.googleapis.com;
    ssl_certificate     /etc/ssl/private/speech.googleapis.com.crt;
    ssl_certificate_key /etc/ssl/private/speech.googleapis.com.key;

    location /v1/speech:recognize {
        proxy_pass         http://127.0.0.1:8080/google/v1/speech:recognize;
        proxy_set_header   Host $host;
        proxy_buffering    off;
    }
    location / { return 404; }
}
```

> :information_source: The `google-cloud-speech` Python SDK builds host-only
> endpoints. For it to work you also need the in-Python monkey-patch
> documented in `api-compatibility.md` under Google STT. Raw REST clients
> don't need that.

### AssemblyAI (`api.assemblyai.com`, REST + realtime WS)

```nginx
server {
    listen 443 ssl;
    server_name api.assemblyai.com;
    ssl_certificate     /etc/ssl/private/api.assemblyai.com.crt;
    ssl_certificate_key /etc/ssl/private/api.assemblyai.com.key;

    location /v2/ {
        proxy_pass         http://127.0.0.1:8080/assemblyai/v2/;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection $connection_upgrade;
        proxy_set_header   Host $host;
        proxy_request_buffering off;
        proxy_buffering          off;
        proxy_read_timeout       300s;
    }
    location / { return 404; }
}
```

### Speechmatics (batch `asr.api.speechmatics.com` + realtime `eu2.rt.speechmatics.com`)

```nginx
# Batch host
server {
    listen 443 ssl;
    server_name asr.api.speechmatics.com;
    ssl_certificate     /etc/ssl/private/asr.api.speechmatics.com.crt;
    ssl_certificate_key /etc/ssl/private/asr.api.speechmatics.com.key;

    location /v2/ {
        rewrite ^/v2/(.*)$ /speechmatics/v1/$1 break;
        proxy_pass         http://127.0.0.1:8080;
        proxy_set_header   Host $host;
        proxy_buffering    off;
    }
    location / { return 404; }
}

# Realtime host
server {
    listen 443 ssl;
    server_name eu2.rt.speechmatics.com;
    ssl_certificate     /etc/ssl/private/eu2.rt.speechmatics.com.crt;
    ssl_certificate_key /etc/ssl/private/eu2.rt.speechmatics.com.key;

    location = /v2 {
        proxy_pass         http://127.0.0.1:8080/speechmatics/v1;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection $connection_upgrade;
        proxy_set_header   Host $host;
        proxy_read_timeout 300s;
    }
    location / { return 404; }
}
```

### Microsoft Azure Speech (`*.stt.speech.microsoft.com`)

```nginx
server {
    listen 443 ssl;
    server_name ~^[a-z0-9]+\.stt\.speech\.microsoft\.com$;
    ssl_certificate     /etc/ssl/private/stt.speech.microsoft.com.crt;
    ssl_certificate_key /etc/ssl/private/stt.speech.microsoft.com.key;

    location /speech/recognition/conversation/cognitiveservices/v1 {
        proxy_pass         http://127.0.0.1:8080/azure-stt/cognitiveservices/v1;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection $connection_upgrade;
        proxy_set_header   Host $host;
        proxy_buffering    off;
        proxy_read_timeout 300s;
    }
    location / { return 404; }
}
```

### AWS Transcribe (`transcribe.*.amazonaws.com` + `transcribestreaming.*.amazonaws.com`)

```nginx
# Batch
server {
    listen 443 ssl;
    server_name ~^transcribe\.[a-z0-9-]+\.amazonaws\.com$;
    ssl_certificate     /etc/ssl/private/transcribe.amazonaws.com.crt;
    ssl_certificate_key /etc/ssl/private/transcribe.amazonaws.com.key;

    location = / {
        proxy_pass         http://127.0.0.1:8080/aws/transcribe;
        proxy_set_header   Host $host;
        proxy_buffering    off;
    }
    location / { return 404; }
}

# Streaming
server {
    listen 443 ssl;
    server_name ~^transcribestreaming\.[a-z0-9-]+\.amazonaws\.com$;
    ssl_certificate     /etc/ssl/private/transcribestreaming.amazonaws.com.crt;
    ssl_certificate_key /etc/ssl/private/transcribestreaming.amazonaws.com.key;

    location /stream-transcription {
        proxy_pass         http://127.0.0.1:8080/aws/transcribestreaming/stream-transcription;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection $connection_upgrade;
        proxy_set_header   Host $host;
        proxy_read_timeout 300s;
        proxy_buffering    off;
    }
    location / { return 404; }
}
```

### IBM Watson STT (`api.*.speech-to-text.watson.cloud.ibm.com`)

```nginx
server {
    listen 443 ssl;
    server_name ~^api\.[a-z0-9-]+\.speech-to-text\.watson\.cloud\.ibm\.com$;
    ssl_certificate     /etc/ssl/private/watson-stt.crt;
    ssl_certificate_key /etc/ssl/private/watson-stt.key;

    location /v1/recognize {
        proxy_pass         http://127.0.0.1:8080/watson/speech-to-text/v1/recognize;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection $connection_upgrade;
        proxy_set_header   Host $host;
        proxy_buffering    off;
        proxy_read_timeout 300s;
    }
    location / { return 404; }
}
```

### Wit.ai (`api.wit.ai`)

```nginx
server {
    listen 443 ssl;
    server_name api.wit.ai;
    ssl_certificate     /etc/ssl/private/api.wit.ai.crt;
    ssl_certificate_key /etc/ssl/private/api.wit.ai.key;

    location /speech {
        proxy_pass         http://127.0.0.1:8080/wit/speech;
        proxy_set_header   Host $host;
        proxy_request_buffering off;
        proxy_buffering          off;
    }
    location / { return 404; }
}
```

### Chromium / Chrome Web Speech (`www.google.com/speech-api`)

This one is special. `www.google.com` is shared with **every other Google
service**, so the nginx block must forward unrelated paths back to the
real Google. The upstream endpoint is plain HTTP, but modern Chrome may
upgrade it to HTTPS. Listen on both.

```nginx
server {
    listen 80;
    listen 443 ssl;
    server_name www.google.com;
    ssl_certificate     /etc/ssl/private/www.google.com.crt;
    ssl_certificate_key /etc/ssl/private/www.google.com.key;

    # STT path → us
    location /speech-api/ {
        proxy_pass         http://127.0.0.1:8080/speech-api/;
        proxy_set_header   Host $host;
        proxy_buffering    off;
    }

    # Everything else proxied to the real Google so other features keep
    # working. Resolver bypasses our hosts/DNS rewrite so we hit real DNS.
    resolver 8.8.8.8 1.1.1.1 ipv6=off valid=300s;
    location / {
        set $upstream "www.google.com";
        proxy_pass         https://$upstream$request_uri;
        proxy_set_header   Host www.google.com;
        proxy_ssl_server_name on;
    }
}
```

---

## Self-hosted server replacement

For self-hosted protocols (vosk-server, kaldi-gstreamer-server,
whisper.cpp) you usually replace them at the bind-port level rather than
intercepting a public hostname. Stop the old process, start
ovos-stt-http-server on the same port, and clients keep working.

See each per-protocol section in `api-compatibility.md` for the matching
nginx config (most just need the port-swap and a single `location /`
rewrite to our internal prefix).

---

## Putting it together

A complete "voice pihole" deployment is:

```
┌──────────────────────────────┐
│   Pi-hole / Unbound / pfSense│   1) DNS rewrites for all the hosts above
│   (LAN-wide DNS)             │
└──────────────┬───────────────┘
               │ resolves api.openai.com etc. → 192.168.1.50
               ▼
┌──────────────────────────────┐
│   nginx (192.168.1.50:443)   │   2) TLS termination + path rewrite
│   - one server{} per vendor  │   3) cert from a CA trusted on clients
└──────────────┬───────────────┘
               │ proxies to 127.0.0.1:8080/<vendor-prefix>/...
               ▼
┌──────────────────────────────┐
│   ovos-stt-http-server       │   4) compat router for each vendor
│   :8080 (HTTP)               │      → OVOS STT plugin (the actual ASR)
│   :50051 (vosk-gRPC, opt-in) │
│   MQTT bridge (opt-in)       │
└──────────────────────────────┘
```

Once the DNS rewrite + TLS cert + reverse proxy are in place, **every**
consumer app on the LAN that uses any of the above APIs is automatically
served by your local OVOS plugin. No client-side change is required.

---
[← Wyoming integration](wyoming-integration.md) · [Home](README.md)
