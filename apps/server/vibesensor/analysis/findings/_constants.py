"""Shared constants used across the findings subpackage.

All constants are sourced from ``vibesensor.constants`` — the single
source of truth for physical and analysis constants.  This file exists
only to keep local imports short.
"""

from __future__ import annotations

from ...constants import CONFIDENCE_CEILING as CONFIDENCE_CEILING
from ...constants import CONFIDENCE_FLOOR as CONFIDENCE_FLOOR
from ...constants import LIGHT_STRENGTH_MAX_DB as LIGHT_STRENGTH_MAX_DB
from ...constants import NEGLIGIBLE_STRENGTH_MAX_DB as NEGLIGIBLE_STRENGTH_MAX_DB
from ...constants import ORDER_SUPPRESS_PERSISTENT_MIN_CONF as ORDER_SUPPRESS_PERSISTENT_MIN_CONF
from ...constants import SNR_LOG_DIVISOR as SNR_LOG_DIVISOR
