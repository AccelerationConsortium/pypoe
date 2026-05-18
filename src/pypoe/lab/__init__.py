"""PyPoe lab-integration layer.

Read-only + journaling + consultation tools for the AC Organic
Self-driving Lab. Talks to the dashboard aggregator
(``ac-organic-lab/api`` on port 8001 by default) over HTTP only —
this layer never opens ``/control/*`` endpoints on devices. Control
belongs to the ``lab-skills`` SDK, which owns the four-layer
interlock model (see ``ac-organic-lab/docs/INTERLOCKS.md``).

See ``PyPoe/docs/LAB_INTEGRATION.md`` for install / configure / use.
"""

from .http_client import LabClient

__all__ = ["LabClient"]
