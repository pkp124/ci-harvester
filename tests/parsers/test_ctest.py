"""
Tests for CTest parser.
"""

import pytest
from ci_harvester.parsers.ctest import (
    CTestXMLParser,
    CTestJUnitParser,
    TestStatus,
)


class TestCTestXMLParser:
    """Tests for CTestXMLParser."""
    
    @pytest.fixture
    def parser(self):
        return CTestXMLParser()
    
    def test_can_parse_test_xml(self, parser):
        """Test that parser recognizes Test.xml files."""
        assert parser.can_parse(b"<Site><Testing>", "Test.xml")
        assert parser.can_parse(b"<Site><Testing>", "build/Testing/Test.xml")
    
    def test_can_parse_ctest_content(self, parser):
        """Test that parser recognizes CTest content."""
        content = b'<?xml version="1.0"?><Site><Testing></Testing></Site>'
        assert parser.can_parse(content, "results.xml")
    
    def test_parse_passed_test(self, parser, sample_ctest_xml):
        """Test parsing a passed test."""
        report = parser.parse(sample_ctest_xml)
        
        assert report.site_name == "test-server"
        assert report.build_name == "Linux-g++"
        assert len(report.suites) >= 1
        
        # Find the passing test
        passing_tests = [
            t for s in report.suites for t in s.tests 
            if t.status == TestStatus.PASSED
        ]
        assert len(passing_tests) == 1
        assert "test_passing" in passing_tests[0].name
        assert passing_tests[0].duration_seconds == 0.123
    
    def test_parse_failed_test(self, parser, sample_ctest_xml):
        """Test parsing a failed test."""
        report = parser.parse(sample_ctest_xml)
        
        # Find the failing test
        failing_tests = [
            t for s in report.suites for t in s.tests 
            if t.status == TestStatus.FAILED
        ]
        assert len(failing_tests) == 1
        assert "test_failing" in failing_tests[0].name
        assert failing_tests[0].failure_message is not None
    
    def test_parse_counts(self, parser, sample_ctest_xml):
        """Test that test counts are correct."""
        report = parser.parse(sample_ctest_xml)
        
        assert report.total_tests == 2
        assert report.total_passed == 1
        assert report.total_failed == 1
    
    def test_parse_invalid_xml(self, parser):
        """Test handling of invalid XML."""
        with pytest.raises(ValueError, match="Invalid XML"):
            parser.parse(b"not valid xml")


class TestCTestJUnitParser:
    """Tests for CTestJUnitParser."""
    
    @pytest.fixture
    def parser(self):
        return CTestJUnitParser()
    
    def test_can_parse_junit_content(self, parser):
        """Test that parser recognizes JUnit content."""
        content = b'<testsuites><testsuite></testsuite></testsuites>'
        assert parser.can_parse(content, "results.xml")
    
    def test_parse_junit_xml(self, parser, sample_junit_xml):
        """Test parsing JUnit XML."""
        report = parser.parse(sample_junit_xml)
        
        assert len(report.suites) == 1
        suite = report.suites[0]
        
        assert suite.name == "TestSuite"
        assert suite.total_tests == 3
        assert suite.passed == 1
        assert suite.failed == 1
        assert suite.skipped == 1
    
    def test_parse_failure_details(self, parser, sample_junit_xml):
        """Test that failure details are extracted."""
        report = parser.parse(sample_junit_xml)
        
        failing_tests = [
            t for s in report.suites for t in s.tests 
            if t.status == TestStatus.FAILED
        ]
        assert len(failing_tests) == 1
        assert "Values differ" in failing_tests[0].failure_message
    
    def test_parse_skipped_test(self, parser, sample_junit_xml):
        """Test parsing skipped tests."""
        report = parser.parse(sample_junit_xml)
        
        skipped_tests = [
            t for s in report.suites for t in s.tests 
            if t.status == TestStatus.SKIPPED
        ]
        assert len(skipped_tests) == 1
