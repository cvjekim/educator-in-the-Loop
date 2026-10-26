"""Guard mocked regression suites against accidental external socket calls.

This is not a sandbox and does not constrain subprocesses or untrusted code.
"""
import socket

_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex


def _local(address):
    # UNIX sockets and literal loopback addresses only; no DNS needed.
    return isinstance(address, str) or address[0] in ("127.0.0.1", "::1")


def _guard(method):
    def connect(sock, address):
        if not _local(address):
            raise RuntimeError("External network disabled by regression harness; mock the call")
        return method(sock, address)
    return connect


def pytest_configure(config):
    socket.socket.connect = _guard(_connect)
    socket.socket.connect_ex = _guard(_connect_ex)


def pytest_unconfigure(config):
    socket.socket.connect = _connect
    socket.socket.connect_ex = _connect_ex
