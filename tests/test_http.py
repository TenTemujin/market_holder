import urllib.error

import pytest

from market_holder.providers import http
from market_holder.providers.http import FetchError, UrlFetcher


class Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, None)


def script(monkeypatch, outcomes):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        out = outcomes[len(calls) - 1]
        if isinstance(out, Exception):
            raise out
        return Resp(out)

    monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
    return calls


def fetcher(sleeps, **kw):
    return UrlFetcher(min_interval_s=0, sleep=sleeps.append, **kw)


def test_retries_transient_status_with_exponential_backoff(monkeypatch):
    calls, sleeps = script(monkeypatch, [http_error(503), http_error(429), b"ok"]), []
    assert fetcher(sleeps, backoff_s=1.0).fetch("http://x") == b"ok"
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]


def test_non_retryable_status_fails_immediately(monkeypatch):
    calls = script(monkeypatch, [http_error(404)])
    with pytest.raises(FetchError, match="404"):
        fetcher([]).fetch("http://x")
    assert len(calls) == 1


def test_gives_up_after_retries(monkeypatch):
    calls = script(monkeypatch, [urllib.error.URLError("down")] * 3)
    with pytest.raises(FetchError, match="3 tentativas"):
        fetcher([], retries=3).fetch("http://x")
    assert len(calls) == 3


def test_rate_limit_waits_min_interval(monkeypatch):
    script(monkeypatch, [b"a", b"b"])
    now, sleeps = [100.0], []
    f = UrlFetcher(min_interval_s=0.5, sleep=sleeps.append, clock=lambda: now[0])
    f.fetch("http://x")
    now[0] += 0.2  # só 0.2 s depois: precisa esperar 0.3 s
    f.fetch("http://x")
    assert sleeps == [pytest.approx(0.3)]
