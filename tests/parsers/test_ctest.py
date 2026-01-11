"""
Tests for CTest parser.
"""

import pytest
from ci_harvester.parsers.ctest import (
    CTestXMLParser,
    CTestJUnitParser,
    CTestResultSaver,
    TestStatus,
    CTestReport,
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
    
    def test_cannot_parse_non_ctest(self, parser):
        """Test that parser rejects non-CTest content."""
        assert not parser.can_parse(b"<html></html>", "index.html")
        assert not parser.can_parse(b"plain text", "output.txt")
    
    def test_parse_basic_structure(self, parser, sample_ctest_xml):
        """Test parsing basic CTest XML structure."""
        report = parser.parse(sample_ctest_xml)
        
        assert isinstance(report, CTestReport)
        assert report.site_name == "test-server"
        assert report.build_name == "Linux-g++"
        assert report.generator == "ctest-3.22.1"
    
    def test_parse_passed_test(self, parser, sample_ctest_xml):
        """Test parsing a passed test."""
        report = parser.parse(sample_ctest_xml)
        
        passing_tests = [t for t in report.tests if t.status == TestStatus.PASSED]
        assert len(passing_tests) == 1
        
        test = passing_tests[0]
        assert test.name == "test_passing"
        assert test.full_name == "TestSuite::test_passing"
        assert test.class_name == "TestSuite"
        assert test.duration_seconds == 0.123
        assert test.command_line is not None
    
    def test_parse_failed_test(self, parser, sample_ctest_xml):
        """Test parsing a failed test."""
        report = parser.parse(sample_ctest_xml)
        
        failing_tests = [t for t in report.tests if t.status == TestStatus.FAILED]
        assert len(failing_tests) == 1
        
        test = failing_tests[0]
        assert test.name == "test_failing"
        assert test.full_name == "TestSuite::test_failing"
        assert test.failure_message is not None
        assert "Expected 5" in test.failure_message or "FAILED" in test.failure_message
        assert test.duration_seconds == 0.456
    
    def test_parse_not_run_test(self, parser, sample_ctest_xml):
        """Test parsing a not-run/skipped test."""
        report = parser.parse(sample_ctest_xml)
        
        not_run_tests = [t for t in report.tests if t.status == TestStatus.NOT_RUN]
        assert len(not_run_tests) == 1
        assert not_run_tests[0].name == "test_skipped"
    
    def test_parse_counts(self, parser, sample_ctest_xml):
        """Test that test counts are correct."""
        report = parser.parse(sample_ctest_xml)
        
        assert report.total_tests == 3
        assert report.total_passed == 1
        assert report.total_failed == 1
    
    def test_parse_measurements(self, parser, sample_ctest_with_measurements):
        """Test parsing CTest measurements."""
        report = parser.parse(sample_ctest_with_measurements)
        
        assert len(report.tests) == 1
        test = report.tests[0]
        
        # Check measurements
        measurement_names = [m.name for m in test.measurements]
        assert "Execution Time" in measurement_names
        assert "Memory Usage" in measurement_names
        assert "Processors" in measurement_names
        assert "Completion Status" in measurement_names
        
        # Check execution time measurement
        exec_time = next(m for m in test.measurements if m.name == "Execution Time")
        assert exec_time.value == 5.432
        assert exec_time.type == "numeric/double"
        assert exec_time.unit == "seconds"
        
        # Check memory measurement
        memory = next(m for m in test.measurements if m.name == "Memory Usage")
        assert memory.value == 1048576
        assert memory.unit == "bytes"
    
    def test_parse_test_name_components(self, parser):
        """Test parsing of test name into components."""
        # Simple name
        name, class_name, suite_name = parser._parse_test_name("test_simple")
        assert name == "test_simple"
        assert class_name is None
        assert suite_name is None
        
        # Class::test
        name, class_name, suite_name = parser._parse_test_name("TestClass::test_method")
        assert name == "test_method"
        assert class_name == "TestClass"
        assert suite_name is None
        
        # Suite::Class::test
        name, class_name, suite_name = parser._parse_test_name("MySuite::TestClass::test_method")
        assert name == "test_method"
        assert class_name == "TestClass"
        assert suite_name == "MySuite"
        
        # Deep nesting
        name, class_name, suite_name = parser._parse_test_name("A::B::C::test")
        assert name == "test"
        assert class_name == "C"
        assert suite_name == "A::B"
    
    def test_parse_invalid_xml(self, parser):
        """Test handling of invalid XML."""
        with pytest.raises(ValueError, match="Invalid XML"):
            parser.parse(b"not valid xml")
    
    def test_parse_missing_testing_element(self, parser):
        """Test handling of missing Testing element."""
        xml = b'<?xml version="1.0"?><Site></Site>'
        with pytest.raises(ValueError, match="No Testing element"):
            parser.parse(xml)


class TestCTestJUnitParser:
    """Tests for CTestJUnitParser."""
    
    @pytest.fixture
    def parser(self):
        return CTestJUnitParser()
    
    def test_can_parse_junit_content(self, parser):
        """Test that parser recognizes JUnit content."""
        content = b'<testsuites><testsuite></testsuite></testsuites>'
        assert parser.can_parse(content, "results.xml")
        
        content = b'<testsuite name="test"></testsuite>'
        assert parser.can_parse(content, "results.xml")
    
    def test_cannot_parse_non_junit(self, parser):
        """Test that parser rejects non-JUnit content."""
        assert not parser.can_parse(b"<Site><Testing>", "Test.xml")
        assert not parser.can_parse(b"<html></html>", "index.html")
    
    def test_parse_junit_xml(self, parser, sample_junit_xml):
        """Test parsing JUnit XML."""
        report = parser.parse(sample_junit_xml)
        
        assert report.total_tests == 3
        assert report.total_passed == 1
        assert report.total_failed == 1
        assert report.total_skipped == 1
    
    def test_parse_full_name(self, parser, sample_junit_xml):
        """Test that full_name is constructed correctly."""
        report = parser.parse(sample_junit_xml)
        
        # Find the passing test
        passing = [t for t in report.tests if t.status == TestStatus.PASSED][0]
        assert passing.full_name == "MathTests::ArithmeticSuite::test_addition"
        assert passing.name == "test_addition"
        assert passing.class_name == "ArithmeticSuite"
        assert passing.suite_name == "MathTests"
    
    def test_parse_failure_details(self, parser, sample_junit_xml):
        """Test that failure details are extracted."""
        report = parser.parse(sample_junit_xml)
        
        failing_tests = [t for t in report.tests if t.status == TestStatus.FAILED]
        assert len(failing_tests) == 1
        
        test = failing_tests[0]
        assert "Values differ" in test.failure_message
        assert test.output is not None
    
    def test_parse_skipped_test(self, parser, sample_junit_xml):
        """Test parsing skipped tests."""
        report = parser.parse(sample_junit_xml)
        
        skipped_tests = [t for t in report.tests if t.status == TestStatus.SKIPPED]
        assert len(skipped_tests) == 1
    
    def test_parse_measurements(self, parser, sample_junit_xml):
        """Test that execution time measurement is created."""
        report = parser.parse(sample_junit_xml)
        
        for test in report.tests:
            # Each test should have an Execution Time measurement
            exec_time = [m for m in test.measurements if m.name == "Execution Time"]
            assert len(exec_time) == 1
            assert exec_time[0].unit == "seconds"


class TestCTestResultSaver:
    """Tests for CTestResultSaver database integration."""
    
    def test_save_creates_tests(self, db_session, sample_build, sample_ctest_xml):
        """Test that saving creates Test definitions."""
        from ci_harvester.db.models import Test
        from ci_harvester.parsers.ctest import CTestXMLParser, CTestResultSaver
        
        parser = CTestXMLParser()
        report = parser.parse(sample_ctest_xml)
        
        saver = CTestResultSaver(db_session)
        stats = saver.save(report, sample_build)
        
        # Should have created test definitions
        assert stats['tests_created'] == 3
        
        # Verify tests exist in database
        tests = db_session.query(Test).filter(
            Test.job_id == sample_build.job_id
        ).all()
        assert len(tests) == 3
    
    def test_save_creates_executions(self, db_session, sample_build, sample_ctest_xml):
        """Test that saving creates TestExecution records."""
        from ci_harvester.db.models import TestExecution
        from ci_harvester.parsers.ctest import CTestXMLParser, CTestResultSaver
        
        parser = CTestXMLParser()
        report = parser.parse(sample_ctest_xml)
        
        saver = CTestResultSaver(db_session)
        stats = saver.save(report, sample_build)
        
        assert stats['executions_created'] == 3
        
        # Verify executions exist
        executions = db_session.query(TestExecution).filter(
            TestExecution.build_id == sample_build.id
        ).all()
        assert len(executions) == 3
        
        # Check statuses
        statuses = {e.status for e in executions}
        assert 'passed' in statuses
        assert 'failed' in statuses
    
    def test_save_creates_measurements(self, db_session, sample_build, sample_ctest_with_measurements):
        """Test that saving creates CTestMeasurement records."""
        from ci_harvester.db.models import CTestMeasurement
        from ci_harvester.parsers.ctest import CTestXMLParser, CTestResultSaver
        
        parser = CTestXMLParser()
        report = parser.parse(sample_ctest_with_measurements)
        
        saver = CTestResultSaver(db_session)
        stats = saver.save(report, sample_build)
        
        assert stats['measurements_created'] >= 4  # At least 4 measurements
        
        # Verify measurements exist
        measurements = db_session.query(CTestMeasurement).all()
        assert len(measurements) >= 4
        
        # Check that numeric values are stored correctly
        exec_time = [m for m in measurements if m.name == "Execution Time"][0]
        assert exec_time.value_numeric == 5.432
    
    def test_save_reuses_existing_tests(self, db_session, sample_build, sample_ctest_xml):
        """Test that saving reuses existing Test definitions."""
        from ci_harvester.db.models import Test, Build
        from ci_harvester.parsers.ctest import CTestXMLParser, CTestResultSaver
        
        parser = CTestXMLParser()
        report = parser.parse(sample_ctest_xml)
        
        saver = CTestResultSaver(db_session)
        
        # First save
        stats1 = saver.save(report, sample_build)
        assert stats1['tests_created'] == 3
        
        # Create a new build
        build2 = Build(
            job_id=sample_build.job_id,
            external_id="43",
            number=43,
            status="completed",
            result="success",
        )
        db_session.add(build2)
        db_session.commit()
        
        # Second save - should reuse existing tests
        stats2 = saver.save(report, build2)
        assert stats2['tests_created'] == 0
        assert stats2['tests_updated'] == 3
        
        # Total tests should still be 3
        tests = db_session.query(Test).filter(
            Test.job_id == sample_build.job_id
        ).all()
        assert len(tests) == 3
    
    def test_save_idempotent(self, db_session, sample_build, sample_ctest_xml):
        """Test that saving the same report twice is idempotent."""
        from ci_harvester.db.models import TestExecution
        from ci_harvester.parsers.ctest import CTestXMLParser, CTestResultSaver
        
        parser = CTestXMLParser()
        report = parser.parse(sample_ctest_xml)
        
        saver = CTestResultSaver(db_session)
        
        # First save
        stats1 = saver.save(report, sample_build)
        assert stats1['executions_created'] == 3
        
        # Second save - should be idempotent
        stats2 = saver.save(report, sample_build)
        assert stats2['executions_created'] == 0
        
        # Should still have only 3 executions
        executions = db_session.query(TestExecution).filter(
            TestExecution.build_id == sample_build.id
        ).all()
        assert len(executions) == 3
