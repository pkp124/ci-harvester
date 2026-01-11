# CI Harvester - Jenkins Integration

## 1. Overview

This document describes the integration with Jenkins CI server for harvesting build logs and test results. Jenkins is the primary CI platform supported by CI Harvester.

## 2. Jenkins API Overview

### 2.1 API Endpoints Used

| Endpoint | Purpose | Method |
|----------|---------|--------|
| `/api/json` | Server info and job list | GET |
| `/job/{name}/api/json` | Job details | GET |
| `/job/{name}/{build}/api/json` | Build details | GET |
| `/job/{name}/{build}/consoleText` | Console log (plain text) | GET |
| `/job/{name}/{build}/logText/progressiveText` | Streaming log | GET |
| `/job/{name}/{build}/artifact/{path}` | Download artifact | GET |
| `/job/{name}/{build}/testReport/api/json` | Test report (if available) | GET |

### 2.2 Authentication Methods

1. **API Token** (Recommended)
   - Generate in Jenkins: User → Configure → API Token
   - Use with HTTP Basic Auth: `username:api_token`

2. **Username/Password**
   - HTTP Basic Auth with actual password
   - Less secure, may not work with SSO

3. **Session Cookie**
   - For environments with special auth (Kerberos, etc.)
   - Requires browser login flow

## 3. Collector Implementation

### 3.1 Class Design

```python
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any
import jenkins
import requests
from urllib.parse import urljoin

@dataclass
class JenkinsConfig:
    """Configuration for Jenkins connection."""
    url: str
    username: str
    api_token: str
    job_filter: Optional[str] = None  # Regex pattern
    folder_depth: int = 3  # How deep to search folders
    max_builds_per_job: int = 100
    collect_artifacts: bool = True
    artifact_patterns: List[str] = None  # Glob patterns for artifacts
    timeout: int = 30
    verify_ssl: bool = True

@dataclass  
class JenkinsJobInfo:
    """Discovered Jenkins job information."""
    full_name: str  # e.g., "folder/subfolder/job-name"
    name: str
    url: str
    job_class: str
    buildable: bool
    last_build_number: Optional[int]
    metadata: Dict[str, Any]

@dataclass
class JenkinsBuildInfo:
    """Jenkins build information."""
    number: int
    url: str
    result: Optional[str]  # SUCCESS, FAILURE, UNSTABLE, ABORTED
    building: bool
    timestamp: int  # Unix timestamp in ms
    duration: int  # Duration in ms
    executor: Optional[str]
    causes: List[Dict[str, Any]]
    parameters: Dict[str, str]
    change_sets: List[Dict[str, Any]]
    metadata: Dict[str, Any]

@dataclass
class JenkinsArtifact:
    """Jenkins build artifact."""
    file_name: str
    relative_path: str
    size: Optional[int]
    download_url: str


class JenkinsCollector:
    """Collector for Jenkins CI jobs and builds."""
    
    def __init__(self, config: JenkinsConfig):
        self.config = config
        self._client = jenkins.Jenkins(
            url=config.url,
            username=config.username,
            password=config.api_token,
            timeout=config.timeout
        )
        self._session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        """Create authenticated requests session."""
        session = requests.Session()
        session.auth = (self.config.username, self.config.api_token)
        session.verify = self.config.verify_ssl
        session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'CI-Harvester/1.0'
        })
        return session
    
    def test_connection(self) -> bool:
        """Test connectivity to Jenkins server."""
        try:
            self._client.get_whoami()
            return True
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Jenkins: {e}")
    
    def discover_jobs(self) -> List[JenkinsJobInfo]:
        """
        Discover all jobs from Jenkins.
        
        Handles:
        - Freestyle jobs
        - Pipeline jobs  
        - Multibranch pipelines
        - Folder hierarchies
        """
        jobs = []
        self._discover_recursive(jobs, "", 0)
        
        # Apply filter if configured
        if self.config.job_filter:
            import re
            pattern = re.compile(self.config.job_filter)
            jobs = [j for j in jobs if pattern.match(j.full_name)]
        
        return jobs
    
    def _discover_recursive(
        self, 
        jobs: List[JenkinsJobInfo], 
        folder_path: str,
        depth: int
    ):
        """Recursively discover jobs in folders."""
        if depth > self.config.folder_depth:
            return
        
        try:
            if folder_path:
                folder_info = self._client.get_job_info(folder_path)
                items = folder_info.get('jobs', [])
            else:
                items = self._client.get_all_jobs()
        except Exception as e:
            # Log and continue
            return
        
        for item in items:
            job_class = item.get('_class', '')
            full_name = item.get('fullname', item.get('name', ''))
            
            # Check if this is a folder
            if 'folder' in job_class.lower():
                self._discover_recursive(jobs, full_name, depth + 1)
            elif self._is_buildable_job(job_class):
                jobs.append(self._job_info_from_api(item, full_name))
    
    def _is_buildable_job(self, job_class: str) -> bool:
        """Check if the job class represents a buildable job."""
        buildable_classes = [
            'FreeStyleProject',
            'WorkflowJob',  # Pipeline
            'WorkflowMultiBranchProject',
            'MatrixProject',
            'MavenModuleSet'
        ]
        return any(c in job_class for c in buildable_classes)
    
    def _job_info_from_api(
        self, 
        api_data: Dict[str, Any],
        full_name: str
    ) -> JenkinsJobInfo:
        """Convert API response to JenkinsJobInfo."""
        last_build = api_data.get('lastBuild')
        return JenkinsJobInfo(
            full_name=full_name,
            name=api_data.get('name', full_name.split('/')[-1]),
            url=api_data.get('url', ''),
            job_class=api_data.get('_class', 'unknown'),
            buildable=api_data.get('buildable', True),
            last_build_number=last_build.get('number') if last_build else None,
            metadata={
                'color': api_data.get('color'),
                'description': api_data.get('description'),
                'in_queue': api_data.get('inQueue', False)
            }
        )
    
    def get_builds(
        self, 
        job_name: str, 
        since_build: Optional[int] = None,
        since_time: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> List[JenkinsBuildInfo]:
        """
        Get builds for a job.
        
        Args:
            job_name: Full job name (path)
            since_build: Only get builds after this number
            since_time: Only get builds after this time
            limit: Maximum builds to return
        """
        max_builds = limit or self.config.max_builds_per_job
        
        try:
            job_info = self._client.get_job_info(
                job_name,
                fetch_all_builds=True
            )
        except Exception as e:
            raise RuntimeError(f"Failed to get job info for {job_name}: {e}")
        
        builds = []
        all_builds = job_info.get('builds', [])[:max_builds]
        
        for build_ref in all_builds:
            build_number = build_ref['number']
            
            # Skip if before since_build
            if since_build and build_number <= since_build:
                continue
            
            try:
                build_info = self._get_build_info(job_name, build_number)
                
                # Skip if before since_time
                if since_time and build_info.timestamp:
                    build_time = datetime.fromtimestamp(build_info.timestamp / 1000)
                    if build_time < since_time:
                        continue
                
                builds.append(build_info)
            except Exception as e:
                # Log and continue with other builds
                continue
        
        return builds
    
    def _get_build_info(
        self, 
        job_name: str, 
        build_number: int
    ) -> JenkinsBuildInfo:
        """Get detailed build information."""
        build_data = self._client.get_build_info(job_name, build_number)
        
        # Extract causes from actions
        causes = []
        parameters = {}
        for action in build_data.get('actions', []):
            if 'causes' in action:
                causes.extend(action['causes'])
            if 'parameters' in action:
                for param in action['parameters']:
                    parameters[param['name']] = str(param.get('value', ''))
        
        return JenkinsBuildInfo(
            number=build_number,
            url=build_data.get('url', ''),
            result=build_data.get('result'),
            building=build_data.get('building', False),
            timestamp=build_data.get('timestamp', 0),
            duration=build_data.get('duration', 0),
            executor=build_data.get('builtOn'),
            causes=causes,
            parameters=parameters,
            change_sets=build_data.get('changeSets', []),
            metadata={
                'id': build_data.get('id'),
                'display_name': build_data.get('displayName'),
                'full_display_name': build_data.get('fullDisplayName'),
                'estimated_duration': build_data.get('estimatedDuration')
            }
        )
    
    def get_console_log(
        self, 
        job_name: str, 
        build_number: int,
        start_offset: int = 0
    ) -> str:
        """
        Get console log for a build.
        
        Args:
            job_name: Full job name
            build_number: Build number
            start_offset: Start reading from this byte offset
        """
        try:
            log = self._client.get_build_console_output(job_name, build_number)
            return log
        except Exception as e:
            raise RuntimeError(
                f"Failed to get console log for {job_name}#{build_number}: {e}"
            )
    
    def get_artifacts(
        self, 
        job_name: str, 
        build_number: int
    ) -> List[JenkinsArtifact]:
        """Get list of artifacts for a build."""
        try:
            build_info = self._client.get_build_info(job_name, build_number)
        except Exception as e:
            raise RuntimeError(f"Failed to get build info: {e}")
        
        artifacts = []
        base_url = build_info.get('url', '')
        
        for artifact in build_info.get('artifacts', []):
            file_name = artifact.get('fileName', '')
            relative_path = artifact.get('relativePath', file_name)
            
            # Apply pattern filter if configured
            if self.config.artifact_patterns:
                import fnmatch
                if not any(
                    fnmatch.fnmatch(relative_path, p) 
                    for p in self.config.artifact_patterns
                ):
                    continue
            
            artifacts.append(JenkinsArtifact(
                file_name=file_name,
                relative_path=relative_path,
                size=None,  # Not available in API
                download_url=urljoin(base_url, f"artifact/{relative_path}")
            ))
        
        return artifacts
    
    def download_artifact(
        self, 
        artifact: JenkinsArtifact
    ) -> bytes:
        """Download artifact content."""
        response = self._session.get(
            artifact.download_url,
            timeout=self.config.timeout
        )
        response.raise_for_status()
        return response.content
    
    def get_test_report(
        self, 
        job_name: str, 
        build_number: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get Jenkins test report if available.
        
        Note: This returns Jenkins' native test report format.
        For CTest results, use artifact download instead.
        """
        url = urljoin(
            self.config.url,
            f"/job/{job_name}/{build_number}/testReport/api/json"
        )
        
        try:
            response = self._session.get(url, timeout=self.config.timeout)
            if response.status_code == 404:
                return None  # No test report
            response.raise_for_status()
            return response.json()
        except Exception:
            return None
```

### 3.2 Rate Limiting

```python
from ratelimit import limits, sleep_and_retry

class RateLimitedJenkinsCollector(JenkinsCollector):
    """Jenkins collector with rate limiting."""
    
    # 100 requests per minute
    @sleep_and_retry
    @limits(calls=100, period=60)
    def _rate_limited_request(self, method, *args, **kwargs):
        return method(*args, **kwargs)
    
    def get_builds(self, *args, **kwargs):
        return self._rate_limited_request(
            super().get_builds, *args, **kwargs
        )
```

### 3.3 Error Handling

```python
class JenkinsError(Exception):
    """Base exception for Jenkins errors."""
    pass

class JenkinsConnectionError(JenkinsError):
    """Failed to connect to Jenkins."""
    pass

class JenkinsAuthError(JenkinsError):
    """Authentication failed."""
    pass

class JenkinsNotFoundError(JenkinsError):
    """Job or build not found."""
    pass

class JenkinsRateLimitError(JenkinsError):
    """Rate limit exceeded."""
    pass
```

## 4. Configuration

### 4.1 Environment Variables

```bash
# Required
JENKINS_URL=https://jenkins.example.com
JENKINS_USERNAME=ci-harvester
JENKINS_API_TOKEN=secret-token

# Optional
JENKINS_JOB_FILTER=.*-build$
JENKINS_FOLDER_DEPTH=3
JENKINS_MAX_BUILDS=100
JENKINS_VERIFY_SSL=true
JENKINS_TIMEOUT=30
```

### 4.2 Airflow Connection

```python
# Create connection in Airflow
from airflow.models import Connection

conn = Connection(
    conn_id='jenkins_main',
    conn_type='http',
    host='jenkins.example.com',
    port=443,
    login='ci-harvester',
    password='api-token',
    schema='https',
    extra={
        'job_filter': '.*',
        'max_builds_per_job': 100,
        'verify_ssl': True
    }
)
```

## 5. CTest Artifact Discovery

### 5.1 CTest Output Locations

CTest generates test results in several locations:

```
build/
├── Testing/
│   ├── TAG                     # Current test tag
│   ├── Temporary/
│   │   ├── LastTest.log        # Detailed test output
│   │   ├── CTestCostData.txt   # Test timing data
│   │   └── ...
│   └── 20240115-1234/          # Tagged results directory
│       ├── Test.xml            # Main test results
│       ├── Configure.xml       # Configure step results
│       ├── Build.xml           # Build step results
│       └── Update.xml          # Update step results
└── ...
```

### 5.2 Recommended Jenkins Artifact Archival

Configure Jenkins jobs to archive CTest results:

```groovy
// Jenkinsfile
pipeline {
    stages {
        stage('Test') {
            steps {
                sh 'ctest --output-on-failure --output-junit test-results.xml'
            }
        }
    }
    post {
        always {
            archiveArtifacts artifacts: 'build/Testing/**/*.xml', allowEmptyArchive: true
            archiveArtifacts artifacts: 'build/test-results.xml', allowEmptyArchive: true
        }
    }
}
```

### 5.3 Artifact Patterns for CTest

```python
CTEST_ARTIFACT_PATTERNS = [
    'Testing/**/*.xml',
    'Testing/**/LastTest.log',
    '**/test-results.xml',
    '**/Test.xml',
    '**/*_test_results.xml'
]
```

## 6. Pipeline Job Support

### 6.1 Blue Ocean API

For Pipeline jobs, additional data is available via Blue Ocean REST API:

```
/blue/rest/organizations/jenkins/pipelines/{job}/runs/{build}/
/blue/rest/organizations/jenkins/pipelines/{job}/runs/{build}/nodes/
/blue/rest/organizations/jenkins/pipelines/{job}/runs/{build}/steps/
```

### 6.2 Stage-Level Logs

```python
def get_pipeline_stages(
    self, 
    job_name: str, 
    build_number: int
) -> List[Dict[str, Any]]:
    """Get pipeline stage details for a build."""
    # Use Blue Ocean API
    url = urljoin(
        self.config.url,
        f"/blue/rest/organizations/jenkins/pipelines/"
        f"{job_name.replace('/', '%2F')}/runs/{build_number}/nodes/"
    )
    
    response = self._session.get(url)
    if response.status_code == 404:
        return []  # Not a pipeline job
    response.raise_for_status()
    return response.json()

def get_stage_log(
    self, 
    job_name: str, 
    build_number: int,
    node_id: str
) -> str:
    """Get log for a specific pipeline stage."""
    url = urljoin(
        self.config.url,
        f"/blue/rest/organizations/jenkins/pipelines/"
        f"{job_name.replace('/', '%2F')}/runs/{build_number}/"
        f"nodes/{node_id}/log/"
    )
    
    response = self._session.get(url)
    response.raise_for_status()
    return response.text
```

## 7. Multibranch Pipeline Support

### 7.1 Branch Discovery

```python
def get_multibranch_branches(
    self, 
    job_name: str
) -> List[JenkinsJobInfo]:
    """Get branches for a multibranch pipeline."""
    job_info = self._client.get_job_info(job_name)
    
    branches = []
    for job in job_info.get('jobs', []):
        branch_name = job.get('name')
        full_name = f"{job_name}/{branch_name}"
        branches.append(self._job_info_from_api(job, full_name))
    
    return branches
```

## 8. Webhook Support (Future)

### 8.1 Jenkins Notification Plugin

Configure Jenkins to send webhooks on build events:

```groovy
// Jenkinsfile
post {
    always {
        httpRequest(
            url: 'https://ci-harvester.example.com/webhook/jenkins',
            httpMode: 'POST',
            contentType: 'APPLICATION_JSON',
            requestBody: """{
                "job": "${env.JOB_NAME}",
                "build": ${env.BUILD_NUMBER},
                "result": "${currentBuild.result}"
            }"""
        )
    }
}
```

### 8.2 Webhook Handler

```python
from fastapi import FastAPI, Request

@app.post("/webhook/jenkins")
async def jenkins_webhook(request: Request):
    """Handle Jenkins build completion webhook."""
    payload = await request.json()
    
    # Trigger immediate collection for this build
    job_name = payload['job']
    build_number = payload['build']
    
    # Queue Airflow task
    trigger_dag_run(
        dag_id='collect_single_build',
        conf={
            'source': 'jenkins',
            'job': job_name,
            'build': build_number
        }
    )
    
    return {"status": "queued"}
```

## 9. Security Considerations

### 9.1 Credential Storage

- Store API tokens in Airflow Connections (encrypted)
- Use environment variables for local development
- Support external secrets (Vault, AWS Secrets Manager)

### 9.2 Network Security

- Always use HTTPS in production
- Verify SSL certificates (configurable for self-signed)
- Consider VPN or network isolation

### 9.3 Permissions

Minimum Jenkins permissions required:
- `Overall/Read` - View Jenkins
- `Job/Read` - View jobs
- `Job/ExtendedRead` - View job configs (optional)
- `Run/Artifacts` - Download artifacts
- No write permissions needed

## 10. Testing

### 10.1 Unit Tests

```python
import pytest
from unittest.mock import Mock, patch

class TestJenkinsCollector:
    
    @pytest.fixture
    def collector(self):
        config = JenkinsConfig(
            url='https://jenkins.example.com',
            username='test',
            api_token='token'
        )
        return JenkinsCollector(config)
    
    @patch('jenkins.Jenkins')
    def test_discover_jobs(self, mock_jenkins, collector):
        mock_jenkins.return_value.get_all_jobs.return_value = [
            {
                'name': 'test-job',
                'fullname': 'test-job',
                '_class': 'WorkflowJob',
                'url': 'https://jenkins/job/test-job/',
                'buildable': True,
                'lastBuild': {'number': 42}
            }
        ]
        
        jobs = collector.discover_jobs()
        
        assert len(jobs) == 1
        assert jobs[0].name == 'test-job'
```

### 10.2 Integration Tests

```python
@pytest.mark.integration
class TestJenkinsIntegration:
    
    @pytest.fixture
    def real_collector(self):
        """Uses real Jenkins server (requires env vars)."""
        config = JenkinsConfig(
            url=os.environ['TEST_JENKINS_URL'],
            username=os.environ['TEST_JENKINS_USER'],
            api_token=os.environ['TEST_JENKINS_TOKEN']
        )
        return JenkinsCollector(config)
    
    def test_connection(self, real_collector):
        assert real_collector.test_connection() is True
    
    def test_discover_jobs(self, real_collector):
        jobs = real_collector.discover_jobs()
        assert len(jobs) > 0
```
