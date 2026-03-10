"""
Structured logging configuration for the Fronte Meridionale Transak backend.

Provides a pre-configured logger that differentiates between INFO, WARNING,
ERROR and DEBUG levels with a consistent format for production debugging.
"""

import logging
import sys

from backend.config import DEBUG

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))

logger = logging.getLogger("transak_gateway")
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)
logger.addHandler(_handler)
logger.propagate = False
