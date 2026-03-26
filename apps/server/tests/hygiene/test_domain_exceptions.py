"""Test VibeSensor domain exception hierarchy."""

from __future__ import annotations

import pytest

from vibesensor.shared.exceptions import (
    AnalysisNotReadyError,
    ConfigurationError,
    DataCorruptError,
    PersistenceError,
    ProcessingError,
    ProtocolError,
    RunNotFoundError,
    UpdateError,
    VibeSensorError,
)

_ALL_DOMAIN_EXCEPTIONS = (
    ConfigurationError,
    DataCorruptError,
    PersistenceError,
    ProcessingError,
    ProtocolError,
    RunNotFoundError,
    UpdateError,
    AnalysisNotReadyError,
)


def test_base_exception_is_exception() -> None:
    assert issubclass(VibeSensorError, Exception)


@pytest.mark.parametrize("exc_cls", _ALL_DOMAIN_EXCEPTIONS, ids=lambda cls: cls.__name__)
def test_domain_errors_catchable_by_base(exc_cls: type[VibeSensorError]) -> None:
    """All domain exceptions should be catchable with VibeSensorError."""
    try:
        raise exc_cls("test")
    except VibeSensorError:
        pass  # expected
    else:
        raise AssertionError(f"{exc_cls.__name__} not catchable as VibeSensorError")


@pytest.mark.parametrize("exc_cls", _ALL_DOMAIN_EXCEPTIONS, ids=lambda cls: cls.__name__)
def test_all_domain_exceptions_single_base(exc_cls: type[VibeSensorError]) -> None:
    """Every domain exception inherits exclusively from VibeSensorError."""
    assert VibeSensorError.__bases__ == (Exception,)
    assert exc_cls.__bases__ == (VibeSensorError,), (
        f"{exc_cls.__name__}.__bases__ = {exc_cls.__bases__}, expected (VibeSensorError,)"
    )


@pytest.mark.parametrize("exc_cls", _ALL_DOMAIN_EXCEPTIONS, ids=lambda cls: cls.__name__)
def test_no_stdlib_exception_inheritance(exc_cls: type[VibeSensorError]) -> None:
    """No domain exception is a subclass of ValueError, RuntimeError, or LookupError."""
    stdlib_bases = (ValueError, RuntimeError, LookupError)
    for stdlib in stdlib_bases:
        assert not issubclass(exc_cls, stdlib), (
            f"{exc_cls.__name__} should not be a subclass of {stdlib.__name__}"
        )


def test_configuration_error_caught_by_vibesensor_error() -> None:
    """ConfigurationError is catchable via except VibeSensorError."""
    with_catch = False
    try:
        raise ConfigurationError("bad")
    except VibeSensorError:
        with_catch = True
    assert with_catch
