"""Explicit same-origin access for local use and a configured website proxy."""
from __future__ import annotations

import re
from urllib.parse import urlsplit


def normalize_origin(value: str, *, config: bool = False) -> str:
    """Canonicalize an HTTP origin; reject paths, credentials and wildcards."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (not value or re.search(r'\s', value) or parsed.scheme not in ('http', 'https')
                or not parsed.hostname or not re.fullmatch(r'[a-zA-Z0-9.-]+', parsed.hostname)
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or '?' in value or '#' in value
                or parsed.path not in (('', '/') if config else ('',))
                or (port is not None and not 1 <= port <= 65535)):
            raise ValueError
        host = parsed.hostname.lower()
        suffix = '' if port is None or port == {'http': 80, 'https': 443}[parsed.scheme] else f':{port}'
        return f'{parsed.scheme}://{host}{suffix}'
    except (ValueError, TypeError):
        raise ValueError('COMMENTARY_PUBLIC_ORIGINS 需要完整 http/https 来源，不含路径、凭据或通配符。') from None


def allows_request(host: str, origin: str | None, local_port: int, public_origins: tuple[str, ...]) -> bool:
    """Accept a local request or allowlisted proxy origin, ignoring forwarding headers."""
    host = host.lower()
    local = host in {f'127.0.0.1:{local_port}', f'localhost:{local_port}'}
    try:
        if origin is None:
            return local or any(normalize_origin(f'{urlsplit(o).scheme}://{host}') == o for o in public_origins)
        normalized = normalize_origin(origin)
        if local:
            return normalized in public_origins or normalized in {
                normalize_origin(f'http://{host}'), normalize_origin(f'https://{host}')}
        return normalized in public_origins and normalize_origin(f'{urlsplit(normalized).scheme}://{host}') == normalized
    except ValueError:
        return False
