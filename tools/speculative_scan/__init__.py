"""Scan unmapped ROM regions for 68000 function entry point candidates."""

from .main import Validator, scan

__all__ = ['Validator', 'scan']
