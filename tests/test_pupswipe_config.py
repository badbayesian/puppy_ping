import builtins
from types import SimpleNamespace

import pytest

import puppyping.pupswipe.config as config
import puppyping.pupswipe.server as pupswipe


def _clear_runtime_env(monkeypatch):
    monkeypatch.delenv("PUPSWIPE_PUBLIC_URL", raising=False)
    monkeypatch.delenv("PUPSWIPE_SESSION_SECRET", raising=False)


def test_validate_runtime_config_rejects_missing_public_url(monkeypatch):
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("PUPSWIPE_SESSION_SECRET", "unit-test-secret")

    with pytest.raises(ValueError, match="PUPSWIPE_PUBLIC_URL"):
        config.validate_runtime_config()


def test_validate_runtime_config_rejects_default_session_secret(monkeypatch):
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("PUPSWIPE_PUBLIC_URL", "https://pups.example")
    monkeypatch.setenv("PUPSWIPE_SESSION_SECRET", config.DEFAULT_SESSION_SECRET)

    with pytest.raises(ValueError, match="PUPSWIPE_SESSION_SECRET"):
        config.validate_runtime_config()


def test_handler_absolute_url_ignores_request_host_headers(monkeypatch):
    monkeypatch.setenv("PUPSWIPE_PUBLIC_URL", "https://safe.example/base/")
    handler = pupswipe.AppHandler.__new__(pupswipe.AppHandler)
    handler.headers = {
        "Host": "evil.example",
        "X-Forwarded-Host": "still-evil.example",
        "X-Forwarded-Proto": "http",
    }

    assert handler._public_base_url() == "https://safe.example/base"
    assert (
        handler._absolute_url("/forgot-password/reset?token=abc")
        == "https://safe.example/base/forgot-password/reset?token=abc"
    )


def test_main_validates_runtime_config_and_bootstraps_schema(monkeypatch):
    calls: dict[str, object] = {}

    class DummyConn:
        def __enter__(self):
            calls["entered_connection"] = True
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class DummyServer:
        def __init__(self, address, handler_cls):
            calls["server_address"] = address
            calls["handler_cls"] = handler_cls

        def serve_forever(self):
            calls["served"] = True
            raise KeyboardInterrupt

    monkeypatch.setattr(
        pupswipe.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(host="127.0.0.1", port=8123),
    )
    monkeypatch.setattr(
        pupswipe,
        "validate_runtime_config",
        lambda: calls.setdefault("validated", True),
    )
    monkeypatch.setattr(pupswipe, "get_connection", lambda: DummyConn())
    monkeypatch.setattr(
        pupswipe,
        "_ensure_app_schema",
        lambda conn: calls.setdefault("bootstrapped_with", conn),
    )
    monkeypatch.setattr(pupswipe, "ThreadingHTTPServer", DummyServer)
    monkeypatch.setattr(builtins, "print", lambda *args, **kwargs: None)

    pupswipe.main()

    assert calls["validated"] is True
    assert calls["entered_connection"] is True
    assert isinstance(calls["bootstrapped_with"], DummyConn)
    assert calls["server_address"] == ("127.0.0.1", 8123)
    assert calls["handler_cls"] is pupswipe.AppHandler
    assert calls["served"] is True
