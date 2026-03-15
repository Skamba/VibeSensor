"""Test VibeSensor domain exception hierarchy."""

from __future__ import annotations

from vibesensor.shared.errors import (
    ConfigurationError,
    PersistenceError,
    ProcessingError,
    UpdateError,
    VibeSensorError,
)


def test_base_exception_is_exception() -> None:
    assert issubclass(VibeSensorError, Exception)


def test_configuration_error_inherits_from_value_error() -> None:
    """ConfigurationError should be catchable as ValueError for backward compat."""
    assert issubclass(ConfigurationError, ValueError)
    assert issubclass(ConfigurationError, VibeSensorError)


def test_persistence_error_inherits_from_runtime_error() -> None:
    assert issubclass(PersistenceError, RuntimeError)
    assert issubclass(PersistenceError, VibeSensorError)


def test_processing_error_inherits_from_runtime_error() -> None:
    assert issubclass(ProcessingError, RuntimeError)
    assert issubclass(ProcessingError, VibeSensorError)


def test_update_error_inherits_from_runtime_error() -> None:
    assert issubclass(UpdateError, RuntimeError)
    assert issubclass(UpdateError, VibeSensorError)


def test_domain_errors_catchable_by_base() -> None:
    """All domain exceptions should be catchable with VibeSensorError."""
    for exc_cls in (ConfigurationError, PersistenceError, ProcessingError, UpdateError):
        try:
            raise exc_cls("test")
        except VibeSensorError:
            pass  # expected
        else:
            raise AssertionError(f"{exc_cls.__name__} not catchable as VibeSensorError")


def test_backward_compatible_catches() -> None:
    """Verify that existing except ValueError/RuntimeError patterns still work."""
    try:
        raise ConfigurationError("bad config")
    except ValueError:
        pass

    try:
        raise PersistenceError("db error")
    except RuntimeError:
        pass

    try:
        raise UpdateError("update failed")
    except RuntimeError:
        pass
