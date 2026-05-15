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

_DIRECT_DOMAIN_EXCEPTIONS = (
    ConfigurationError,
    DataCorruptError,
    PersistenceError,
    ProcessingError,
    ProtocolError,
    RunNotFoundError,
    UpdateError,
    AnalysisNotReadyError,
)


def _all_domain_exception_classes() -> tuple[type[VibeSensorError], ...]:
    classes: list[type[VibeSensorError]] = []

    def collect(cls: type[VibeSensorError]) -> None:
        for subclass in sorted(cls.__subclasses__(), key=lambda item: item.__name__):
            classes.append(subclass)
            collect(subclass)

    collect(VibeSensorError)
    return tuple(classes)


_ALL_DOMAIN_EXCEPTIONS = _all_domain_exception_classes()


def test_base_exception_is_exception() -> None:
    assert issubclass(VibeSensorError, Exception)
    assert VibeSensorError.__bases__ == (Exception,)


@pytest.mark.parametrize("exc_cls", _DIRECT_DOMAIN_EXCEPTIONS, ids=lambda cls: cls.__name__)
def test_domain_errors_catchable_by_base_preserve_message(
    exc_cls: type[VibeSensorError],
) -> None:
    """Every top-level domain exception is catchable through VibeSensorError."""
    with pytest.raises(VibeSensorError, match=f"{exc_cls.__name__} message"):
        raise exc_cls(f"{exc_cls.__name__} message")


@pytest.mark.parametrize("exc_cls", _DIRECT_DOMAIN_EXCEPTIONS, ids=lambda cls: cls.__name__)
def test_all_domain_exceptions_single_base(exc_cls: type[VibeSensorError]) -> None:
    """Top-level domain exceptions inherit directly from VibeSensorError."""
    assert exc_cls.__bases__ == (VibeSensorError,), (
        f"{exc_cls.__name__}.__bases__ = {exc_cls.__bases__}, expected (VibeSensorError,)"
    )


@pytest.mark.parametrize("exc_cls", _ALL_DOMAIN_EXCEPTIONS, ids=lambda cls: cls.__name__)
def test_domain_exception_hierarchy_has_no_stdlib_compat_bases(
    exc_cls: type[VibeSensorError],
) -> None:
    """Concrete exceptions may specialize another domain error, but no stdlib class."""
    assert len(exc_cls.__bases__) == 1
    assert issubclass(exc_cls.__bases__[0], VibeSensorError)

    stdlib_mro_entries = [
        cls.__name__
        for cls in exc_cls.__mro__[1:]
        if cls not in (VibeSensorError, Exception, BaseException, object)
        and cls.__module__ == "builtins"
    ]
    assert not stdlib_mro_entries, (
        f"{exc_cls.__name__} should not inherit from stdlib exception bases: {stdlib_mro_entries}"
    )


def test_configuration_error_is_in_recursive_exception_inventory() -> None:
    assert ConfigurationError in _ALL_DOMAIN_EXCEPTIONS
    with pytest.raises(VibeSensorError, match="bad config"):
        raise ConfigurationError("bad config")
