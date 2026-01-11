"""
Pytest configuration and fixtures for CI Harvester tests.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ci_harvester.db.models import Base


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
def sample_ctest_xml():
    """Sample CTest XML content for testing."""
    return b'''<?xml version="1.0" encoding="UTF-8"?>
<Site BuildName="Linux-g++" Name="test-server" Generator="ctest-3.22.1">
  <Testing>
    <StartTestTime>1705339240</StartTestTime>
    <Test Status="passed">
      <Name>TestSuite::test_passing</Name>
      <Path>./tests</Path>
      <Results>
        <NamedMeasurement type="numeric/double" name="Execution Time">
          <Value>0.123</Value>
        </NamedMeasurement>
        <Measurement>
          <Value>Test passed successfully</Value>
        </Measurement>
      </Results>
    </Test>
    <Test Status="failed">
      <Name>TestSuite::test_failing</Name>
      <Path>./tests</Path>
      <Results>
        <NamedMeasurement type="numeric/double" name="Execution Time">
          <Value>0.456</Value>
        </NamedMeasurement>
        <Measurement>
          <Value>FAILED: Expected 5 but got 4</Value>
        </Measurement>
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
  <testsuite name="TestSuite" tests="3" failures="1" skipped="1" errors="0" time="0.579">
    <testcase name="test_passing" classname="TestClass" time="0.123" status="run"/>
    <testcase name="test_failing" classname="TestClass" time="0.456" status="run">
      <failure message="Values differ" type="AssertionError">
Expected: 5
Actual: 4
      </failure>
    </testcase>
    <testcase name="test_skipped" classname="TestClass" time="0.000" status="run">
      <skipped message="Not implemented yet"/>
    </testcase>
  </testsuite>
</testsuites>'''
