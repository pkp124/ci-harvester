"""
Parsers module - Parses test results from various formats.
"""

from typing import List, Type
from abc import ABC, abstractmethod


class BaseParser(ABC):
    """Base class for test result parsers."""
    
    @abstractmethod
    def can_parse(self, content: bytes, filename: str) -> bool:
        """Check if this parser can handle the content."""
        pass
    
    @abstractmethod
    def parse(self, content: bytes):
        """Parse content into structured test results."""
        pass


class ParserFactory:
    """Factory for creating appropriate parser based on content."""
    
    def __init__(self):
        from .ctest import CTestXMLParser, CTestJUnitParser
        
        self._parsers: List[BaseParser] = [
            CTestXMLParser(),
            CTestJUnitParser(),
        ]
    
    def get_parser(self, content: bytes, filename: str) -> BaseParser:
        """Get appropriate parser for content."""
        for parser in self._parsers:
            if parser.can_parse(content, filename):
                return parser
        
        raise ValueError(f"No parser found for {filename}")
    
    def parse(self, content: bytes, filename: str):
        """Parse content with appropriate parser."""
        parser = self.get_parser(content, filename)
        return parser.parse(content)
