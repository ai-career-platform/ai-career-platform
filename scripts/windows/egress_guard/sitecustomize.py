"""Opt-in process-wide egress guard (also inherited by child Python processes, e.g. the dispatcher's
scheduled_worker). Active only when AICP_NO_EGRESS=1 and this directory is on PYTHONPATH.
See scripts/windows/no_egress.py for the behaviour (non-loopback connect/DNS blocked and counted)."""
import os
import sys

if os.environ.get('AICP_NO_EGRESS') == '1':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import no_egress  # noqa: F401  (installs the socket guard on import)
