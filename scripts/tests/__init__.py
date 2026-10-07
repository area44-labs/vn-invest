"""Test package initialization for VN Invest.

Installs process-wide network guard to prevent unit tests from making live network calls.
"""

import socket


def enforce_network_isolation() -> None:
    """Block socket connections globally during unit test execution."""
    if getattr(socket.socket, "_network_guard_installed", False):
        return

    _real_connect = socket.socket.connect

    def _blocked_connect(self, address):
        host = (
            address[0] if isinstance(address, (tuple, list)) and len(address) > 0 else str(address)
        )
        raise RuntimeError(
            f"Live network access is forbidden during unit test execution! "
            f"Attempted connection to '{host}'. Ensure external data providers and network calls are properly mocked."
        )

    socket.socket.connect = _blocked_connect
    socket.socket._network_guard_installed = True


