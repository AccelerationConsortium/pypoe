"""End-to-end: ``/status`` must tell the truth about every model provider.

Two regressions are pinned here:

1. A lapsed Poe subscription used to leave the tile ``ready``, because the
   ``poe_api`` component was checked with ``client.get_available_bots()`` — a
   hardcoded local list, no network.
2. With per-model routing, one dead provider must not condemn a healthy one:
   PyPoe can still chat as long as *some* provider answers.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

import pypoe.interfaces.web.app as appmod
from pypoe.core.provider_health import HealthRegistry
from pypoe.core.providers import OPENROUTER, POE


SUBSCRIPTION_PAYLOAD = json.dumps(
    {
        "text": "The model Claude-Opus-4.8 requires an active Poe subscription for API access.",
        "allow_retry": False,
        "error_type": "subscription_required",
    }
)


class _StubClient:
    async def get_conversations(self):
        return []


def _status_host(monkeypatch, *, poe_key="poe-key", openrouter_key="", registry=None):
    """A minimal WebApp bound to just what ``_status_payload`` touches."""
    host = object.__new__(appmod.WebApp)
    host.config = type(
        "Cfg",
        (),
        {
            "poe_api_key": poe_key,
            "openrouter_api_key": openrouter_key,
            "openrouter_max_tokens": 4096,
            "openrouter_min_credits": 1.0,
            "database_path": "/nonexistent/lab.db",
        },
    )()
    host.client = _StubClient()
    host._status_cache = None
    host._status_cache_expires_at = 0.0
    host._claim = None

    # Keep the non-provider components healthy so assertions are unambiguously
    # about provider health.
    monkeypatch.setattr(
        appmod.WebApp,
        "_network_components",
        lambda self: (
            {
                "internet": self._component(True, "reachable"),
                "tailscale": self._component(True, "up"),
                "wifi": self._component(True, "associated"),
            },
            {},
            {},
        ),
    )
    monkeypatch.delenv("PYPOE_KUMA_URL", raising=False)
    monkeypatch.delenv("PYPOE_HEALTH_PROBE_MODEL", raising=False)
    monkeypatch.setattr(appmod, "health", registry or HealthRegistry())
    return host


def _probe_returning(results):
    """Fake probe driven by a {provider_name: (ok, reason, message)} map."""
    seen = []

    async def _probe(spec, api_key, model, **kwargs):
        seen.append((spec.name, model))
        return results[spec.name]

    _probe.seen = seen
    return _probe


async def _no_credits(spec, **kwargs):
    return None


@pytest.mark.asyncio
async def test_lapsed_poe_subscription_degrades_the_envelope(monkeypatch):
    """The original bug: sole provider dead => must not read "ready"."""
    host = _status_host(monkeypatch)
    monkeypatch.setattr(
        appmod,
        "probe_provider",
        _probe_returning(
            {
                POE: (
                    False,
                    "subscription_required",
                    "The model requires an active Poe subscription for API access.",
                )
            }
        ),
    )

    payload = await host._status_payload()

    assert payload["equipment_status"] == "degraded"          # not "ready"
    assert "No model provider available" in payload["message"]
    assert "subscription" in payload["message"].lower()

    poe = payload["components"]["poe_api"]
    assert poe["connected"] is False
    assert poe["state"] == "poe_subscription_required"

    # Structured, branchable error per STATUS_SPEC best practice #6.
    assert payload["last_error"]["code"] == "poe_subscription_required"
    assert payload["last_error"]["severity"] == "error"


@pytest.mark.asyncio
async def test_openrouter_carries_the_service_when_poe_is_dead(monkeypatch):
    """The point of per-model routing: one live provider keeps PyPoe working."""
    host = _status_host(monkeypatch, openrouter_key="sk-or-key")
    monkeypatch.setattr(
        appmod,
        "probe_provider",
        _probe_returning(
            {
                POE: (False, "subscription_required", "Poe subscription lapsed"),
                OPENROUTER: (True, None, None),
            }
        ),
    )
    monkeypatch.setattr(appmod, "fetch_credits", _no_credits)

    payload = await host._status_payload()

    assert payload["equipment_status"] == "ready"
    assert "OpenRouter" in payload["message"]                 # names who's carrying it
    # Both truths are still visible per component.
    assert payload["components"]["poe_api"]["state"] == "poe_subscription_required"
    assert payload["components"]["openrouter_api"]["connected"] is True


@pytest.mark.asyncio
async def test_both_providers_down_is_degraded_and_names_both(monkeypatch):
    host = _status_host(monkeypatch, openrouter_key="sk-or-key")
    monkeypatch.setattr(
        appmod,
        "probe_provider",
        _probe_returning(
            {
                POE: (False, "subscription_required", "Poe subscription lapsed"),
                OPENROUTER: (False, "auth_failed", "User not found."),
            }
        ),
    )

    payload = await host._status_payload()

    assert payload["equipment_status"] == "degraded"
    assert "Poe" in payload["message"] and "OpenRouter" in payload["message"]
    # An account-level error outranks the others for last_error.
    assert payload["last_error"]["severity"] == "error"


@pytest.mark.asyncio
async def test_unconfigured_provider_is_omitted_not_failed(monkeypatch):
    """A provider you never set up is not a fault."""
    host = _status_host(monkeypatch, openrouter_key="")
    monkeypatch.setattr(
        appmod, "probe_provider", _probe_returning({POE: (True, None, None)})
    )

    payload = await host._status_payload()

    assert payload["equipment_status"] == "ready"
    assert "openrouter_api" not in payload["components"]
    assert payload["message"] is None   # no "serving via" noise for the only provider


@pytest.mark.asyncio
async def test_credits_surface_on_the_envelope(monkeypatch):
    """Spend guard: the balance is visible before it runs out."""
    host = _status_host(monkeypatch, poe_key="", openrouter_key="sk-or-key")
    monkeypatch.setattr(
        appmod, "probe_provider", _probe_returning({OPENROUTER: (True, None, None)})
    )

    async def _credits(spec, **kwargs):
        return {"granted": 10.0, "used": 7.5, "remaining": 2.5}

    monkeypatch.setattr(appmod, "fetch_credits", _credits)

    payload = await host._status_payload()

    assert payload["equipment_status"] == "ready"
    assert payload["metrics"]["openrouter_credits_remaining"]["value"] == 2.5
    assert payload["metrics"]["openrouter_credits_remaining"]["unit"] == "USD"
    assert payload["details"]["openrouter_credits"]["remaining"] == 2.5


@pytest.mark.asyncio
async def test_low_balance_degrades_before_requests_fail(monkeypatch):
    host = _status_host(monkeypatch, poe_key="", openrouter_key="sk-or-key")
    monkeypatch.setattr(
        appmod, "probe_provider", _probe_returning({OPENROUTER: (True, None, None)})
    )

    async def _credits(spec, **kwargs):
        return {"granted": 10.0, "used": 9.8, "remaining": 0.2}

    monkeypatch.setattr(appmod, "fetch_credits", _credits)

    payload = await host._status_payload()

    assert payload["equipment_status"] == "degraded"
    assert payload["components"]["openrouter_api"]["state"] == "openrouter_insufficient_credits"


@pytest.mark.asyncio
async def test_no_provider_configured_still_explains_itself(monkeypatch):
    host = _status_host(monkeypatch, poe_key="", openrouter_key="")

    async def _no_probe(*args, **kwargs):
        raise AssertionError("probe should not have been called")

    monkeypatch.setattr(appmod, "probe_provider", _no_probe)

    payload = await host._status_payload()

    assert payload["equipment_status"] == "degraded"
    assert payload["components"]["poe_api"]["state"] == "not_configured"


@pytest.mark.asyncio
async def test_recent_chat_failure_is_reported_without_probing(monkeypatch):
    """A real failed chat is evidence enough — no extra API call needed."""
    registry = HealthRegistry()
    registry.for_provider(POE).record_exception(Exception(SUBSCRIPTION_PAYLOAD))

    host = _status_host(monkeypatch, registry=registry)

    async def _no_probe(*args, **kwargs):
        raise AssertionError("probe should not have been called")

    monkeypatch.setattr(appmod, "probe_provider", _no_probe)

    payload = await host._status_payload()

    assert payload["equipment_status"] == "degraded"
    assert payload["components"]["poe_api"]["state"] == "poe_subscription_required"


def _fake_roster(monkeypatch, roster, default):
    """Install a roster + a provider_for consistent with it."""
    lookup = {model: name for name, models in roster.items() for model in models}
    monkeypatch.setattr(appmod, "models_by_provider", lambda: roster)
    monkeypatch.setattr(appmod, "provider_for", lambda m: lookup.get(m, POE))
    monkeypatch.setattr(appmod, "DEFAULT_CHAT_MODEL", default)


@pytest.mark.asyncio
@pytest.mark.parametrize("default", ["Claude-Opus-4.8", "z-ai/glm-5.2"])
async def test_probe_targets_a_model_the_provider_actually_owns(monkeypatch, default):
    """Probing OpenRouter with a Poe model name would fail for the wrong reason.

    Parametrised over which provider owns the default model, because the
    default is configuration — it is currently an OpenRouter model, and each
    provider must still be probed with something it actually serves.
    """
    host = _status_host(monkeypatch, openrouter_key="sk-or-key")
    _fake_roster(
        monkeypatch,
        {POE: ["Claude-Opus-4.8", "GLM-5.2"], OPENROUTER: ["z-ai/glm-5.2"]},
        default,
    )
    probe = _probe_returning({POE: (True, None, None), OPENROUTER: (True, None, None)})
    monkeypatch.setattr(appmod, "probe_provider", probe)
    monkeypatch.setattr(appmod, "fetch_credits", _no_credits)

    await host._status_payload()

    targets = dict(probe.seen)
    assert targets[POE] in ("Claude-Opus-4.8", "GLM-5.2")
    assert targets[OPENROUTER] == "z-ai/glm-5.2"
    # The default's own provider is probed with the default itself.
    assert targets[appmod.provider_for(default)] == default
