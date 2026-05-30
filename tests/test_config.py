import importlib
import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _reload_config():
    import config

    return importlib.reload(config)


def test_youtube_proxy_defaults_to_disabled_without_urls(monkeypatch):
    monkeypatch.setenv("YOUTUBE_PROXY_ENABLED", "")
    monkeypatch.setenv("YOUTUBE_PROXY_HTTP_URL", "")
    monkeypatch.setenv("YOUTUBE_PROXY_HTTPS_URL", "")

    config = _reload_config()

    assert config.YOUTUBE_PROXY_HTTP_URL is None
    assert config.YOUTUBE_PROXY_HTTPS_URL is None
    assert config.YOUTUBE_PROXY_ENABLED is False


def test_youtube_proxy_enabled_with_only_http_url(monkeypatch):
    monkeypatch.delenv("YOUTUBE_PROXY_ENABLED", raising=False)
    monkeypatch.setenv("YOUTUBE_PROXY_HTTP_URL", "http://user:pass@proxy.example:8080")
    monkeypatch.setenv("YOUTUBE_PROXY_HTTPS_URL", "")

    config = _reload_config()

    assert config.YOUTUBE_PROXY_HTTP_URL == "http://user:pass@proxy.example:8080"
    assert config.YOUTUBE_PROXY_HTTPS_URL is None
    assert config.YOUTUBE_PROXY_ENABLED is True


def test_youtube_proxy_respects_explicit_enabled_flag_with_both_urls(monkeypatch):
    monkeypatch.setenv("YOUTUBE_PROXY_ENABLED", "true")
    monkeypatch.setenv("YOUTUBE_PROXY_HTTP_URL", "http://proxy-http.example:8080")
    monkeypatch.setenv("YOUTUBE_PROXY_HTTPS_URL", "https://proxy-https.example:8443")

    config = _reload_config()

    assert config.YOUTUBE_PROXY_HTTP_URL == "http://proxy-http.example:8080"
    assert config.YOUTUBE_PROXY_HTTPS_URL == "https://proxy-https.example:8443"
    assert config.YOUTUBE_PROXY_ENABLED is True


def test_yt_dlp_deno_path_prefers_explicit_env(monkeypatch):
    monkeypatch.setenv("YT_DLP_DENO_PATH", "/opt/render/.deno/bin/deno")

    config = _reload_config()

    assert config.YT_DLP_DENO_PATH == "/opt/render/.deno/bin/deno"
