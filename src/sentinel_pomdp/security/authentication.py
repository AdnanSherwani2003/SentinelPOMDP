"""Opaque local API-key authentication for demos and future HTTP adapters."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from threading import RLock
from typing import Protocol

from .errors import AuthenticationError
from .models import APIKeyRecord, AuthenticatedPrincipal


class Authenticator(Protocol):
    def authenticate(self, credential: str) -> AuthenticatedPrincipal: ...


def _verifier(credential: str, salt: bytes) -> bytes:
    # API keys are generated with 256 bits of entropy; salted SHA-256 is an
    # appropriate one-way verifier for high-entropy, non-user-chosen secrets.
    return hashlib.sha256(salt + credential.encode("utf-8")).digest()


class LocalAPIKeyAuthenticator:
    """Process-local credential store. Persist records in a real secret store in production."""

    def __init__(self, records: list[APIKeyRecord] | None = None) -> None:
        self._records = {record.key_id: record for record in records or []}
        self._lock = RLock()

    def issue(self, principal: AuthenticatedPrincipal, *, expires_at: datetime | None = None) -> tuple[str, str]:
        if not principal.principal_id or not principal.tenant_id:
            raise ValueError("principal and tenant identifiers are required")
        credential = secrets.token_urlsafe(32)
        key_id = secrets.token_hex(12)
        salt = secrets.token_bytes(16)
        with self._lock:
            self._records[key_id] = APIKeyRecord(
                key_id=key_id, verifier=_verifier(credential, salt), salt=salt,
                principal=principal, created_at=datetime.now(timezone.utc), expires_at=expires_at,
            )
        return key_id, credential

    def register(self, credential: str, principal: AuthenticatedPrincipal, *,
                 expires_at: datetime | None = None) -> str:
        """Register a pre-provisioned high-entropy secret without retaining plaintext."""
        if len(credential) < 32 or len(credential) > 512:
            raise ValueError("configured API key must contain 32-512 characters")
        if not principal.principal_id or not principal.tenant_id:
            raise ValueError("principal and tenant identifiers are required")
        key_id = secrets.token_hex(12)
        salt = secrets.token_bytes(16)
        with self._lock:
            self._records[key_id] = APIKeyRecord(
                key_id=key_id, verifier=_verifier(credential, salt), salt=salt,
                principal=principal, created_at=datetime.now(timezone.utc), expires_at=expires_at,
            )
        return key_id

    def authenticate(self, credential: str) -> AuthenticatedPrincipal:
        if not credential or len(credential) > 512:
            raise AuthenticationError("Authentication failed")
        matched: APIKeyRecord | None = None
        # Scan all bounded local records so a caller cannot use lookup behavior
        # to distinguish valid identifiers. Always compare every verifier.
        with self._lock:
            records = tuple(self._records.values())
        for record in records:
            if hmac.compare_digest(record.verifier, _verifier(credential, record.salt)):
                matched = record
        if matched is None or not matched.active or not matched.principal.active:
            raise AuthenticationError("Authentication failed")
        return matched.principal

    def revoke(self, key_id: str) -> None:
        with self._lock:
            record = self._records.get(key_id)
            if record is not None:
                record.revoked_at = datetime.now(timezone.utc)

    def replace(self, key_id: str) -> tuple[str, str]:
        """Revoke one active key and return a newly issued credential once."""
        with self._lock:
            record = self._records.get(key_id)
            if record is None or not record.active:
                raise AuthenticationError("Authentication failed")
            self.revoke(key_id)
            return self.issue(record.principal, expires_at=record.expires_at)

    def stored_record(self, key_id: str) -> APIKeyRecord | None:
        """Administrative/test inspection; never returns the original credential."""
        with self._lock:
            return self._records.get(key_id)


class ExplicitDevelopmentAuthenticator:
    """Credential-free development mode that must be deliberately constructed."""

    def __init__(self, principal: AuthenticatedPrincipal, *, enabled: bool = False) -> None:
        if not enabled:
            raise ValueError("development authentication requires an explicit enabled=True")
        self.principal = principal

    def authenticate(self, credential: str) -> AuthenticatedPrincipal:
        if credential:
            raise AuthenticationError("Authentication failed")
        if not self.principal.active:
            raise AuthenticationError("Authentication failed")
        return self.principal
