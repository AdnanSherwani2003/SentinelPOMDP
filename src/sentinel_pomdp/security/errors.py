"""Stable, non-enumerating errors for the public security boundary."""


class SecurityBoundaryError(RuntimeError):
    """Base error carrying a machine-readable reason without sensitive context."""

    code = "SECURITY_DENIED"


class AuthenticationError(SecurityBoundaryError):
    code = "AUTHENTICATION_FAILED"


class AuthorizationError(SecurityBoundaryError):
    code = "ACCESS_DENIED"


class PrivacyPolicyError(SecurityBoundaryError):
    code = "EXTERNAL_PROCESSING_DENIED"


class ResourceLimitError(SecurityBoundaryError):
    code = "RESOURCE_LIMIT_EXCEEDED"
