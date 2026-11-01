import hashlib
import secrets

from fastapi import Depends, Header, HTTPException, Request

from .db import q


def hash_key(key):
    return hashlib.sha256(key.encode()).hexdigest()


def generate_raw_key():
    return "ev_" + secrets.token_urlsafe(32)


def create_key(name, admin=False):
    raw = generate_raw_key()
    q("INSERT INTO api_keys(name, key_hash, is_admin) VALUES (%s, %s, %s)",
      (name, hash_key(raw), admin))
    return raw


def audit(key_id, action, detail, request=None):
    ip = request.client.host if request is not None and request.client else None
    q("INSERT INTO audit_log(key_id, action, detail, client_ip) VALUES (%s, %s, %s, %s)",
      (key_id, action, (detail or "")[:500], ip))


def require_key(request: Request, x_api_key: str | None = Header(default=None)):
    if not x_api_key:
        audit(None, "auth_failed", "missing key", request)
        raise HTTPException(401, "Missing X-API-Key header")
    row = q("SELECT id, name, is_admin FROM api_keys WHERE key_hash = %s AND active",
            (hash_key(x_api_key),), one=True)
    if not row:
        audit(None, "auth_failed", "invalid key", request)
        raise HTTPException(401, "Invalid API key")
    return row


def require_admin(key=Depends(require_key)):
    if not key["is_admin"]:
        raise HTTPException(403, "Admin key required")
    return key
