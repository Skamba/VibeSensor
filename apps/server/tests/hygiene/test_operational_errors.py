"""Test the operational exception hierarchy."""

from __future__ import annotations

import pytest

from vibesensor.shared.exceptions import VibeSensorError
from vibesensor.shared.operational_errors import (
    ExternalCommandError,
    OperationalError,
    ServiceUnavailableError,
)

_ALL_OPERATIONAL_EXCEPTIONS = (
    ServiceUnavailableError,
    ExternalCommandError,
)


def test_operational_base_exception_is_exception() -> None:
    assert issubclass(OperationalError, Exception)
    assert str(OperationalError("test")) == "test"


@pytest.mark.parametrize("exc_cls", _ALL_OPERATIONAL_EXCEPTIONS, ids=lambda cls: cls.__name__)
def test_operational_errors_catchable_by_base(exc_cls: type[OperationalError]) -> None:
    with pytest.raises(OperationalError) as exc_info:
        raise exc_cls("test")

    assert str(exc_info.value) == "test"


def test_operational_error_base_is_direct_exception_subclass() -> None:
    assert OperationalError.__bases__ == (Exception,)


def test_service_unavailable_error_uses_operational_base() -> None:
    assert ServiceUnavailableError.__bases__ == (OperationalError,)


def test_external_command_error_uses_service_unavailable_base() -> None:
    assert ExternalCommandError.__bases__ == (ServiceUnavailableError,)


@pytest.mark.parametrize("exc_cls", _ALL_OPERATIONAL_EXCEPTIONS, ids=lambda cls: cls.__name__)
def test_operational_errors_are_not_domain_errors(exc_cls: type[OperationalError]) -> None:
    assert not issubclass(exc_cls, VibeSensorError)
    assert not isinstance(exc_cls("test"), VibeSensorError)
