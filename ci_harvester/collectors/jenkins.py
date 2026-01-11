"""
Jenkins CI Collector - Fetches builds and artifacts from Jenkins.

See docs/design/JENKINS_INTEGRATION.md for detailed documentation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin

import jenkins
import requests

from . import register_collector


@dataclass
class JenkinsConfig:
    """Configuration for Jenkins connection."""
    url: str
    username: str
    api_token: str
    job_filter: Optional[str] = None
    folder_depth: int = 3
    max_builds_per_job: int = 100
    collect_artifacts: bool = True
    artifact_patterns: List[str] = field(default_factory=list)
    timeout: int = 30
    verify_ssl: bool = True


@dataclass
class JenkinsJobInfo:
    """Discovered Jenkins job information."""
    full_name: str
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
    result: Optional[str]
    building: bool
    timestamp: int
    duration: int
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


@register_collector("jenkins")
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
    
    @classmethod
    def from_connection(cls, connection_id: str) -> "JenkinsCollector":
        """Create collector from Airflow connection."""
        # In production, this would fetch from Airflow's connection store
        import os
        
        config = JenkinsConfig(
            url=os.getenv("JENKINS_URL", ""),
            username=os.getenv("JENKINS_USERNAME", ""),
            api_token=os.getenv("JENKINS_API_TOKEN", ""),
            job_filter=os.getenv("JENKINS_JOB_FILTER"),
            folder_depth=int(os.getenv("JENKINS_FOLDER_DEPTH", 3)),
            max_builds_per_job=int(os.getenv("JENKINS_MAX_BUILDS", 100)),
            verify_ssl=os.getenv("JENKINS_VERIFY_SSL", "true").lower() == "true",
        )
        return cls(config)
    
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
        """Discover all jobs from Jenkins."""
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
        except Exception:
            return
        
        for item in items:
            job_class = item.get('_class', '')
            full_name = item.get('fullname', item.get('name', ''))
            
            if 'folder' in job_class.lower():
                self._discover_recursive(jobs, full_name, depth + 1)
            elif self._is_buildable_job(job_class):
                jobs.append(self._job_info_from_api(item, full_name))
    
    def _is_buildable_job(self, job_class: str) -> bool:
        """Check if the job class represents a buildable job."""
        buildable_classes = [
            'FreeStyleProject',
            'WorkflowJob',
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
        """Get builds for a job."""
        max_builds = limit or self.config.max_builds_per_job
        
        try:
            job_info = self._client.get_job_info(job_name, fetch_all_builds=True)
        except Exception as e:
            raise RuntimeError(f"Failed to get job info for {job_name}: {e}")
        
        builds = []
        all_builds = job_info.get('builds', [])[:max_builds]
        
        for build_ref in all_builds:
            build_number = build_ref['number']
            
            if since_build and build_number <= since_build:
                continue
            
            try:
                build_info = self._get_build_info(job_name, build_number)
                
                if since_time and build_info.timestamp:
                    build_time = datetime.fromtimestamp(build_info.timestamp / 1000)
                    if build_time < since_time:
                        continue
                
                builds.append(build_info)
            except Exception:
                continue
        
        return builds
    
    def _get_build_info(self, job_name: str, build_number: int) -> JenkinsBuildInfo:
        """Get detailed build information."""
        build_data = self._client.get_build_info(job_name, build_number)
        
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
    
    def get_console_log(self, job_name: str, build_number: int) -> str:
        """Get console log for a build."""
        try:
            return self._client.get_build_console_output(job_name, build_number)
        except Exception as e:
            raise RuntimeError(
                f"Failed to get console log for {job_name}#{build_number}: {e}"
            )
    
    def get_artifacts(self, job_name: str, build_number: int) -> List[JenkinsArtifact]:
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
                size=None,
                download_url=urljoin(base_url, f"artifact/{relative_path}")
            ))
        
        return artifacts
    
    def download_artifact(self, artifact: JenkinsArtifact) -> bytes:
        """Download artifact content."""
        response = self._session.get(
            artifact.download_url,
            timeout=self.config.timeout
        )
        response.raise_for_status()
        return response.content
    
    def download_artifact_by_url(self, url: str) -> bytes:
        """Download artifact by URL."""
        response = self._session.get(url, timeout=self.config.timeout)
        response.raise_for_status()
        return response.content
