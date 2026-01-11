"""
Configuration module for CI Harvester.

Re-exports from main config module for convenience.
"""

from ci_harvester.config import (
    Config,
    CISourceConfig,
    ProductConfig,
    CollectionSettings,
)

__all__ = [
    'Config',
    'CISourceConfig', 
    'ProductConfig',
    'CollectionSettings',
]
