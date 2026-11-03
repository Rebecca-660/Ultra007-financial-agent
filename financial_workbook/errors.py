"""Errors whose details come from local report parsing, never model providers."""


class ReportSourceError(ValueError):
    """A source-bound report/layout failure that can be explained to the user.

    Only wrap local parser/verification exceptions in this type. Provider,
    transport and model exceptions must retain the generic safe UI message.
    """
