"""
CTest Parser - Parses CTest XML test results.

Hierarchy:
- Parses CTest XML to extract test results
- Creates/updates Test definitions (persistent per job)
- Creates TestExecution entries (per build)
- Creates CTestMeasurement entries (per execution)

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
class CTestMeasurement:
    """A named measurement from CTest results."""
    name: str
    type: str  # 'numeric/double', 'text/string', etc.
    value: Any
    unit: Optional[str] = None


@dataclass
class CTestResult:
    """Individual test result from CTest."""
    name: str
    full_name: str
    status: TestStatus
    duration_seconds: float
    class_name: Optional[str] = None
    suite_name: Optional[str] = None
    path: Optional[str] = None
    command_line: Optional[str] = None
    output: Optional[str] = None
    failure_message: Optional[str] = None
    exit_code: Optional[int] = None
    measurements: List[CTestMeasurement] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CTestReport:
    """Complete CTest results for a build."""
    site_name: Optional[str] = None
    build_name: Optional[str] = None
    build_stamp: Optional[str] = None
    generator: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    tests: List[CTestResult] = field(default_factory=list)
    
    @property
    def total_tests(self) -> int:
        return len(self.tests)
    
    @property
    def total_passed(self) -> int:
        return sum(1 for t in self.tests if t.status == TestStatus.PASSED)
    
    @property
    def total_failed(self) -> int:
        return sum(1 for t in self.tests if t.status == TestStatus.FAILED)
    
    @property
    def total_skipped(self) -> int:
        return sum(1 for t in self.tests if t.status == TestStatus.SKIPPED)
    
    @property
    def total_errors(self) -> int:
        return sum(1 for t in self.tests if t.status == TestStatus.ERROR)


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
        for test_elem in testing.findall('Test'):
            test_result = self._parse_test(test_elem)
            report.tests.append(test_result)
        
        return report
    
    def _parse_test(self, test_elem: ET.Element) -> CTestResult:
        """Parse a single Test element."""
        status_str = test_elem.get('Status', 'unknown').lower()
        status = self._map_status(status_str)
        
        name_elem = test_elem.find('Name')
        raw_name = name_elem.text if name_elem is not None else 'unknown'
        
        path_elem = test_elem.find('Path')
        path = path_elem.text if path_elem is not None else None
        
        full_name_elem = test_elem.find('FullName')
        full_name_path = full_name_elem.text if full_name_elem is not None else None
        
        cmd_elem = test_elem.find('FullCommandLine')
        command_line = cmd_elem.text if cmd_elem is not None else None
        
        # Parse name components (e.g., "Suite::Class::test_method")
        name, class_name, suite_name = self._parse_test_name(raw_name)
        full_name = raw_name  # Use the original name as full_name
        
        # Parse Results
        results = test_elem.find('Results')
        duration = 0.0
        output = None
        exit_code = None
        measurements = []
        
        if results is not None:
            for nm in results.findall('NamedMeasurement'):
                measurement = self._parse_measurement(nm)
                if measurement:
                    measurements.append(measurement)
                    
                    # Extract special measurements
                    if measurement.name == 'Execution Time':
                        try:
                            duration = float(measurement.value)
                        except (ValueError, TypeError):
                            pass
                    elif measurement.name == 'Exit Code':
                        try:
                            exit_code = int(measurement.value)
                        except (ValueError, TypeError):
                            pass
            
            # Parse output (Measurement without name)
            for m in results.findall('Measurement'):
                value_elem = m.find('Value')
                if value_elem is not None:
                    output = self._decode_measurement_value(value_elem)
        
        # Extract failure message from output
        failure_message = None
        if status == TestStatus.FAILED and output:
            failure_message = self._extract_failure_message(output)
        
        return CTestResult(
            name=name,
            full_name=full_name,
            status=status,
            duration_seconds=duration,
            class_name=class_name,
            suite_name=suite_name,
            path=path,
            command_line=command_line,
            output=output,
            failure_message=failure_message,
            exit_code=exit_code,
            measurements=measurements
        )
    
    def _parse_test_name(self, raw_name: str) -> tuple:
        """
        Parse test name into components.
        
        Examples:
        - "test_simple" -> ("test_simple", None, None)
        - "TestClass::test_method" -> ("test_method", "TestClass", None)
        - "Suite::Class::test" -> ("test", "Class", "Suite")
        """
        parts = raw_name.split('::')
        
        if len(parts) == 1:
            return (parts[0], None, None)
        elif len(parts) == 2:
            return (parts[1], parts[0], None)
        else:
            # Take last as name, second-to-last as class, rest as suite
            name = parts[-1]
            class_name = parts[-2]
            suite_name = '::'.join(parts[:-2])
            return (name, class_name, suite_name)
    
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
    
    def _parse_measurement(self, elem: ET.Element) -> Optional[CTestMeasurement]:
        """Parse a NamedMeasurement element."""
        name = elem.get('name')
        type_ = elem.get('type', 'text/string')
        
        value_elem = elem.find('Value')
        if value_elem is None:
            return None
        
        value = value_elem.text
        unit = None
        
        # Convert numeric types
        if 'numeric' in type_ and value:
            try:
                value = float(value)
                # Infer unit from name
                if 'time' in name.lower():
                    unit = 'seconds'
                elif 'memory' in name.lower():
                    unit = 'bytes'
            except ValueError:
                pass
        
        return CTestMeasurement(name=name, type=type_, value=value, unit=unit)
    
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
    """Parser for CTest JUnit-style XML output (--output-junit)."""
    
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
            suite_name = ts_elem.get('name', 'unknown')
            
            for tc_elem in ts_elem.findall('testcase'):
                test = self._parse_testcase(tc_elem, suite_name)
                report.tests.append(test)
        
        return report
    
    def _parse_testcase(self, elem: ET.Element, suite_name: str) -> CTestResult:
        """Parse a testcase element."""
        name = elem.get('name', 'unknown')
        classname = elem.get('classname', '')
        duration = float(elem.get('time', 0))
        
        # Build full_name
        if classname and suite_name and classname != suite_name:
            full_name = f"{suite_name}::{classname}::{name}"
        elif classname:
            full_name = f"{classname}::{name}"
        elif suite_name:
            full_name = f"{suite_name}::{name}"
        else:
            full_name = name
        
        # Determine status
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
        
        # Get stdout/stderr if present
        stdout = elem.find('system-out')
        stderr = elem.find('system-err')
        
        # Create execution time measurement
        measurements = [
            CTestMeasurement(
                name='Execution Time',
                type='numeric/double',
                value=duration,
                unit='seconds'
            )
        ]
        
        return CTestResult(
            name=name,
            full_name=full_name,
            status=status,
            duration_seconds=duration,
            class_name=classname or None,
            suite_name=suite_name,
            output=output,
            failure_message=failure_message,
            measurements=measurements,
            properties={
                'stdout': stdout.text if stdout is not None else None,
                'stderr': stderr.text if stderr is not None else None
            }
        )


# =============================================================================
# Database Integration
# =============================================================================

class CTestResultSaver:
    """Save CTest results to database using the new data model."""
    
    STATUS_MAP = {
        TestStatus.PASSED: 'passed',
        TestStatus.FAILED: 'failed',
        TestStatus.SKIPPED: 'skipped',
        TestStatus.ERROR: 'error',
        TestStatus.TIMEOUT: 'timeout',
        TestStatus.NOT_RUN: 'not_run',
    }
    
    def __init__(self, session):
        """
        Initialize saver with database session.
        
        Args:
            session: SQLAlchemy session
        """
        self.session = session
    
    def save(self, report: CTestReport, build) -> dict:
        """
        Save CTest report to database.
        
        Creates/updates Test definitions and creates TestExecution + CTestMeasurement entries.
        
        Args:
            report: Parsed CTest report
            build: Build ORM instance
        
        Returns:
            dict with counts of saved entities
        """
        from ci_harvester.db.models import Test, TestExecution, CTestMeasurement as CTestMeasurementModel
        from datetime import datetime, timezone
        
        job = build.job
        stats = {
            'tests_created': 0,
            'tests_updated': 0,
            'executions_created': 0,
            'measurements_created': 0,
        }
        
        for ctest_result in report.tests:
            # Get or create Test definition
            test = self.session.query(Test).filter(
                Test.job_id == job.id,
                Test.full_name == ctest_result.full_name
            ).first()
            
            if test is None:
                # Create new test
                test = Test(
                    job_id=job.id,
                    name=ctest_result.name,
                    full_name=ctest_result.full_name,
                    class_name=ctest_result.class_name,
                    suite_name=ctest_result.suite_name,
                    file_path=ctest_result.path,
                    is_active=True,
                    first_seen_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc),
                    metadata={
                        'generator': report.generator,
                        'build_stamp': report.build_stamp,
                    }
                )
                self.session.add(test)
                self.session.flush()  # Get ID
                stats['tests_created'] += 1
            else:
                # Update existing test
                test.last_seen_at = datetime.now(timezone.utc)
                test.is_active = True
                stats['tests_updated'] += 1
            
            # Check if execution already exists
            existing_execution = self.session.query(TestExecution).filter(
                TestExecution.build_id == build.id,
                TestExecution.test_id == test.id
            ).first()
            
            if existing_execution:
                # Skip if already saved
                continue
            
            # Create TestExecution
            execution = TestExecution(
                build_id=build.id,
                test_id=test.id,
                status=self.STATUS_MAP.get(ctest_result.status, 'unknown'),
                duration_ms=int(ctest_result.duration_seconds * 1000) if ctest_result.duration_seconds else None,
                message=ctest_result.failure_message,
                stdout=ctest_result.output,
                stderr=ctest_result.properties.get('stderr'),
                command_line=ctest_result.command_line,
                exit_code=ctest_result.exit_code,
                metadata={
                    'path': ctest_result.path,
                }
            )
            self.session.add(execution)
            self.session.flush()  # Get ID
            stats['executions_created'] += 1
            
            # Create CTestMeasurements
            for measurement in ctest_result.measurements:
                value_numeric = None
                value_text = None
                
                if isinstance(measurement.value, (int, float)):
                    value_numeric = float(measurement.value)
                else:
                    value_text = str(measurement.value) if measurement.value is not None else None
                
                cm = CTestMeasurementModel(
                    test_execution_id=execution.id,
                    name=measurement.name,
                    type=measurement.type,
                    value_numeric=value_numeric,
                    value_text=value_text,
                    unit=measurement.unit,
                )
                self.session.add(cm)
                stats['measurements_created'] += 1
        
        self.session.commit()
        return stats
