"""Deterministic default-deny authorization."""
from __future__ import annotations

from .errors import AuthorizationError
from .models import AuthenticatedPrincipal, Permission


class Authorizer:
    def require(self, principal: AuthenticatedPrincipal, permission: Permission, *,
                tenant_id: str | None = None) -> None:
        if not principal.active:
            raise AuthorizationError("Resource unavailable or access denied")
        if Permission.ADMIN not in principal.permissions and permission not in principal.permissions:
            raise AuthorizationError("Resource unavailable or access denied")
        if tenant_id is not None and tenant_id != principal.tenant_id:
            raise AuthorizationError("Resource unavailable or access denied")
