"""
CTest Parser - Parses CTest XML test results.

See docs/design/CTEST_PARSER.md for detailed documentation.
"""

import base64
import gzip
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any

from . import BaseParser


class TestStatus(Enum):
    """Test result status."""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
    TIMEOUT = "timeout"
    NOT_RUN = "not_run"


@dataclass
class TestMeasurement:
    """A named measurement from CTest results."""
    name: str
    type: str
    value: Any


@dataclass
class CTestResult:
    """Individual test result from CTest."""
    name: str
    status: TestStatus
    duration_seconds: float
    path: Optional[str] = None
    full_name: Optional[str] = None
    command_line: Optional[str] = None
    output: Optional[str] = None
    failure_message: Optional[str] = None
    measurements: List[TestMeasurement] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CTestSuite:
    """A collection of test results."""
    name: str
    framework: str = "ctest"
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    tests: List[CTestResult] = field(default_factory=list)


@dataclass
class CTestReport:
    """Complete CTest results for a build."""
    site_name: Optional[str] = None
    build_name: Optional[str] = None
    build_stamp: Optional[str] = None
    generator: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    suites: List[CTestSuite] = field(default_factory=list)
    
    @property
    def total_tests(self) -> int:
        return sum(s.total_tests for s in self.suites)
    
    @property
    def total_passed(self) -> int:
        return sum(s.passed for s in self.suites)
    
    @property
    def total_failed(self) -> int:
        return sum(s.failed for s in self.suites)


class CTestXMLParser(BaseParser):
    """Parser for CTest Test.xml format."""
    
    def can_parse(self, content: bytes, filename: str) -> bool:
        """Check if this parser can handle the content."""
        if 'Test.xml' in filename or 'test.xml' in filename.lower():
            return True
        
        try:
            content_str = content.decode('utf-8', errors='ignore')[:1000]
            if '<Site' in content_str and '<Testing>' in content_str:
                return True
            if 'ctest' in content_str.lower():
                return True
        except Exception:
            pass
        
        return False
    
    def parse(self, content: bytes) -> CTestReport:
        """Parse CTest XML content into structured results."""
        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML: {e}")
        
        report = CTestReport()
        
        # Parse Site attributes
        report.site_name = root.get('Name')
        report.build_name = root.get('BuildName')
        report.build_stamp = root.get('BuildStamp')
        report.generator = root.get('Generator')
        
        # Find Testing element
        testing = root.find('.//Testing')
        if testing is None:
            raise ValueError("No Testing element found")
        
        # Parse timestamps
        start_time = testing.find('StartTestTime')
        if start_time is not None and start_time.text:
            try:
                report.start_time = datetime.fromtimestamp(int(start_time.text))
            except (ValueError, OSError):
                pass
        
        end_time = testing.find('EndTestTime')
        if end_time is not None and end_time.text:
            try:
                report.end_time = datetime.fromtimestamp(int(end_time.text))
            except (ValueError, OSError):
                pass
        
        # Parse individual tests
        tests_by_path: Dict[str, List[CTestResult]] = {}
        
        for test_elem in testing.findall('Test'):
            test_result = self._parse_test(test_elem)
            
            path = test_result.path or 'default'
            if path not in tests_by_path:
                tests_by_path[path] = []
            tests_by_path[path].append(test_result)
        
        # Create suites from grouped tests
        for path, tests in tests_by_path.items():
            suite = CTestSuite(
                name=path,
                tests=tests,
                total_tests=len(tests),
                passed=sum(1 for t in tests if t.status == TestStatus.PASSED),
                failed=sum(1 for t in tests if t.status == TestStatus.FAILED),
                skipped=sum(1 for t in tests if t.status == TestStatus.SKIPPED),
                errors=sum(1 for t in tests if t.status == TestStatus.ERROR),
                duration_seconds=sum(t.duration_seconds for t in tests)
            )
            report.suites.append(suite)
        
        return report
    
    def _parse_test(self, test_elem: ET.Element) -> CTestResult:
        """Parse a single Test element."""
        status_str = test_elem.get('Status', 'unknown').lower()
        status = self._map_status(status_str)
        
        name_elem = test_elem.find('Name')
        name = name_elem.text if name_elem is not None else 'unknown'
        
        path_elem = test_elem.find('Path')
        path = path_elem.text if path_elem is not None else None
        
        full_name_elem = test_elem.find('FullName')
        full_name = full_name_elem.text if full_name_elem is not None else None
        
        cmd_elem = test_elem.find('FullCommandLine')
        command_line = cmd_elem.text if cmd_elem is not None else None
        
        results = test_elem.find('Results')
        duration = 0.0
        output = None
        measurements = []
        
        if results is not None:
            for nm in results.findall('NamedMeasurement'):
                measurement = self._parse_measurement(nm)
                if measurement:
                    measurements.append(measurement)
                    
                    if measurement.name == 'Execution Time':
                        try:
                            duration = float(measurement.value)
                        except (ValueError, TypeError):
                            pass
            
            for m in results.findall('Measurement'):
                value_elem = m.find('Value')
                if value_elem is not None:
                    output = self._decode_measurement_value(value_elem)
        
        failure_message = None
        if status == TestStatus.FAILED and output:
            failure_message = self._extract_failure_message(output)
        
        return CTestResult(
            name=name,
            status=status,
            duration_seconds=duration,
            path=path,
            full_name=full_name,
            command_line=command_line,
            output=output,
            failure_message=failure_message,
            measurements=measurements
        )
    
    def _map_status(self, status_str: str) -> TestStatus:
        """Map CTest status string to TestStatus enum."""
        status_map = {
            'passed': TestStatus.PASSED,
            'failed': TestStatus.FAILED,
            'notrun': TestStatus.NOT_RUN,
            'timeout': TestStatus.TIMEOUT,
            'disabled': TestStatus.SKIPPED,
        }
        return status_map.get(status_str.lower(), TestStatus.ERROR)
    
    def _parse_measurement(self, elem: ET.Element) -> Optional[TestMeasurement]:
        """Parse a NamedMeasurement element."""
        name = elem.get('name')
        type_ = elem.get('type', 'text/string')
        
        value_elem = elem.find('Value')
        if value_elem is None:
            return None
        
        value = value_elem.text
        
        if 'numeric' in type_ and value:
            try:
                value = float(value)
            except ValueError:
                pass
        
        return TestMeasurement(name=name, type=type_, value=value)
    
    def _decode_measurement_value(self, elem: ET.Element) -> str:
        """Decode measurement value, handling base64/gzip encoding."""
        encoding = elem.get('encoding')
        compression = elem.get('compression')
        value = elem.text or ''
        
        if encoding == 'base64':
            try:
                decoded = base64.b64decode(value)
                if compression == 'gzip':
                    decoded = gzip.decompress(decoded)
                return decoded.decode('utf-8', errors='replace')
            except Exception:
                return value
        
        return value
    
    def _extract_failure_message(self, output: str) -> str:
        """Extract failure message from test output."""
        patterns = [
            r'FAILED[:\s]+(.+?)(?:\n|$)',
            r'Error[:\s]+(.+?)(?:\n|$)',
            r'Assertion failed[:\s]+(.+?)(?:\n|$)',
            r'Expected[:\s]+(.+?)(?:\n|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                return match.group(0).strip()[:500]
        
        for line in output.split('\n'):
            line = line.strip()
            if line and not line.startswith('['):
                return line[:500]
        
        return "Test failed"


class CTestJUnitParser(BaseParser):
    """Parser for CTest JUnit-style XML output."""
    
    def can_parse(self, content: bytes, filename: str) -> bool:
        """Check if this parser can handle the content."""
        try:
            content_str = content.decode('utf-8', errors='ignore')[:1000]
            if '<testsuites>' in content_str or '<testsuite' in content_str:
                return True
        except Exception:
            pass
        
        return False
    
    def parse(self, content: bytes) -> CTestReport:
        """Parse JUnit-style XML content."""
        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML: {e}")
        
        report = CTestReport()
        
        if root.tag == 'testsuites':
            testsuite_elems = root.findall('testsuite')
        elif root.tag == 'testsuite':
            testsuite_elems = [root]
        else:
            raise ValueError(f"Unexpected root element: {root.tag}")
        
        for ts_elem in testsuite_elems:
            suite = self._parse_testsuite(ts_elem)
            report.suites.append(suite)
        
        return report
    
    def _parse_testsuite(self, elem: ET.Element) -> CTestSuite:
        """Parse a testsuite element."""
        suite = CTestSuite(
            name=elem.get('name', 'unknown'),
            total_tests=int(elem.get('tests', 0)),
            failed=int(elem.get('failures', 0)),
            errors=int(elem.get('errors', 0)),
            skipped=int(elem.get('skipped', 0)),
            duration_seconds=float(elem.get('time', 0))
        )
        suite.passed = suite.total_tests - suite.failed - suite.errors - suite.skipped
        
        for tc_elem in elem.findall('testcase'):
            test = self._parse_testcase(tc_elem)
            suite.tests.append(test)
        
        return suite
    
    def _parse_testcase(self, elem: ET.Element) -> CTestResult:
        """Parse a testcase element."""
        name = elem.get('name', 'unknown')
        classname = elem.get('classname', '')
        duration = float(elem.get('time', 0))
        
        failure = elem.find('failure')
        error = elem.find('error')
        skipped = elem.find('skipped')
        
        if failure is not None:
            status = TestStatus.FAILED
            failure_message = failure.get('message', failure.text or 'Test failed')
            output = failure.text
        elif error is not None:
            status = TestStatus.ERROR
            failure_message = error.get('message', error.text or 'Test error')
            output = error.text
        elif skipped is not None:
            status = TestStatus.SKIPPED
            failure_message = None
            output = skipped.get('message', skipped.text)
        else:
            status = TestStatus.PASSED
            failure_message = None
            output = None
        
        stdout = elem.find('system-out')
        stderr = elem.find('system-err')
        
        return CTestResult(
            name=name,
            status=status,
            duration_seconds=duration,
            full_name=f"{classname}::{name}" if classname else name,
            output=output,
            failure_message=failure_message,
            properties={
                'classname': classname,
                'stdout': stdout.text if stdout is not None else None,
                'stderr': stderr.text if stderr is not None else None
            }
        )
