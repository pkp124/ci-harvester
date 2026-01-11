# CI Harvester - Configuration

## 1. Overview

Configuration for CI Harvester covers:

1. **CI Sources** - Jenkins servers, credentials, job discovery
2. **Products** - Grouping of jobs, settings
3. **Jobs** - Which jobs to collect, artifact patterns
4. **Collection Settings** - Schedules, limits, patterns

## 2. Configuration Storage

```
┌─────────────────────────────────────────────────────────────────┐
│                    Configuration Sources                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Database   │  │  YAML File   │  │  Airflow     │          │
│  │   (runtime)  │  │  (bootstrap) │  │  Variables   │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│         │                 │                 │                   │
│         │    Products     │    Initial      │    Schedules      │
│         │    Jobs         │    Setup        │    Limits         │
│         │    Sources      │                 │    Secrets ref    │
│         │                 │                 │                   │
└─────────────────────────────────────────────────────────────────┘
```

### Where Configuration Lives

| What | Where | Why |
|------|-------|-----|
| CI Sources (Jenkins URLs) | Database + Airflow Connections | Credentials in Connections |
| Products | Database | Runtime management |
| Jobs & mappings | Database | Auto-discovered + manual |
| Artifact patterns | Database (per-job) or YAML (global) | Flexibility |
| Schedules | Airflow Variables | Airflow-native |
| Credentials | Airflow Connections | Secure storage |

## 3. Configuration File (Bootstrap)

Use YAML for initial setup, then manage via database/API.

```yaml
# config/ci_harvester.yaml

# =============================================================================
# CI Sources - Jenkins servers to connect to
# =============================================================================
ci_sources:
  - name: jenkins-main
    type: jenkins
    url: https://jenkins.example.com
    # Credentials reference Airflow Connection ID
    connection_id: jenkins_main
    
    # Job discovery settings
    discovery:
      # Include jobs matching these patterns
      include_patterns:
        - ".*-build$"
        - ".*-test$"
        - "^release/.*"
      
      # Exclude jobs matching these patterns  
      exclude_patterns:
        - ".*-experimental$"
        - "^sandbox/.*"
      
      # How deep to search in folders
      folder_depth: 3
    
    # Default settings for jobs from this source
    defaults:
      collect_logs: true
      max_log_size_mb: 50
      artifact_patterns:
        - "**/Test.xml"
        - "**/test-results.xml"
        - "**/*_test_results.xml"

  - name: jenkins-legacy
    type: jenkins
    url: https://legacy-jenkins.example.com
    connection_id: jenkins_legacy
    discovery:
      include_patterns:
        - "^legacy/.*"
    defaults:
      collect_logs: false  # Large logs, skip them

# =============================================================================
# Products - Group related jobs
# =============================================================================
products:
  - name: MyProduct
    description: Main product build and test pipeline
    repository_url: https://github.com/org/myproduct
    
    # Jobs belonging to this product
    jobs:
      # Pattern matching (auto-discovery)
      - pattern: "myproduct-.*"
        source: jenkins-main
      
      # Explicit job names
      - name: "myproduct-linux-build"
        source: jenkins-main
        settings:
          priority: high
          
      - name: "myproduct-windows-build"  
        source: jenkins-main
        settings:
          priority: high
          artifact_patterns:
            - "**/TestResults.xml"  # Windows uses different path
    
    # Product-level settings (override source defaults)
    settings:
      collect_logs: true
      max_builds_per_collection: 30

  - name: Platform
    description: Platform libraries
    jobs:
      - pattern: "platform-.*"
        source: jenkins-main
      - pattern: "^libs/.*"
        source: jenkins-main

  - name: Legacy
    description: Legacy system (collect less frequently)
    jobs:
      - pattern: ".*"
        source: jenkins-legacy
    settings:
      # Collect less frequently for legacy
      collection_interval_minutes: 30

# =============================================================================
# Global Settings
# =============================================================================
settings:
  # Default artifact patterns for test results
  test_artifact_patterns:
    - "**/Test.xml"
    - "**/test-results.xml"
    - "**/junit*.xml"
    - "**/TEST-*.xml"
    - "**/*_test_results.xml"
    - "**/ctest-*.xml"
  
  # CTest-specific patterns
  ctest_patterns:
    - "**/Testing/**/Test.xml"
    - "**/Testing/**/LastTest.log"
  
  # Log collection
  logs:
    enabled: true
    max_size_mb: 50
    # Truncate logs larger than this
    truncate_at_mb: 100
  
  # Collection defaults
  collection:
    max_builds_per_job: 20
    timeout_seconds: 300
    
  # Retention
  retention:
    test_results_days: 365
    build_logs_days: 90
    builds_days: 730
```

## 4. Database Models for Configuration

Configuration is stored in existing tables with JSONB fields:

```python
# In ci_harvester/db/models.py

class CISource(Base):
    """CI platform configuration."""
    __tablename__ = 'ci_sources'
    
    id = Column(UUID, primary_key=True)
    name = Column(String(255), unique=True)
    type = Column(String(50))  # 'jenkins', 'github_actions'
    url = Column(String(2048))
    connection_id = Column(String(255))  # Airflow Connection ID
    
    # Configuration stored as JSONB
    config = Column(JSONB, default={})
    # {
    #   "discovery": {
    #     "include_patterns": [".*-build$"],
    #     "exclude_patterns": [".*-experimental$"],
    #     "folder_depth": 3
    #   },
    #   "defaults": {
    #     "collect_logs": true,
    #     "max_log_size_mb": 50,
    #     "artifact_patterns": ["**/Test.xml"]
    #   }
    # }
    
    is_active = Column(Boolean, default=True)


class Product(Base):
    """Product with job associations."""
    __tablename__ = 'products'
    
    id = Column(UUID, primary_key=True)
    name = Column(String(255), unique=True)
    description = Column(Text)
    
    # Configuration stored as JSONB
    config = Column(JSONB, default={})
    # {
    #   "job_patterns": [
    #     {"pattern": "myproduct-.*", "source": "jenkins-main"}
    #   ],
    #   "settings": {
    #     "collect_logs": true,
    #     "priority": "high"
    #   }
    # }


class Job(Base):
    """Job with collection settings."""
    __tablename__ = 'jobs'
    
    id = Column(UUID, primary_key=True)
    product_id = Column(UUID, ForeignKey('products.id'))
    external_id = Column(String(1024))  # Jenkins job path
    name = Column(String(1024))
    ci_source = Column(String(50))
    
    # Job-specific configuration
    config = Column(JSONB, default={})
    # {
    #   "enabled": true,
    #   "priority": "normal",
    #   "collect_logs": true,
    #   "artifact_patterns": ["**/Test.xml"],
    #   "collection_interval_minutes": 5
    # }
```

## 5. Configuration Loader

```python
# ci_harvester/config.py

import os
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml
import fnmatch


class Config:
    """
    Configuration manager for CI Harvester.
    
    Loads from YAML file and provides merged settings.
    """
    
    _instance = None
    _config: Dict[str, Any] = {}
    
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.getenv(
                'CI_HARVESTER_CONFIG',
                '/etc/ci-harvester/config.yaml'
            )
        
        self._load(config_path)
    
    @classmethod
    def get(cls) -> 'Config':
        """Get singleton config instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def _load(self, path: str):
        """Load configuration from YAML file."""
        if Path(path).exists():
            with open(path) as f:
                self._config = yaml.safe_load(f) or {}
    
    # =========================================================================
    # CI Sources
    # =========================================================================
    
    def get_ci_sources(self) -> List[Dict[str, Any]]:
        """Get all CI source configurations."""
        return self._config.get('ci_sources', [])
    
    def get_ci_source(self, name: str) -> Optional[Dict[str, Any]]:
        """Get CI source by name."""
        for source in self.get_ci_sources():
            if source['name'] == name:
                return source
        return None
    
    # =========================================================================
    # Products
    # =========================================================================
    
    def get_products(self) -> List[Dict[str, Any]]:
        """Get all product configurations."""
        return self._config.get('products', [])
    
    def get_product(self, name: str) -> Optional[Dict[str, Any]]:
        """Get product by name."""
        for product in self.get_products():
            if product['name'] == name:
                return product
        return None
    
    # =========================================================================
    # Job Matching
    # =========================================================================
    
    def get_product_for_job(
        self, 
        job_name: str, 
        source_name: str
    ) -> Optional[str]:
        """
        Find which product a job belongs to.
        
        Matches against job patterns defined in products.
        """
        for product in self.get_products():
            for job_spec in product.get('jobs', []):
                # Check if source matches
                if job_spec.get('source') != source_name:
                    continue
                
                # Check pattern match
                if 'pattern' in job_spec:
                    import re
                    if re.match(job_spec['pattern'], job_name):
                        return product['name']
                
                # Check exact name match
                if job_spec.get('name') == job_name:
                    return product['name']
        
        return None
    
    def should_collect_job(
        self, 
        job_name: str, 
        source_name: str
    ) -> bool:
        """
        Check if a job should be collected.
        
        Based on include/exclude patterns in source config.
        """
        source = self.get_ci_source(source_name)
        if not source:
            return False
        
        discovery = source.get('discovery', {})
        include_patterns = discovery.get('include_patterns', ['.*'])
        exclude_patterns = discovery.get('exclude_patterns', [])
        
        import re
        
        # Check excludes first
        for pattern in exclude_patterns:
            if re.match(pattern, job_name):
                return False
        
        # Check includes
        for pattern in include_patterns:
            if re.match(pattern, job_name):
                return True
        
        return False
    
    # =========================================================================
    # Artifact Patterns
    # =========================================================================
    
    def get_test_artifact_patterns(
        self, 
        job_name: Optional[str] = None,
        product_name: Optional[str] = None,
        source_name: Optional[str] = None
    ) -> List[str]:
        """
        Get artifact patterns for test results.
        
        Merges patterns from: global -> source -> product -> job
        """
        patterns = set()
        
        # Global defaults
        settings = self._config.get('settings', {})
        patterns.update(settings.get('test_artifact_patterns', []))
        patterns.update(settings.get('ctest_patterns', []))
        
        # Source defaults
        if source_name:
            source = self.get_ci_source(source_name)
            if source:
                defaults = source.get('defaults', {})
                patterns.update(defaults.get('artifact_patterns', []))
        
        # Product overrides
        if product_name:
            product = self.get_product(product_name)
            if product:
                prod_settings = product.get('settings', {})
                if 'artifact_patterns' in prod_settings:
                    patterns.update(prod_settings['artifact_patterns'])
        
        return list(patterns)
    
    def is_test_artifact(
        self, 
        filename: str,
        patterns: Optional[List[str]] = None
    ) -> bool:
        """Check if a file matches test artifact patterns."""
        if patterns is None:
            patterns = self.get_test_artifact_patterns()
        
        for pattern in patterns:
            if fnmatch.fnmatch(filename, pattern):
                return True
            # Also check just the filename part
            if fnmatch.fnmatch(os.path.basename(filename), pattern):
                return True
        
        return False
    
    # =========================================================================
    # Collection Settings
    # =========================================================================
    
    def get_collection_settings(
        self, 
        job_name: Optional[str] = None,
        product_name: Optional[str] = None,
        source_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get merged collection settings.
        
        Priority: job -> product -> source -> global
        """
        settings = {
            'enabled': True,
            'collect_logs': True,
            'max_log_size_mb': 50,
            'max_builds_per_collection': 20,
            'timeout_seconds': 300,
            'priority': 'normal',
        }
        
        # Global settings
        global_settings = self._config.get('settings', {})
        collection = global_settings.get('collection', {})
        logs = global_settings.get('logs', {})
        
        settings['max_builds_per_collection'] = collection.get(
            'max_builds_per_job', 
            settings['max_builds_per_collection']
        )
        settings['collect_logs'] = logs.get('enabled', settings['collect_logs'])
        settings['max_log_size_mb'] = logs.get(
            'max_size_mb', 
            settings['max_log_size_mb']
        )
        
        # Source defaults
        if source_name:
            source = self.get_ci_source(source_name)
            if source:
                defaults = source.get('defaults', {})
                settings.update({
                    k: v for k, v in defaults.items() 
                    if k in settings
                })
        
        # Product settings
        if product_name:
            product = self.get_product(product_name)
            if product:
                prod_settings = product.get('settings', {})
                settings.update({
                    k: v for k, v in prod_settings.items() 
                    if k in settings
                })
        
        return settings
```

## 6. Using Configuration in DAGs

```python
# dags/collect_builds.py

from ci_harvester.config import Config

@task
def get_jobs_to_collect() -> list:
    """Get jobs based on configuration."""
    config = Config.get()
    
    with get_session() as session:
        jobs = []
        
        for source in config.get_ci_sources():
            # Query jobs from this source
            source_jobs = session.query(Job).filter(
                Job.ci_source == source['name'],
                Job.is_active == True
            ).all()
            
            for job in source_jobs:
                # Check if should collect
                if not config.should_collect_job(job.name, source['name']):
                    continue
                
                # Get settings
                settings = config.get_collection_settings(
                    job_name=job.name,
                    product_name=job.product.name if job.product else None,
                    source_name=source['name']
                )
                
                if not settings['enabled']:
                    continue
                
                jobs.append({
                    'id': str(job.id),
                    'name': job.name,
                    'external_id': job.external_id,
                    'ci_source': job.ci_source,
                    'settings': settings,
                    'artifact_patterns': config.get_test_artifact_patterns(
                        job_name=job.name,
                        product_name=job.product.name if job.product else None,
                        source_name=source['name']
                    )
                })
        
        # Sort by last_collected (oldest first)
        jobs.sort(key=lambda j: j.get('last_collected') or '')
        
        return jobs[:config.get_max_jobs_per_run()]

@task
def collect_job(job: dict) -> dict:
    """Collect builds for a job using its settings."""
    settings = job['settings']
    
    collector = get_collector(job['ci_source'])
    
    builds = collector.get_builds(
        job['external_id'],
        limit=settings['max_builds_per_collection']
    )
    
    for build in builds:
        # Collect logs if enabled
        if settings['collect_logs']:
            log = collector.get_console_log(
                job['external_id'],
                build.number,
                max_size=settings['max_log_size_mb'] * 1024 * 1024
            )
        
        # Check artifacts against patterns
        artifacts = collector.get_artifacts(job['external_id'], build.number)
        for artifact in artifacts:
            is_test = Config.get().is_test_artifact(
                artifact.file_name,
                job['artifact_patterns']
            )
```

## 7. API for Configuration Management

```python
# Future: REST API for managing configuration

# Get all CI sources
GET /api/v1/config/sources

# Add/update CI source
PUT /api/v1/config/sources/jenkins-main
{
    "url": "https://jenkins.example.com",
    "connection_id": "jenkins_main",
    "discovery": {
        "include_patterns": [".*-build$"]
    }
}

# Get all products
GET /api/v1/config/products

# Update product job patterns
PATCH /api/v1/config/products/MyProduct
{
    "jobs": [
        {"pattern": "myproduct-.*", "source": "jenkins-main"}
    ]
}

# Update job settings
PATCH /api/v1/jobs/{job_id}/config
{
    "enabled": true,
    "priority": "high",
    "artifact_patterns": ["**/CustomTest.xml"]
}
```

## 8. Bootstrap Process

```bash
# 1. Create Airflow Connections for credentials
airflow connections add jenkins_main \
    --conn-type http \
    --conn-host jenkins.example.com \
    --conn-port 443 \
    --conn-schema https \
    --conn-login ci-harvester \
    --conn-password "api-token-here"

# 2. Create config file
cp config/ci_harvester.yaml.example /etc/ci-harvester/config.yaml
# Edit with your settings

# 3. Initialize database with config
python -m ci_harvester.config.bootstrap

# 4. Set Airflow Variables for schedules
airflow variables set collection_schedule "*/5 * * * *"
airflow variables set discovery_schedule "*/10 * * * *"

# 5. Enable DAGs
airflow dags unpause discover_jobs
airflow dags unpause collect_builds
```
