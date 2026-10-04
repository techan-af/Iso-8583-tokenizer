class ISO8583Error(ValueError):
    """Base exception for malformed messages and profile mismatches."""


class ProfileError(ISO8583Error):
    """Raised when a profile is missing or internally inconsistent."""


class ParseError(ISO8583Error):
    """Raised when a wire message cannot be parsed under its profile."""
