"""Login for the Settings area (/admin). The kids' page, clips and pictures stay public.

* Password: UNSUB_ADMIN_PASSWORD (stack .env). If it isn't set, nobody can log in (the Settings area stays
  locked) unless UNSUB_AUTH=off, which tests use.
* Session: a signed cookie (HMAC-SHA256 with a random secret kept in the data folder), valid 30 days.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from .config import env

COOKIE = "wbs_session"
MAX_AGE = 30 * 86400

# Public: the kids' page and what it needs. Everything else under /admin and /api is protected.
PUBLIC_PREFIXES = ("/static/", "/img/", "/clips/", "/api/public/", "/login", "/logout", "/favicon")
PUBLIC_EXACT = {"/", "/gallery", "/collection"}


class Auth:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._secret: bytes | None = None

    @property
    def enabled(self) -> bool:
        return env("UNSUB_AUTH", "on").lower() not in ("off", "0", "false", "no")

    @property
    def password(self) -> str:
        return env("UNSUB_ADMIN_PASSWORD")

    def secret(self) -> bytes:
        if self._secret is None:
            p = self.data_dir / "session_secret"
            try:
                self._secret = p.read_bytes()
            except FileNotFoundError:
                p.parent.mkdir(parents=True, exist_ok=True)
                self._secret = secrets.token_bytes(32)
                p.write_bytes(self._secret)
                os.chmod(p, 0o600)
        return self._secret

    def check_password(self, given: str) -> bool:
        return bool(self.password) and hmac.compare_digest(given.encode(), self.password.encode())

    def make_cookie(self, now: float | None = None) -> str:
        exp = int((now or time.time()) + MAX_AGE)
        msg = f"admin|{exp}".encode()
        sig = hmac.new(self.secret(), msg, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(msg + b"|" + sig).decode()

    def valid(self, cookie: str | None, now: float | None = None) -> bool:
        if not cookie:
            return False
        try:
            raw = base64.urlsafe_b64decode(cookie.encode())
            user, exp, sig = raw.split(b"|", 2)
            msg = user + b"|" + exp
            good = hmac.compare_digest(sig, hmac.new(self.secret(), msg, hashlib.sha256).digest())
            return good and user == b"admin" and int(exp) > (now or time.time())
        except (ValueError, TypeError):
            return False

    def is_public(self, path: str) -> bool:
        return path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES)
