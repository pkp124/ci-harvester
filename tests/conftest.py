"""
Pytest configuration and fixtures for CI Harvester tests.
"""

import pytest
import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ci_harvester.db.models import Base, Product, Job, Build, Test


@pytest.fixture(scope="session")
def engine():
    """Create a test database engine."""
    # Use in-memory SQLite for tests
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture(scope="function")
def db_session(engine):
    """Create a new database session for each test."""
    Session = sessionmaker(bind=engine)
    session = Session()
    
    yield session
    
    session.rollback()
    session.close()


@pytest.fixture
def sample_product(db_session):
    """Create a sample product for testing."""
    product = Product(
        name="TestProduct",
        description="A test product",
        repository_url="https://github.com/test/product",
    )
    db_session.add(product)
    db_session.commit()
    return product


@pytest.fixture
def sample_job(db_session, sample_product):
    """Create a sample job for testing."""
    job = Job(
        product_id=sample_product.id,
        external_id="test-job",
        name="Test Job",
        url="https://jenkins.example.com/job/test-job/",
        ci_source="jenkins",
        ci_source_url="https://jenkins.example.com",
    )
    db_session.add(job)
    db_session.commit()
    return job


@pytest.fixture
def sample_build(db_session, sample_job):
    """Create a sample build for testing."""
    build = Build(
        job_id=sample_job.id,
        external_id="42",
        number=42,
        status="completed",
        result="success",
        started_at=datetime.now(timezone.utc),
        duration_ms=60000,
        branch="main",
        commit_sha="abc123def456",
    )
    db_session.add(build)
    db_session.commit()
    return build


@pytest.fixture
def sample_test(db_session, sample_job):
    """Create a sample test definition for testing."""
    test = Test(
        job_id=sample_job.id,
        name="test_addition",
        full_name="MathTests::ArithmeticSuite::test_addition",
        class_name="ArithmeticSuite",
        suite_name="MathTests",
        file_path="tests/math/test_arithmetic.cpp",
    )
    db_session.add(test)
    db_session.commit()
    return test


@pytest.fixture
def sample_ctest_xml():
    """Sample CTest XML content for testing."""
    return b'''<?xml version="1.0" encoding="UTF-8"?>
<Site BuildName="Linux-g++" Name="test-server" Generator="ctest-3.22.1">
  <Testing>
    <StartTestTime>1705339240</StartTestTime>
    <Test Status="passed">
      <Name>TestSuite::test_passing</Name>
      <Path>./tests</Path>
      <FullName>./tests/test_math</FullName>
      <FullCommandLine>/path/to/test --gtest_filter=TestSuite.test_passing</FullCommandLine>
      <Results>
        <NamedMeasurement type="numeric/double" name="Execution Time">
          <Value>0.123</Value>
        </NamedMeasurement>
        <NamedMeasurement type="numeric/double" name="Processors">
          <Value>1</Value>
        </NamedMeasurement>
        <Measurement>
          <Value>Test passed successfully</Value>
        </Measurement>
      </Results>
    </Test>
    <Test Status="failed">
      <Name>TestSuite::test_failing</Name>
      <Path>./tests</Path>
      <FullName>./tests/test_math</FullName>
      <FullCommandLine>/path/to/test --gtest_filter=TestSuite.test_failing</FullCommandLine>
      <Results>
        <NamedMeasurement type="numeric/double" name="Execution Time">
          <Value>0.456</Value>
        </NamedMeasurement>
        <NamedMeasurement type="numeric/double" name="Exit Code">
          <Value>1</Value>
        </NamedMeasurement>
        <Measurement>
          <Value>FAILED: Expected 5 but got 4</Value>
        </Measurement>
      </Results>
    </Test>
    <Test Status="notrun">
      <Name>TestSuite::test_skipped</Name>
      <Path>./tests</Path>
      <Results>
        <NamedMeasurement type="numeric/double" name="Execution Time">
          <Value>0</Value>
        </NamedMeasurement>
      </Results>
    </Test>
    <EndTestTime>1705339300</EndTestTime>
  </Testing>
</Site>'''


@pytest.fixture
def sample_junit_xml():
    """Sample JUnit XML content for testing."""
    return b'''<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="MathTests" tests="3" failures="1" skipped="1" errors="0" time="0.579">
    <testcase name="test_addition" classname="ArithmeticSuite" time="0.123" status="run"/>
    <testcase name="test_subtraction" classname="ArithmeticSuite" time="0.456" status="run">
      <failure message="Values differ" type="AssertionError">
Expected: 5
Actual: 4
      </failure>
    </testcase>
    <testcase name="test_skipped" classname="ArithmeticSuite" time="0.000" status="run">
      <skipped message="Not implemented yet"/>
    </testcase>
  </testsuite>
</testsuites>'''


@pytest.fixture
def sample_ctest_with_measurements():
    """CTest XML with various measurement types for testing."""
    return b'''<?xml version="1.0" encoding="UTF-8"?>
<Site BuildName="Linux-g++" Name="test-server" Generator="ctest-3.22.1">
  <Testing>
    <StartTestTime>1705339240</StartTestTime>
    <Test Status="passed">
      <Name>PerformanceTest::memory_benchmark</Name>
      <Path>./tests</Path>
      <Results>
        <NamedMeasurement type="numeric/double" name="Execution Time">
          <Value>5.432</Value>
        </NamedMeasurement>
        <NamedMeasurement type="numeric/double" name="Memory Usage">
          <Value>1048576</Value>
        </NamedMeasurement>
        <NamedMeasurement type="numeric/double" name="Processors">
          <Value>4</Value>
        </NamedMeasurement>
        <NamedMeasurement type="text/string" name="Completion Status">
          <Value>Completed</Value>
        </NamedMeasurement>
        <Measurement>
          <Value>Benchmark completed successfully</Value>
        </Measurement>
      </Results>
    </Test>
    <EndTestTime>1705339300</EndTestTime>
  </Testing>
</Site>'''
