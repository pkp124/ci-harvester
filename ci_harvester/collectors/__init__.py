"""
Collectors module - Interfaces with CI platforms to fetch build data.
"""

from typing import Dict, Type
from abc import ABC, abstractmethod

# Collector registry
_collectors: Dict[str, Type["BaseCollector"]] = {}


def register_collector(source_type: str):
    """Decorator to register a collector class."""
    def decorator(cls):
        _collectors[source_type] = cls
        return cls
    return decorator


def get_collector(source_type: str, connection_id: str):
    """Get a collector instance for the given source type."""
    if source_type not in _collectors:
        raise ValueError(f"Unknown collector type: {source_type}")
    
    collector_class = _collectors[source_type]
    return collector_class.from_connection(connection_id)


# Import collectors to trigger registration
from .jenkins import JenkinsCollector  # noqa: F401
