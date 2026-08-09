"""Observed health of each model provider, for PyPoe's ``/status`` envelope.

Why this exists: PyPoe's primary operation is talking to models. Before this
module, ``/status`` "probed" Poe by calling
:meth:`PoeChatClient.get_available_bots`, which returns a **hardcoded local
list** and never touches the network — so the ``poe_api`` component reported
``connected`` whenever ``POE_API_KEY`` was merely *set*. A lapsed Poe
subscription (every chat call failing with ``subscription_required``) was
invisible to the dashboard, which kept rendering the tile ``ready``. That
violates STATUS_SPEC §2.2: the top-level state must not claim ``ready`` while
a known fault blocks the equipment's normal primary operation.

Health is tracked **per provider** (:mod:`pypoe.core.providers`), because with
per-model routing one provider can be dead while another serves fine — which
is exactly the situation that motivated adding OpenRouter. The envelope
therefore carries one component per configured provider, and the service is
only fully ``ready`` when at least one provider can actually answer.

Two signal sources, deliberately combined:

* **Passive** — every real chat call records its outcome here. Free, and it
  reflects exactly what users experience.
* **Active** — :func:`probe_provider` issues a ``max_tokens=1`` request when
  passive evidence has gone stale (e.g. nobody has chatted since the last
  restart). Note the asymmetry that makes this cheap: a *failing* probe is
  rejected before inference and costs nothing, so a broken provider can be
  re-checked often, while a healthy one is only re-probed rarely.

Failure *reasons* are a stable set (per STATUS_SPEC best practice #6) and the
wire ``code`` is ``"{provider}_{reason}"`` — e.g. ``poe_subscription_required``,
``openrouter_auth_failed`` — so a reader can branch on the code and tell both
*what* broke and *whose* it was.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from .providers import PROVIDERS, ProviderSpec, get_provider

logger = logging.getLogger(__name__)

#: Stable failure reasons. Combined with a provider name to form the wire code.
FAILURE_REASONS = frozenset(
    {
        "subscription_required",   # account lacks the entitlement to call the API
        "insufficient_credits",    # entitled, but out of points/credits/quota
        "auth_failed",             # key rejected / revoked / absent
        "rate_limited",            # throttled
        "model_unavailable",       # this model is private, deprecated, missing
        "unreachable",             # transport failure
        "api_error",               # anything else the provider reported
    }
)

#: Reasons meaning "this provider cannot serve *any* request" — as opposed to a
#: failure specific to one model or one moment. Only these justify calling the
#: provider down; a bad model name or a transient 429 does not.
ACCOUNT_BLOCKING_REASONS = frozenset(
    {"subscription_required", "insufficient_credits", "auth_failed"}
)

#: Reasons that say nothing about the provider's health and must never be
#: recorded against it.
MODEL_SCOPED_REASONS = frozenset({"model_unavailable"})


def code_for(provider: str, reason: str) -> str:
    """The wire ``last_error.code`` for a provider/reason pair."""
    return f"{provider}_{reason}"


def split_code(code: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Inverse of :func:`code_for` — ``(provider, reason)``."""
    if not code:
        return None, None
    for name in PROVIDERS:
        prefix = f"{name}_"
        if code.startswith(prefix):
            return name, code[len(prefix) :]
    return None, code


def recovery_hint(provider: str, reason: Optional[str]) -> Optional[str]:
    """Operator-facing next step, phrased for the provider that failed."""
    spec = get_provider(provider)
    if reason == "subscription_required":
        upgrade = (
            "https://poe.com/subscription_plans"
            if spec.name == "poe"
            else spec.signup_url
        )
        return f"{spec.label} API access requires an active subscription — renew it at {upgrade}"
    if reason == "insufficient_credits":
        return (
            f"{spec.label} credits exhausted — top up at {spec.signup_url}"
            if spec.metered
            else f"{spec.label} quota exhausted — wait for it to reset or upgrade the plan"
        )
    if reason == "auth_failed":
        return f"{spec.api_key_env} was rejected — reissue it at {spec.signup_url}"
    if reason == "rate_limited":
        return f"Rate limited by {spec.label} — retry shortly"
    if reason == "model_unavailable":
        return f"That model is unavailable on {spec.label} — pick another"
    if reason == "unreachable":
        return f"Could not reach {spec.base_url} — check network/DNS"
    if reason == "api_error":
        return f"{spec.label} returned an error"
    return None


def _classify_payload(error_type: str, text: str) -> str:
    """Map a provider's ``error_type``/message onto :data:`FAILURE_REASONS`."""
    etype = (error_type or "").strip().lower()
    lowered = (text or "").lower()

    if etype == "subscription_required" or "requires an active poe subscription" in lowered:
        return "subscription_required"
    if etype in {"insufficient_fund", "insufficient_funds", "insufficient_quota", "quota_exceeded"}:
        return "insufficient_credits"
    if etype in {"invalid_api_key", "unauthorized", "authentication_error", "invalid_request_error"}:
        return "auth_failed"
    if etype in {"rate_limit", "rate_limit_exceeded", "too_many_requests"}:
        return "rate_limited"
    if etype in {"bot_not_found", "invalid_bot", "model_not_found", "not_found_error"}:
        return "model_unavailable"

    # Fall back to message text for older/undocumented shapes.
    if "insufficient" in lowered or "quota" in lowered or "out of credit" in lowered:
        return "insufficient_credits"
    if (
        "invalid api key" in lowered
        or "unauthorized" in lowered
        or "user not found" in lowered
        or "no auth" in lowered
        or ("api key" in lowered and "invalid" in lowered)
    ):
        return "auth_failed"
    if "rate limit" in lowered or "too many requests" in lowered:
        return "rate_limited"
    if "cannot access private bots" in lowered or "bot does not exist" in lowered:
        return "model_unavailable"
    if "not a valid model" in lowered or "no endpoints found" in lowered:
        return "model_unavailable"
    return "api_error"


def _unwrap(payload: Any) -> Tuple[str, Optional[str]]:
    """Pull ``(error_type, message)`` out of a provider's JSON error body.

    Handles both shapes in play: ``fastapi_poe``'s flat
    ``{"text", "error_type"}`` and the OpenAI-compatible
    ``{"error": {"message", "type"|"code"}}``.
    """
    if not isinstance(payload, dict):
        return "", None

    nested = payload.get("error")
    if isinstance(nested, dict):
        # OpenRouter puts an *integer* HTTP status in "code" (e.g. 401), which
        # is not a type name — treat only non-numeric strings as a type, or
        # every OpenRouter error would classify as an unrecognised type and
        # skip the status-code fallback.
        raw_type = nested.get("type")
        if not isinstance(raw_type, str) or not raw_type:
            raw_code = nested.get("code")
            raw_type = raw_code if isinstance(raw_code, str) else ""
        return str(raw_type or ""), _as_text(nested.get("message"))

    return str(payload.get("error_type") or ""), _as_text(
        payload.get("text") or payload.get("message")
    )


def _as_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value)


def classify_error_body(
    payload: Any, status_code: Optional[int] = None, fallback: str = ""
) -> Tuple[str, str]:
    """Classify a decoded error body into ``(reason, message)``."""
    if isinstance(payload, dict) and "__transport_error__" in payload:
        return "unreachable", str(payload["__transport_error__"])

    error_type, message = _unwrap(payload)
    text = message or fallback or (json.dumps(payload) if payload is not None else "")

    reason = _classify_payload(error_type, text)
    if reason == "api_error" and status_code is not None:
        # Trust the HTTP status when the body carried no usable type.
        if status_code in (401, 403):
            reason = "auth_failed"
        elif status_code == 402:
            reason = "subscription_required"
        elif status_code == 404:
            # A model the provider doesn't serve. Model-scoped on purpose: a
            # typo'd model name must not mark the whole provider unhealthy.
            reason = "model_unavailable"
        elif status_code == 429:
            reason = "rate_limited"

    if not text and status_code is not None:
        text = f"HTTP {status_code}"
    return reason, text


def classify_exception(exc: BaseException) -> Tuple[str, str]:
    """Classify an exception raised by a chat call into ``(reason, message)``.

    ``fastapi_poe`` raises ``BotError`` / ``BotErrorNoRetry`` whose ``str()`` is
    the raw JSON body, e.g.::

        {"text": "The model X requires an active Poe subscription for API
         access.", "allow_retry": false, "error_type": "subscription_required"}

    so the structured ``error_type`` is recovered by parsing rather than by
    matching prose. :class:`pypoe.core.providers.ProviderError` is built to
    stringify the same way, which is why both providers share this path.
    """
    raw = str(exc)
    status_code = getattr(exc, "status_code", None)

    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        payload = None

    if payload is None:
        if _looks_like_transport_error(exc):
            return "unreachable", raw or exc.__class__.__name__
        return _classify_payload("", raw), raw or exc.__class__.__name__

    return classify_error_body(payload, status_code=status_code, fallback=raw)


def _looks_like_transport_error(exc: BaseException) -> bool:
    name = exc.__class__.__name__.lower()
    if isinstance(exc, (OSError, TimeoutError)):
        return True
    return any(token in name for token in ("connect", "timeout", "network", "dns", "ssl"))


@dataclass
class ProviderHealthState:
    """Last observed outcome of a real call to one provider."""

    provider: str = "poe"
    state: str = "unknown"           # unknown | ok | not_configured | <reason>
    reason: Optional[str] = None
    message: Optional[str] = None
    source: Optional[str] = None     # "chat" (passive) | "probe" (active)
    observed_at: Optional[datetime] = None
    monotonic_at: Optional[float] = None
    credits: Optional[Dict[str, float]] = None

    @property
    def ok(self) -> bool:
        return self.state == "ok"

    @property
    def code(self) -> Optional[str]:
        """Wire ``last_error.code``, or ``None`` when healthy/unverified."""
        if self.reason is None:
            return None
        return code_for(self.provider, self.reason)

    @property
    def age_s(self) -> Optional[float]:
        if self.monotonic_at is None:
            return None
        return round(time.monotonic() - self.monotonic_at, 1)


class ProviderHealthTracker:
    """Most recent outcome for a single provider.

    Every mutation replaces the whole state object, so readers never observe a
    half-updated record without needing a lock.
    """

    #: Re-probe interval once a healthy call has been observed. Long, because a
    #: successful probe costs money on a metered provider; passive chat traffic
    #: refreshes it for free in the meantime.
    HEALTHY_PROBE_INTERVAL_S = 900.0
    #: Re-probe interval while the last outcome was a failure. Short, because a
    #: failing probe is rejected before inference and costs nothing — so
    #: recovery is noticed promptly.
    UNHEALTHY_PROBE_INTERVAL_S = 60.0

    def __init__(self, provider: str = "poe") -> None:
        self.provider = provider
        self._state = ProviderHealthState(provider=provider)

    def snapshot(self) -> ProviderHealthState:
        return self._state

    def _set(self, **kwargs: Any) -> None:
        self._state = ProviderHealthState(
            provider=self.provider,
            observed_at=datetime.now(timezone.utc),
            monotonic_at=time.monotonic(),
            credits=self._state.credits,
            **kwargs,
        )

    def record_success(self, source: str = "chat") -> None:
        self._set(state="ok", source=source)

    def record_failure(self, reason: str, message: str, source: str = "chat") -> None:
        self._set(state=reason, reason=reason, message=message, source=source)

    def record_exception(self, exc: BaseException, source: str = "chat") -> Tuple[str, str]:
        """Classify and record ``exc``; returns the ``(reason, message)`` used."""
        reason, message = classify_exception(exc)
        self.record_failure(reason, message, source=source)
        return reason, message

    def record_not_configured(self) -> None:
        spec = get_provider(self.provider)
        self._set(
            state="not_configured",
            message=f"{spec.api_key_env} is not configured",
        )

    def record_credits(self, credits: Optional[Dict[str, float]]) -> None:
        """Attach a balance reading without disturbing the freshness clock."""
        self._state.credits = credits

    def needs_probe(self) -> bool:
        """True when passive evidence is stale enough to warrant an API call."""
        state = self._state
        if state.monotonic_at is None:
            return True
        interval = (
            self.HEALTHY_PROBE_INTERVAL_S if state.ok else self.UNHEALTHY_PROBE_INTERVAL_S
        )
        return (time.monotonic() - state.monotonic_at) >= interval


class HealthRegistry:
    """One tracker per provider, created on demand."""

    def __init__(self) -> None:
        self._trackers: Dict[str, ProviderHealthTracker] = {}

    def for_provider(self, provider: str) -> ProviderHealthTracker:
        tracker = self._trackers.get(provider)
        if tracker is None:
            tracker = ProviderHealthTracker(provider)
            self._trackers[provider] = tracker
        return tracker

    def snapshots(self) -> Dict[str, ProviderHealthState]:
        return {name: t.snapshot() for name, t in self._trackers.items()}

    def reset(self) -> None:
        """Drop all state (tests)."""
        self._trackers.clear()


#: The process-wide registry. Chat paths write to it; ``/status`` reads it.
registry = HealthRegistry()


async def probe_provider(
    spec: ProviderSpec, api_key: str, model: str, **kwargs: Any
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Actively check one provider. Returns ``(ok, reason, message)``."""
    from .providers import probe as _probe

    ok, status_code, body = await _probe(spec, api_key=api_key, model=model, **kwargs)
    if ok:
        return True, None, None
    reason, message = classify_error_body(body, status_code=status_code)
    return False, reason, message


def component_for(
    state: ProviderHealthState, *, low_credit_threshold: float = 0.0
) -> Dict[str, Any]:
    """Render a state as STATUS_SPEC ``ComponentStatus`` bits.

    Returns ``{"connected", "state", "message"}``. ``unknown`` reports
    ``connected: False`` deliberately — see STATUS_SPEC §2.1: an undetermined
    state is not evidence of health, so the caller treats it as a non-``ready``
    input rather than letting it pass silently.
    """
    spec = get_provider(state.provider)

    if state.state == "not_configured":
        return {
            "connected": False,
            "state": "not_configured",
            "message": state.message or f"{spec.api_key_env} is not configured",
        }
    if state.state == "unknown":
        return {
            "connected": False,
            "state": "unknown",
            "message": f"{spec.label} API access has not been verified yet",
        }
    if state.ok:
        remaining = (state.credits or {}).get("remaining")
        if remaining is not None and low_credit_threshold > 0 and remaining < low_credit_threshold:
            # Reachable but nearly out of money: the request that matters will
            # fail soon, so say so before it does rather than after.
            return {
                "connected": False,
                "state": f"{spec.name}_insufficient_credits",
                "message": (
                    f"{spec.label} balance ${remaining:.2f} is below the "
                    f"${low_credit_threshold:.2f} threshold — top up at {spec.signup_url}"
                ),
            }
        return {"connected": True, "state": "connected", "message": None}

    hint = recovery_hint(state.provider, state.reason)
    message = state.message or state.reason or f"{spec.label} error"
    if hint:
        message = f"{message} — {hint}"
    return {
        # Provider-qualified so the tile distinguishes "Poe unsubscribed" from
        # "OpenRouter key rejected" at a glance.
        "connected": False,
        "state": state.code or "error",
        "message": message,
    }
