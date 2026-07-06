"""PyPoe lab-integration layer.

Read-only + journaling + consultation tools for the AC Organic
Self-driving Lab. Talks to the lab dashboard (``ac-organic-lab`` web,
port 8000 by default, which proxies ``/api/*`` to the aggregator) over
HTTP only —
this layer never opens ``/control/*`` endpoints on devices. Control
belongs to the ``lab-skills`` SDK, which owns the four-layer
interlock model (see ``ac-organic-lab/docs/INTERLOCKS.md``).

See ``PyPoe/docs/LAB_INTEGRATION.md`` for install / configure / use.
"""

from .http_client import LabClient

__all__ = ["LabClient"]
