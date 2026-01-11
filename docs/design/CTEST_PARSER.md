# CI Harvester - CTest Parser

## 1. Overview

This document describes the parser for CMake's CTest framework test results. CTest is part of the CMake build system and generates XML-formatted test results that can be parsed for structured test data.

## 2. CTest Output Formats

### 2.1 CTest XML (Test.xml)

The primary output format when running tests via CTest's CDash integration or direct XML output.

**Location:** `Testing/<tag>/Test.xml` or custom path

**Example:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Site BuildName="Linux-g++"
      Name="build-server"
      Generator="ctest-3.22.1"
      BuildStamp="20240115-1234-Experimental">
  <Testing>
    <StartDateTime>Jan 15 12:34:00 EST</StartDateTime>
    <StartTestTime>1705339240</StartTestTime>
    <TestList>
      <Test>MyProject::TestSuite1::test_addition</Test>
      <Test>MyProject::TestSuite1::test_subtraction</Test>
      <Test>MyProject::TestSuite2::test_multiplication</Test>
    </TestList>
    <Test Status="passed">
      <Name>MyProject::TestSuite1::test_addition</Name>
      <Path>./tests</Path>
      <FullName>./tests/test_math</FullName>
      <FullCommandLine>/path/to/test_math --gtest_filter=TestSuite1.test_addition</FullCommandLine>
      <Results>
        <NamedMeasurement type="numeric/double" name="Execution Time">
          <Value>0.123</Value>
        </NamedMeasurement>
        <NamedMeasurement type="numeric/double" name="Processors">
          <Value>1</Value>
        </NamedMeasurement>
        <NamedMeasurement type="text/string" name="Completion Status">
          <Value>Completed</Value>
        </NamedMeasurement>
        <Measurement>
          <Value encoding="base64" compression="gzip">H4sIAAAAA...</Value>
        </Measurement>
      </Results>
    </Test>
    <Test Status="failed">
      <Name>MyProject::TestSuite1::test_subtraction</Name>
      <Path>./tests</Path>
      <FullName>./tests/test_math</FullName>
      <FullCommandLine>/path/to/test_math --gtest_filter=TestSuite1.test_subtraction</FullCommandLine>
      <Results>
        <NamedMeasurement type="numeric/double" name="Execution Time">
          <Value>0.456</Value>
        </NamedMeasurement>
        <NamedMeasurement type="text/string" name="Exit Code">
          <Value>Failed</Value>
        </NamedMeasurement>
        <Measurement>
          <Value>test_subtraction FAILED
Expected: 5
Actual: 4</Value>
        </Measurement>
      </Results>
    </Test>
    <EndDateTime>Jan 15 12:35:00 EST</EndDateTime>
    <EndTestTime>1705339300</EndTestTime>
    <ElapsedMinutes>1</ElapsedMinutes>
  </Testing>
</Site>
```

### 2.2 JUnit-Style XML (--output-junit)

CTest 3.21+ supports JUnit-compatible output:

```bash
ctest --output-junit results.xml
```

**Example:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="test_math" tests="3" failures="1" skipped="0" errors="0" time="0.579">
    <testcase name="test_addition" classname="TestSuite1" time="0.123" status="run"/>
    <testcase name="test_subtraction" classname="TestSuite1" time="0.456" status="run">
      <failure message="Values differ" type="AssertionError">
Expected: 5
Actual: 4
      </failure>
    </testcase>
    <testcase name="test_multiplication" classname="TestSuite2" time="0.000" status="run"/>
  </testsuite>
</testsuites>
```

### 2.3 TAG File

The TAG file points to the current test results:

```
20240115-1234
Experimental
```

### 2.4 LastTest.log

Detailed test output log:

```
Start testing: Jan 15 12:34:00
----------------------------------------------------------
1/3 Testing: test_addition
1/3 Test: test_addition
Command: "/path/to/test_math" "--gtest_filter=TestSuite1.test_addition"
Directory: /build/tests
"test_addition" start time: Jan 15 12:34:00
Output:
----------------------------------------------------------
[==========] Running 1 test from 1 test suite.
[----------] 1 test from TestSuite1
[ RUN      ] TestSuite1.test_addition
[       OK ] TestSuite1.test_addition (0 ms)
[----------] 1 test from TestSuite1 (0 ms total)
[==========] 1 test from 1 test suite ran. (0 ms total)
[  PASSED  ] 1 test.
<end of output>
Test time =   0.12 sec
----------------------------------------------------------
Test Passed.
"test_addition" end time: Jan 15 12:34:00
"test_addition" time elapsed: 00:00:00
----------------------------------------------------------
```

## 3. Parser Implementation

### 3.1 Data Structures

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum

class TestStatus(Enum):
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
    type: str  # numeric/double, text/string, etc.
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
    """A collection of test results (typically one executable)."""
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
```

### 3.2 CTest XML Parser

```python
import xml.etree.ElementTree as ET
import base64
import gzip
import re
from typing import Optional
from datetime import datetime

class CTestXMLParser:
    """Parser for CTest Test.xml format."""
    
    def can_parse(self, content: bytes, filename: str) -> bool:
        """Check if this parser can handle the content."""
        # Check filename
        if 'Test.xml' in filename or 'test.xml' in filename.lower():
            return True
        
        # Check content for CTest markers
        try:
            content_str = content.decode('utf-8', errors='ignore')[:1000]
            if '<Site' in content_str and '<Testing>' in content_str:
                return True
            if 'ctest' in content_str.lower():
                return True
        except:
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
            
            # Group by path (suite)
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
        
        # Parse Results
        results = test_elem.find('Results')
        duration = 0.0
        output = None
        measurements = []
        
        if results is not None:
            # Parse named measurements
            for nm in results.findall('NamedMeasurement'):
                measurement = self._parse_measurement(nm)
                if measurement:
                    measurements.append(measurement)
                    
                    # Extract duration
                    if measurement.name == 'Execution Time':
                        try:
                            duration = float(measurement.value)
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
        
        # Convert numeric types
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
        # Common patterns for failure messages
        patterns = [
            r'FAILED[:\s]+(.+?)(?:\n|$)',
            r'Error[:\s]+(.+?)(?:\n|$)',
            r'Assertion failed[:\s]+(.+?)(?:\n|$)',
            r'Expected[:\s]+(.+?)(?:\n|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                return match.group(0).strip()[:500]  # Limit length
        
        # Return first non-empty line if no pattern matched
        for line in output.split('\n'):
            line = line.strip()
            if line and not line.startswith('['):
                return line[:500]
        
        return "Test failed"
```

### 3.3 JUnit XML Parser (for CTest --output-junit)

```python
class CTestJUnitParser:
    """Parser for CTest JUnit-style XML output."""
    
    def can_parse(self, content: bytes, filename: str) -> bool:
        """Check if this parser can handle the content."""
        # Check for JUnit-style XML
        try:
            content_str = content.decode('utf-8', errors='ignore')[:1000]
            if '<testsuites>' in content_str or '<testsuite' in content_str:
                return True
        except:
            pass
        
        return False
    
    def parse(self, content: bytes) -> CTestReport:
        """Parse JUnit-style XML content."""
        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML: {e}")
        
        report = CTestReport()
        
        # Handle both <testsuites> wrapper and direct <testsuite>
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
```

### 3.4 Parser Factory

```python
class ParserFactory:
    """Factory for creating appropriate parser based on content."""
    
    def __init__(self):
        self._parsers = [
            CTestXMLParser(),
            CTestJUnitParser(),
            # Add more parsers here
        ]
    
    def get_parser(self, content: bytes, filename: str):
        """Get appropriate parser for content."""
        for parser in self._parsers:
            if parser.can_parse(content, filename):
                return parser
        
        raise ValueError(f"No parser found for {filename}")
    
    def parse(self, content: bytes, filename: str) -> CTestReport:
        """Parse content with appropriate parser."""
        parser = self.get_parser(content, filename)
        return parser.parse(content)
```

## 4. Database Integration

### 4.1 Saving Results to Database

```python
from sqlalchemy.orm import Session
from ci_harvester.db.models import TestSuite, TestResult, Build
from ci_harvester.parsers.ctest import CTestReport, CTestResult, TestStatus

class CTestResultSaver:
    """Save CTest results to database."""
    
    STATUS_MAP = {
        TestStatus.PASSED: 'passed',
        TestStatus.FAILED: 'failed',
        TestStatus.SKIPPED: 'skipped',
        TestStatus.ERROR: 'error',
        TestStatus.TIMEOUT: 'timeout',
        TestStatus.NOT_RUN: 'skipped'
    }
    
    def __init__(self, session: Session):
        self.session = session
    
    def save(self, report: CTestReport, build: Build) -> int:
        """
        Save CTest report to database.
        
        Returns:
            Number of test results saved
        """
        total_saved = 0
        
        for ctest_suite in report.suites:
            # Create TestSuite record
            suite = TestSuite(
                build_id=build.id,
                name=ctest_suite.name,
                framework='ctest',
                total_tests=ctest_suite.total_tests,
                passed=ctest_suite.passed,
                failed=ctest_suite.failed,
                skipped=ctest_suite.skipped,
                errors=ctest_suite.errors,
                duration_ms=int(ctest_suite.duration_seconds * 1000),
                metadata={
                    'generator': report.generator,
                    'build_stamp': report.build_stamp
                }
            )
            self.session.add(suite)
            self.session.flush()  # Get suite ID
            
            # Create TestResult records
            for ctest_result in ctest_suite.tests:
                result = self._create_test_result(ctest_result, suite, build)
                self.session.add(result)
                total_saved += 1
        
        self.session.commit()
        return total_saved
    
    def _create_test_result(
        self, 
        ctest_result: CTestResult,
        suite: TestSuite,
        build: Build
    ) -> TestResult:
        """Create TestResult record from CTestResult."""
        # Parse test name for class/name split
        name = ctest_result.name
        class_name = None
        
        if '::' in name:
            parts = name.rsplit('::', 1)
            class_name = parts[0]
            name = parts[1]
        
        return TestResult(
            suite_id=suite.id,
            build_id=build.id,
            name=name,
            class_name=class_name,
            status=self.STATUS_MAP.get(ctest_result.status, 'unknown'),
            duration_ms=int(ctest_result.duration_seconds * 1000),
            message=ctest_result.failure_message,
            stdout=ctest_result.output,
            properties={
                'command_line': ctest_result.command_line,
                'path': ctest_result.path,
                'measurements': [
                    {'name': m.name, 'type': m.type, 'value': m.value}
                    for m in ctest_result.measurements
                ]
            },
            metadata=ctest_result.properties
        )
```

## 5. Usage Examples

### 5.1 Basic Parsing

```python
from ci_harvester.parsers.ctest import ParserFactory

# Parse from file
with open('Testing/20240115-1234/Test.xml', 'rb') as f:
    content = f.read()

factory = ParserFactory()
report = factory.parse(content, 'Test.xml')

print(f"Total tests: {report.total_tests}")
print(f"Passed: {report.total_passed}")
print(f"Failed: {report.total_failed}")

for suite in report.suites:
    print(f"\nSuite: {suite.name}")
    for test in suite.tests:
        print(f"  {test.status.value}: {test.name} ({test.duration_seconds}s)")
        if test.failure_message:
            print(f"    Error: {test.failure_message}")
```

### 5.2 Integration with Jenkins Collector

```python
from ci_harvester.collectors.jenkins import JenkinsCollector, JenkinsConfig
from ci_harvester.parsers.ctest import ParserFactory, CTestResultSaver
from ci_harvester.db import get_session

def harvest_test_results(job_name: str, build_number: int):
    """Harvest test results from Jenkins build."""
    
    # Initialize components
    config = JenkinsConfig(
        url=os.environ['JENKINS_URL'],
        username=os.environ['JENKINS_USER'],
        api_token=os.environ['JENKINS_TOKEN'],
        artifact_patterns=['**/Test.xml', '**/test-results.xml']
    )
    collector = JenkinsCollector(config)
    factory = ParserFactory()
    
    # Get artifacts
    artifacts = collector.get_artifacts(job_name, build_number)
    
    with get_session() as session:
        # Get or create build record
        build = get_or_create_build(session, job_name, build_number)
        saver = CTestResultSaver(session)
        
        for artifact in artifacts:
            try:
                content = collector.download_artifact(artifact)
                report = factory.parse(content, artifact.file_name)
                saved = saver.save(report, build)
                print(f"Saved {saved} test results from {artifact.file_name}")
            except ValueError as e:
                print(f"Could not parse {artifact.file_name}: {e}")
```

## 6. Error Handling

### 6.1 Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Invalid XML | Truncated or corrupted file | Log and skip |
| Encoding errors | Non-UTF8 content | Use errors='replace' |
| Missing elements | Incomplete test run | Default values |
| Large output | Memory issues | Stream/truncate |

### 6.2 Error Recovery

```python
class RobustCTestParser(CTestXMLParser):
    """Parser with enhanced error recovery."""
    
    def parse(self, content: bytes) -> CTestReport:
        """Parse with error recovery."""
        # Try different encodings
        for encoding in ['utf-8', 'latin-1', 'cp1252']:
            try:
                decoded = content.decode(encoding)
                # Fix common XML issues
                decoded = self._fix_xml(decoded)
                return super().parse(decoded.encode('utf-8'))
            except (UnicodeDecodeError, ET.ParseError):
                continue
        
        raise ValueError("Could not parse content with any encoding")
    
    def _fix_xml(self, content: str) -> str:
        """Fix common XML issues."""
        # Remove invalid characters
        import re
        content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', content)
        
        # Fix unclosed elements (truncated files)
        if not content.strip().endswith('>'):
            # Try to close open elements
            content = content + '</Testing></Site>'
        
        return content
```

## 7. Testing

### 7.1 Unit Tests

```python
import pytest
from ci_harvester.parsers.ctest import CTestXMLParser, TestStatus

class TestCTestXMLParser:
    
    @pytest.fixture
    def parser(self):
        return CTestXMLParser()
    
    def test_parse_passed_test(self, parser):
        xml = b'''<?xml version="1.0"?>
        <Site Name="test-server">
          <Testing>
            <StartTestTime>1705339240</StartTestTime>
            <Test Status="passed">
              <Name>test_example</Name>
              <Path>./tests</Path>
              <Results>
                <NamedMeasurement name="Execution Time" type="numeric/double">
                  <Value>0.5</Value>
                </NamedMeasurement>
              </Results>
            </Test>
            <EndTestTime>1705339300</EndTestTime>
          </Testing>
        </Site>'''
        
        report = parser.parse(xml)
        
        assert len(report.suites) == 1
        assert len(report.suites[0].tests) == 1
        assert report.suites[0].tests[0].status == TestStatus.PASSED
        assert report.suites[0].tests[0].duration_seconds == 0.5
    
    def test_parse_failed_test(self, parser):
        xml = b'''<?xml version="1.0"?>
        <Site Name="test-server">
          <Testing>
            <Test Status="failed">
              <Name>test_failing</Name>
              <Results>
                <Measurement>
                  <Value>Expected 5 but got 4</Value>
                </Measurement>
              </Results>
            </Test>
          </Testing>
        </Site>'''
        
        report = parser.parse(xml)
        
        assert report.suites[0].tests[0].status == TestStatus.FAILED
        assert 'Expected 5' in report.suites[0].tests[0].output
    
    def test_parse_base64_output(self, parser):
        import base64
        output = base64.b64encode(b"Test output here").decode()
        
        xml = f'''<?xml version="1.0"?>
        <Site Name="test-server">
          <Testing>
            <Test Status="passed">
              <Name>test_encoded</Name>
              <Results>
                <Measurement>
                  <Value encoding="base64">{output}</Value>
                </Measurement>
              </Results>
            </Test>
          </Testing>
        </Site>'''.encode()
        
        report = parser.parse(xml)
        
        assert 'Test output here' in report.suites[0].tests[0].output
```

### 7.2 Test Fixtures

```python
# tests/fixtures/ctest/
# ├── passed_test.xml
# ├── failed_test.xml
# ├── mixed_results.xml
# ├── gzip_encoded.xml
# ├── junit_format.xml
# └── truncated.xml
```

## 8. Performance Considerations

### 8.1 Large File Handling

```python
def parse_large_file(file_path: str, max_output_size: int = 100000):
    """Parse large CTest XML with memory limits."""
    
    # Use iterparse for streaming
    tests = []
    for event, elem in ET.iterparse(file_path, events=['end']):
        if elem.tag == 'Test':
            test = parse_test_element(elem)
            
            # Truncate large output
            if test.output and len(test.output) > max_output_size:
                test.output = test.output[:max_output_size] + '\n... [truncated]'
            
            tests.append(test)
            elem.clear()  # Free memory
    
    return tests
```

### 8.2 Batch Processing

```python
async def parse_artifacts_async(artifacts: List[Artifact]) -> List[CTestReport]:
    """Parse multiple artifacts concurrently."""
    import asyncio
    
    async def parse_one(artifact):
        content = await download_artifact_async(artifact)
        return factory.parse(content, artifact.file_name)
    
    tasks = [parse_one(a) for a in artifacts]
    return await asyncio.gather(*tasks, return_exceptions=True)
```
