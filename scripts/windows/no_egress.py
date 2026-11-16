"""Run a Python module with outbound network blocked (loopback only) and count any attempts.

    python scripts\\windows\\no_egress.py -m crawler.jobs.run_crawler --source-id jobkorea ...

Every socket connect to a non-loopback address raises ``OSError`` and is counted; DNS lookups of
non-local names are refused too. At exit one line ``EGRESS_ATTEMPTS=<n>`` is written to stderr and,
if ``AICP_EGRESS_LOG`` is set, appended as JSON to that file. libpq connections (psycopg) are made
inside the C library to 127.0.0.1 and are unaffected. Used as evidence that fixture/offline runs make
zero external requests; it complements, not replaces, the crawler's own T61/LIVE gates.
"""
import atexit
import ipaddress
import json
import os
import runpy
import socket
import sys

_attempts = []
_LOCAL_NAMES = {'localhost', 'db', ''}
_real_connect, _real_connect_ex, _real_getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo


def _is_local(host):
    if isinstance(host, bytes):
        host = host.decode()
    if host in _LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split('%')[0]).is_loopback
    except ValueError:
        return False


def _check(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(address[0]):
        _attempts.append(str(address[0]))
        raise OSError(f'AICP no_egress: blocked outbound connection to {address[0]}')


def _connect(self, address):
    _check(self, address)
    return _real_connect(self, address)


def _connect_ex(self, address):
    _check(self, address)
    return _real_connect_ex(self, address)


def _getaddrinfo(host, *args, **kwargs):
    if host is not None and not _is_local(host):
        _attempts.append(str(host))
        raise socket.gaierror(f'AICP no_egress: blocked DNS lookup for {host}')
    return _real_getaddrinfo(host, *args, **kwargs)


socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = _connect, _connect_ex, _getaddrinfo


@atexit.register
def _report():
    print(f'EGRESS_ATTEMPTS={len(_attempts)}', file=sys.stderr)
    log = os.environ.get('AICP_EGRESS_LOG')
    if log:
        with open(log, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps({'argv': sys.argv[1:], 'attempts': len(_attempts), 'targets': sorted(set(_attempts))}) + '\n')


if __name__ == '__main__':
    if len(sys.argv) < 3 or sys.argv[1] != '-m':
        raise SystemExit('usage: no_egress.py -m <module> [args...]')
    module = sys.argv[2]
    sys.argv = [module] + sys.argv[3:]
    sys.path.insert(0, os.getcwd())
    runpy.run_module(module, run_name='__main__', alter_sys=True)
