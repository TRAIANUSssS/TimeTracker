"""Shared clock for ETW liveness and frame deadlines, excluding system sleep."""

import ctypes
import time


def unbiased_monotonic():
    """Return elapsed running time, excluding suspended system time when available."""
    value = ctypes.c_ulonglong()
    try:
        if ctypes.windll.kernel32.QueryUnbiasedInterruptTime(ctypes.byref(value)):
            return value.value / 10_000_000
        raise OSError(ctypes.get_last_error(), "QueryUnbiasedInterruptTime")
    except (AttributeError, OSError):
        # Keep the transport usable on older Windows versions and in test doubles.
        return time.monotonic()
