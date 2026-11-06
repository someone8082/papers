"""Rejection type shared by the two interfaces.

The contract only requires that invalid input is rejected explicitly, so any
``ValueError`` subclass is accepted by the acceptance harness. Implementations
should raise ``InputError`` for readability.
"""


class InputError(ValueError):
    """Raised when an input violates the documented interface contract."""
