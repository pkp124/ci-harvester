"""
Configuration management for CI Harvester.

Loads configuration from:
1. YAML configuration file (bootstrap/static config)
2. Database (runtime config for products, jobs)
3. Airflow Variables (schedules, limits)

See docs/design/CONFIGURATION.md for detailed documentation.
"""

import os
import re
import fnmatch
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

import yaml


@dataclass
class CISourceConfig:
    """Configuration for a CI source (e.g., Jenkins server)."""
    name: str
    type: str  # 'jenkins', 'github_actions'
    url: str
    connection_id: str  # Airflow Connection ID for credentials
    
    # Discovery settings
    include_patterns: List[str] = field(default_factory=lambda: ['.*'])
    exclude_patterns: List[str] = field(default_factory=list)
    folder_depth: int = 3
    
    # Default settings for jobs from this source
    collect_logs: bool = True
    max_log_size_mb: int = 50
    artifact_patterns: List[str] = field(default_factory=list)
    
    def should_include_job(self, job_name: str) -> bool:
        """Check if a job should be included based on patterns."""
        # Check excludes first
        for pattern in self.exclude_patterns:
            if re.match(pattern, job_name):
                return False
        
        # Check includes
        for pattern in self.include_patterns:
            if re.match(pattern, job_name):
                return True
        
        return False


@dataclass
class ProductConfig:
    """Configuration for a product."""
    name: str
    description: str = ""
    repository_url: Optional[str] = None
    
    # Job patterns: list of {"pattern": "...", "source": "...", "settings": {...}}
    job_patterns: List[Dict[str, Any]] = field(default_factory=list)
    
    # Product-level settings
    priority: str = "normal"
    collect_logs: bool = True
    max_builds_per_collection: int = 20


@dataclass 
class CollectionSettings:
    """Merged collection settings for a job."""
    enabled: bool = True
    priority: str = "normal"
    collect_logs: bool = True
    max_log_size_mb: int = 50
    max_builds_per_collection: int = 20
    timeout_seconds: int = 300
    artifact_patterns: List[str] = field(default_factory=list)


class Config:
    """
    Configuration manager for CI Harvester.
    
    Usage:
        config = Config.load()
        sources = config.get_ci_sources()
        patterns = config.get_artifact_patterns("my-job", "MyProduct", "jenkins-main")
    """
    
    _instance: Optional['Config'] = None
    
    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._ci_sources: Dict[str, CISourceConfig] = {}
        self._products: Dict[str, ProductConfig] = {}
    
    @classmethod
    def load(cls, config_path: Optional[str] = None) -> 'Config':
        """
        Load configuration from file.
        
        Args:
            config_path: Path to YAML config file. 
                         Defaults to CI_HARVESTER_CONFIG env var or /etc/ci-harvester/config.yaml
        """
        instance = cls()
        
        if config_path is None:
            config_path = os.getenv(
                'CI_HARVESTER_CONFIG',
                '/etc/ci-harvester/config.yaml'
            )
        
        path = Path(config_path)
        if path.exists():
            with open(path) as f:
                instance._config = yaml.safe_load(f) or {}
            instance._parse_config()
        
        return instance
    
    @classmethod
    def get(cls) -> 'Config':
        """Get singleton config instance."""
        if cls._instance is None:
            cls._instance = cls.load()
        return cls._instance
    
    @classmethod
    def reload(cls) -> 'Config':
        """Reload configuration from file."""
        cls._instance = cls.load()
        return cls._instance
    
    def _parse_config(self):
        """Parse raw config into typed objects."""
        # Parse CI sources
        for source_data in self._config.get('ci_sources', []):
            discovery = source_data.get('discovery', {})
            defaults = source_data.get('defaults', {})
            
            source = CISourceConfig(
                name=source_data['name'],
                type=source_data['type'],
                url=source_data['url'],
                connection_id=source_data.get('connection_id', f"{source_data['name']}_connection"),
                include_patterns=discovery.get('include_patterns', ['.*']),
                exclude_patterns=discovery.get('exclude_patterns', []),
                folder_depth=discovery.get('folder_depth', 3),
                collect_logs=defaults.get('collect_logs', True),
                max_log_size_mb=defaults.get('max_log_size_mb', 50),
                artifact_patterns=defaults.get('artifact_patterns', []),
            )
            self._ci_sources[source.name] = source
        
        # Parse products
        for prod_data in self._config.get('products', []):
            settings = prod_data.get('settings', {})
            
            product = ProductConfig(
                name=prod_data['name'],
                description=prod_data.get('description', ''),
                repository_url=prod_data.get('repository_url'),
                job_patterns=prod_data.get('jobs', []),
                priority=settings.get('priority', 'normal'),
                collect_logs=settings.get('collect_logs', True),
                max_builds_per_collection=settings.get('max_builds_per_collection', 20),
            )
            self._products[product.name] = product
    
    # =========================================================================
    # CI Sources
    # =========================================================================
    
    def get_ci_sources(self) -> List[CISourceConfig]:
        """Get all CI source configurations."""
        return list(self._ci_sources.values())
    
    def get_ci_source(self, name: str) -> Optional[CISourceConfig]:
        """Get CI source by name."""
        return self._ci_sources.get(name)
    
    # =========================================================================
    # Products
    # =========================================================================
    
    def get_products(self) -> List[ProductConfig]:
        """Get all product configurations."""
        return list(self._products.values())
    
    def get_product(self, name: str) -> Optional[ProductConfig]:
        """Get product by name."""
        return self._products.get(name)
    
    def find_product_for_job(self, job_name: str, source_name: str) -> Optional[str]:
        """
        Find which product a job belongs to.
        
        Returns product name if found, None otherwise.
        """
        for product in self._products.values():
            for job_spec in product.job_patterns:
                # Check source matches
                if job_spec.get('source') != source_name:
                    continue
                
                # Check pattern match
                if 'pattern' in job_spec:
                    if re.match(job_spec['pattern'], job_name):
                        return product.name
                
                # Check exact name
                if job_spec.get('name') == job_name:
                    return product.name
        
        return None
    
    # =========================================================================
    # Artifact Patterns
    # =========================================================================
    
    def get_artifact_patterns(
        self,
        job_name: Optional[str] = None,
        product_name: Optional[str] = None,
        source_name: Optional[str] = None,
    ) -> List[str]:
        """
        Get artifact patterns for identifying test results.
        
        Merges patterns from: global -> source -> product -> job
        """
        patterns = set()
        
        # Global defaults
        settings = self._config.get('settings', {})
        patterns.update(settings.get('test_artifact_patterns', [
            '**/Test.xml',
            '**/test-results.xml',
            '**/junit*.xml',
            '**/TEST-*.xml',
        ]))
        patterns.update(settings.get('ctest_patterns', [
            '**/Testing/**/Test.xml',
        ]))
        
        # Source patterns
        if source_name and source_name in self._ci_sources:
            source = self._ci_sources[source_name]
            patterns.update(source.artifact_patterns)
        
        # Product patterns
        if product_name and product_name in self._products:
            product = self._products[product_name]
            # Check for job-specific patterns in product config
            for job_spec in product.job_patterns:
                if job_name and job_spec.get('name') == job_name:
                    job_settings = job_spec.get('settings', {})
                    if 'artifact_patterns' in job_settings:
                        patterns.update(job_settings['artifact_patterns'])
        
        return list(patterns)
    
    def is_test_artifact(self, filename: str, patterns: Optional[List[str]] = None) -> bool:
        """Check if a file matches test artifact patterns."""
        if patterns is None:
            patterns = self.get_artifact_patterns()
        
        for pattern in patterns:
            if fnmatch.fnmatch(filename, pattern):
                return True
            # Also match just the basename
            if fnmatch.fnmatch(os.path.basename(filename), os.path.basename(pattern)):
                return True
        
        return False
    
    # =========================================================================
    # Collection Settings
    # =========================================================================
    
    def get_collection_settings(
        self,
        job_name: Optional[str] = None,
        product_name: Optional[str] = None,
        source_name: Optional[str] = None,
    ) -> CollectionSettings:
        """
        Get merged collection settings for a job.
        
        Priority: job-specific -> product -> source -> global
        """
        settings = CollectionSettings()
        
        # Global settings
        global_settings = self._config.get('settings', {})
        collection = global_settings.get('collection', {})
        logs = global_settings.get('logs', {})
        
        settings.collect_logs = logs.get('enabled', True)
        settings.max_log_size_mb = logs.get('max_size_mb', 50)
        settings.max_builds_per_collection = collection.get('max_builds_per_job', 20)
        settings.timeout_seconds = collection.get('timeout_seconds', 300)
        
        # Source settings
        if source_name and source_name in self._ci_sources:
            source = self._ci_sources[source_name]
            settings.collect_logs = source.collect_logs
            settings.max_log_size_mb = source.max_log_size_mb
            settings.artifact_patterns = source.artifact_patterns.copy()
        
        # Product settings
        if product_name and product_name in self._products:
            product = self._products[product_name]
            settings.priority = product.priority
            settings.collect_logs = product.collect_logs
            settings.max_builds_per_collection = product.max_builds_per_collection
        
        # Add artifact patterns
        settings.artifact_patterns = self.get_artifact_patterns(
            job_name, product_name, source_name
        )
        
        return settings
    
    # =========================================================================
    # Airflow Integration
    # =========================================================================
    
    def get_airflow_variable(self, key: str, default: Any = None) -> Any:
        """
        Get value from Airflow Variable with fallback.
        
        Falls back to config file, then default.
        """
        try:
            from airflow.models import Variable
            value = Variable.get(key, default=None)
            if value is not None:
                return value
        except ImportError:
            pass
        
        # Check config file
        settings = self._config.get('settings', {})
        if key in settings:
            return settings[key]
        
        return default
    
    def get_max_jobs_per_run(self) -> int:
        """Get maximum jobs to process per DAG run."""
        return int(self.get_airflow_variable('max_jobs_per_run', 50))
    
    def get_max_builds_per_job(self) -> int:
        """Get maximum builds to collect per job."""
        return int(self.get_airflow_variable('max_builds_per_job', 20))
