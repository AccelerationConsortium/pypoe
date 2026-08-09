"""Tests for per-provider API health classification and probing.

Regression target: PyPoe reported ``equipment_status: "ready"`` while every
chat call failed with ``subscription_required``, because the ``poe_api``
component was "probed" with a hardcoded local model list that never touched
the network.
"""

import json

import pytest

from pypoe.core.provider_health import (
    ACCOUNT_BLOCKING_REASONS,
    MODEL_SCOPED_REASONS,
    ProviderHealthTracker,
    classify_error_body,
    classify_exception,
    code_for,
    component_for,
    probe_provider,
    split_code,
)
from pypoe.core.providers import OPENROUTER, POE, PROVIDERS, get_provider


class _FakeBotError(Exception):
    """Mimics fastapi_poe's BotErrorNoRetry, whose str() is a JSON body."""


def _bot_error(**payload) -> _FakeBotError:
    return _FakeBotError(json.dumps(payload))


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------

def test_classifies_the_live_poe_subscription_error():
    """The exact payload Poe returned when the subscription lapsed."""
    exc = _bot_error(
        text="The model Claude-Opus-4.8 requires an active Poe subscription for API access.",
        allow_retry=False,
        error_type="subscription_required",
    )
    reason, message = classify_exception(exc)
    assert reason == "subscription_required"
    assert "active Poe subscription" in message


def test_classifies_openrouter_numeric_code_as_auth_failure():
    """OpenRouter puts an int HTTP status in "code", not a type name.

    Treating 401 as a type would skip the status-code fallback and misfile a
    rejected key as a generic API error.
    """
    body = {"error": {"message": "User not found.", "code": 401}}
    reason, message = classify_error_body(body, status_code=401)
    assert reason == "auth_failed"
    assert message == "User not found."


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"text": "boom", "error_type": "insufficient_fund"}, "insufficient_credits"),
        ({"text": "boom", "error_type": "invalid_api_key"}, "auth_failed"),
        ({"text": "boom", "error_type": "rate_limit_exceeded"}, "rate_limited"),
        ({"text": "Bot does not exist", "error_type": ""}, "model_unavailable"),
        ({"text": "Cannot access private bots", "error_type": ""}, "model_unavailable"),
        ({"text": "No endpoints found for this model", "error_type": ""}, "model_unavailable"),
        ({"text": "something odd", "error_type": ""}, "api_error"),
    ],
)
def test_classification_taxonomy(payload, expected):
    assert classify_exception(_bot_error(**payload))[0] == expected


@pytest.mark.parametrize(
    "status,expected",
    [(401, "auth_failed"), (402, "subscription_required"), (429, "rate_limited")],
)
def test_bare_status_codes_are_classified(status, expected):
    """A body with no usable type falls back to the HTTP status."""
    assert classify_error_body(None, status_code=status)[0] == expected


def test_non_json_transport_error_is_unreachable():
    assert classify_exception(OSError("Name or service not known"))[0] == "unreachable"


def test_reason_partitioning():
    """Only account-level reasons take a provider down; model ones never do."""
    assert "subscription_required" in ACCOUNT_BLOCKING_REASONS
    assert "insufficient_credits" in ACCOUNT_BLOCKING_REASONS
    assert "model_unavailable" in MODEL_SCOPED_REASONS
    assert not (ACCOUNT_BLOCKING_REASONS & MODEL_SCOPED_REASONS)
    assert "rate_limited" not in ACCOUNT_BLOCKING_REASONS


def test_codes_are_provider_qualified_and_reversible():
    """The wire code says both what broke and whose it was."""
    assert code_for(POE, "subscription_required") == "poe_subscription_required"
    assert code_for(OPENROUTER, "auth_failed") == "openrouter_auth_failed"
    assert split_code("openrouter_auth_failed") == (OPENROUTER, "auth_failed")
    assert split_code("poe_subscription_required") == (POE, "subscription_required")


def test_recovery_hints_name_the_right_provider():
    poe = component_for(_state(POE, "auth_failed", "nope"))
    router = component_for(_state(OPENROUTER, "auth_failed", "nope"))
    assert "POE_API_KEY" in poe["message"]
    assert "OPENROUTER_API_KEY" in router["message"]
    assert "openrouter.ai" in router["message"]


def _state(provider, reason, message):
    tracker = ProviderHealthTracker(provider)
    tracker.record_failure(reason, message)
    return tracker.snapshot()


# --------------------------------------------------------------------------
# tracker
# --------------------------------------------------------------------------

def test_tracker_starts_unknown_and_is_not_connected():
    """An unverified state must not read as healthy (STATUS_SPEC §2.1)."""
    state = ProviderHealthTracker(POE).snapshot()
    assert state.state == "unknown"
    assert component_for(state)["connected"] is False


def test_tracker_records_and_clears_failures():
    tracker = ProviderHealthTracker(POE)
    tracker.record_exception(_bot_error(text="nope", error_type="subscription_required"))

    state = tracker.snapshot()
    assert state.code == "poe_subscription_required"
    assert state.ok is False

    rendered = component_for(state)
    assert rendered["connected"] is False
    assert rendered["state"] == "poe_subscription_required"
    assert "subscription_plans" in rendered["message"]  # recovery hint attached

    tracker.record_success()
    assert component_for(tracker.snapshot()) == {
        "connected": True,
        "state": "connected",
        "message": None,
    }


def test_probe_cadence_is_asymmetric():
    """Cheap-when-broken: a failing probe costs nothing, so re-check sooner."""
    tracker = ProviderHealthTracker(POE)
    assert tracker.needs_probe() is True  # no evidence at all

    tracker.record_success()
    assert tracker.needs_probe() is False
    assert tracker.UNHEALTHY_PROBE_INTERVAL_S < tracker.HEALTHY_PROBE_INTERVAL_S

    # Age the healthy observation past the unhealthy interval but not the
    # healthy one: a working provider must not be re-probed that eagerly.
    state = tracker.snapshot()
    state.monotonic_at -= tracker.UNHEALTHY_PROBE_INTERVAL_S + 1
    assert tracker.needs_probe() is False

    state.monotonic_at -= tracker.HEALTHY_PROBE_INTERVAL_S
    assert tracker.needs_probe() is True


def test_low_balance_degrades_a_metered_provider():
    """Say it before requests start failing, not after."""
    tracker = ProviderHealthTracker(OPENROUTER)
    tracker.record_success()
    tracker.record_credits({"granted": 10.0, "used": 9.6, "remaining": 0.4})

    rendered = component_for(tracker.snapshot(), low_credit_threshold=1.0)
    assert rendered["connected"] is False
    assert rendered["state"] == "openrouter_insufficient_credits"
    assert "0.40" in rendered["message"]

    # Comfortable balance stays healthy.
    tracker.record_credits({"granted": 10.0, "used": 1.0, "remaining": 9.0})
    assert component_for(tracker.snapshot(), low_credit_threshold=1.0)["connected"] is True


def test_credits_do_not_disturb_the_freshness_clock():
    tracker = ProviderHealthTracker(OPENROUTER)
    tracker.record_success()
    before = tracker.snapshot().monotonic_at
    tracker.record_credits({"remaining": 5.0})
    assert tracker.snapshot().monotonic_at == before


# --------------------------------------------------------------------------
# active probe
# --------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeAsyncClient:
    calls = []

    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        type(self).calls.append({"url": url, "json": json, "headers": headers})
        if self._raises is not None:
            raise self._raises
        return self._response


@pytest.fixture
def fake_httpx(monkeypatch):
    import httpx

    _FakeAsyncClient.calls = []

    def _install(response=None, raises=None):
        monkeypatch.setattr(
            httpx, "AsyncClient", _FakeAsyncClient(response=response, raises=raises)
        )

    return _install


@pytest.mark.asyncio
async def test_probe_reports_poe_subscription_required(fake_httpx):
    """HTTP 402 is the live signal an unsubscribed Poe account returns."""
    fake_httpx(
        _FakeResponse(
            402,
            {
                "error": {
                    "message": "The model Claude-Opus-4.8 requires an active Poe subscription for API access.",
                    "type": "subscription_required",
                    "code": "subscription_required",
                }
            },
        )
    )
    ok, reason, message = await probe_provider(PROVIDERS[POE], "key", "Claude-Opus-4.8")
    assert (ok, reason) == (False, "subscription_required")
    assert "active Poe subscription" in message


@pytest.mark.asyncio
async def test_probe_is_minimal_and_identifies_the_caller(fake_httpx):
    fake_httpx(_FakeResponse(200, {"choices": []}))
    ok, reason, _ = await probe_provider(PROVIDERS[OPENROUTER], "sk-or-key", "some/model")

    assert (ok, reason) == (True, None)
    call = _FakeAsyncClient.calls[-1]
    assert call["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-or-key"
    # OpenRouter asks callers to identify themselves for attribution.
    assert call["headers"]["X-Title"] == "PyPoe"
    # max_tokens=1 keeps a healthy probe as cheap as the API allows.
    assert call["json"]["max_tokens"] == 1
    assert call["json"]["model"] == "some/model"


@pytest.mark.asyncio
async def test_probe_maps_transport_failure_to_unreachable(fake_httpx):
    fake_httpx(raises=OSError("connection refused"))
    ok, reason, message = await probe_provider(PROVIDERS[POE], "key", "M")
    assert (ok, reason) == (False, "unreachable")
    assert "connection refused" in message


@pytest.mark.asyncio
async def test_probe_maps_openrouter_bad_key(fake_httpx):
    """The real shape OpenRouter returns for a rejected key."""
    fake_httpx(_FakeResponse(401, {"error": {"message": "User not found.", "code": 401}}))
    ok, reason, _ = await probe_provider(PROVIDERS[OPENROUTER], "bad", "some/model")
    assert (ok, reason) == (False, "auth_failed")
