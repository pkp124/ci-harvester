"""
Tests for Jenkins collector.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from ci_harvester.collectors.jenkins import (
    JenkinsCollector,
    JenkinsConfig,
    JenkinsJobInfo,
    JenkinsBuildInfo,
)


class TestJenkinsCollector:
    """Tests for JenkinsCollector."""
    
    @pytest.fixture
    def config(self):
        return JenkinsConfig(
            url="https://jenkins.example.com",
            username="test-user",
            api_token="test-token",
            max_builds_per_job=10,
        )
    
    @pytest.fixture
    def mock_jenkins(self):
        with patch('ci_harvester.collectors.jenkins.jenkins.Jenkins') as mock:
            yield mock
    
    @pytest.fixture
    def collector(self, config, mock_jenkins):
        return JenkinsCollector(config)
    
    def test_test_connection_success(self, collector, mock_jenkins):
        """Test successful connection test."""
        mock_jenkins.return_value.get_whoami.return_value = {"id": "test-user"}
        
        result = collector.test_connection()
        
        assert result is True
    
    def test_test_connection_failure(self, collector, mock_jenkins):
        """Test connection failure."""
        mock_jenkins.return_value.get_whoami.side_effect = Exception("Connection failed")
        
        with pytest.raises(ConnectionError):
            collector.test_connection()
    
    def test_discover_jobs(self, collector, mock_jenkins):
        """Test job discovery."""
        mock_jenkins.return_value.get_all_jobs.return_value = [
            {
                'name': 'test-job',
                'fullname': 'test-job',
                '_class': 'org.jenkinsci.plugins.workflow.job.WorkflowJob',
                'url': 'https://jenkins.example.com/job/test-job/',
                'buildable': True,
                'lastBuild': {'number': 42},
                'color': 'blue',
            }
        ]
        
        jobs = collector.discover_jobs()
        
        assert len(jobs) == 1
        assert jobs[0].name == 'test-job'
        assert jobs[0].full_name == 'test-job'
        assert jobs[0].last_build_number == 42
    
    def test_discover_jobs_with_filter(self, mock_jenkins):
        """Test job discovery with filter."""
        config = JenkinsConfig(
            url="https://jenkins.example.com",
            username="test-user",
            api_token="test-token",
            job_filter=".*-build$",
        )
        collector = JenkinsCollector(config)
        
        mock_jenkins.return_value.get_all_jobs.return_value = [
            {
                'name': 'test-build',
                'fullname': 'test-build',
                '_class': 'WorkflowJob',
            },
            {
                'name': 'test-deploy',
                'fullname': 'test-deploy',
                '_class': 'WorkflowJob',
            },
        ]
        
        jobs = collector.discover_jobs()
        
        assert len(jobs) == 1
        assert jobs[0].name == 'test-build'
    
    def test_get_builds(self, collector, mock_jenkins):
        """Test getting builds for a job."""
        mock_jenkins.return_value.get_job_info.return_value = {
            'builds': [
                {'number': 3, 'url': 'https://jenkins.example.com/job/test/3/'},
                {'number': 2, 'url': 'https://jenkins.example.com/job/test/2/'},
                {'number': 1, 'url': 'https://jenkins.example.com/job/test/1/'},
            ]
        }
        mock_jenkins.return_value.get_build_info.return_value = {
            'number': 3,
            'url': 'https://jenkins.example.com/job/test/3/',
            'result': 'SUCCESS',
            'building': False,
            'timestamp': 1705339240000,
            'duration': 60000,
            'builtOn': 'agent-01',
            'actions': [],
            'changeSets': [],
        }
        
        builds = collector.get_builds('test-job')
        
        assert len(builds) >= 1
        assert builds[0].number == 3
        assert builds[0].result == 'SUCCESS'
    
    def test_get_console_log(self, collector, mock_jenkins):
        """Test getting console log."""
        expected_log = "Build started...\nBuild completed."
        mock_jenkins.return_value.get_build_console_output.return_value = expected_log
        
        log = collector.get_console_log('test-job', 42)
        
        assert log == expected_log
    
    def test_get_artifacts(self, collector, mock_jenkins):
        """Test getting build artifacts."""
        mock_jenkins.return_value.get_build_info.return_value = {
            'url': 'https://jenkins.example.com/job/test/42/',
            'artifacts': [
                {'fileName': 'Test.xml', 'relativePath': 'build/Testing/Test.xml'},
                {'fileName': 'coverage.xml', 'relativePath': 'coverage.xml'},
            ]
        }
        
        artifacts = collector.get_artifacts('test-job', 42)
        
        assert len(artifacts) == 2
        assert artifacts[0].file_name == 'Test.xml'
        assert 'artifact/build/Testing/Test.xml' in artifacts[0].download_url
