"""
Scheduling Configuration - User-configurable scheduling policies.

See docs/design/SCHEDULING_POLICY.md for detailed documentation.
"""

import os
import re
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Dict, List, Optional, Any
import yaml


class JobPriority(IntEnum):
    """Job collection priority levels."""
    CRITICAL = 0    # P0: Collect immediately, max resources
    HIGH = 1        # P1: Collect within 5 minutes
    NORMAL = 2      # P2: Collect within 15 minutes (default)
    LOW = 3         # P3: Collect when resources available
    BACKGROUND = 4  # P4: Collect during off-peak hours


@dataclass
class RetryConfig:
    """Retry policy configuration."""
    max_attempts: int = 3
    initial_delay_seconds: int = 60
    max_delay_seconds: int = 3600
    exponential_base: float = 2.0


@dataclass
class RateLimitConfig:
    """Rate limiting configuration for a CI platform."""
    requests_per_minute: int = 100
    max_concurrent: int = 10
    min_request_interval_ms: int = 100
    backoff_initial_ms: int = 1000
    backoff_max_ms: int = 60000
    backoff_multiplier: float = 2.0


@dataclass
class BackpressureConfig:
    """Backpressure handling configuration."""
    warning_threshold: float = 0.25
    critical_threshold: float = 0.50
    emergency_threshold: float = 0.75
    resume_threshold: float = 0.20
    recovery_rate: float = 0.10


@dataclass
class CollectionLimits:
    """Limits on collection operations."""
    max_builds_per_interval: int = 500
    max_concurrent_jobs: int = 20
    max_log_size_mb: int = 50
    max_artifacts_per_build: int = 100
    max_artifact_size_mb: int = 100


@dataclass
class PriorityRule:
    """Rule for assigning priority to jobs."""
    name: str
    priority: JobPriority
    job_name_pattern: Optional[str] = None
    branch_pattern: Optional[str] = None
    product_name: Optional[str] = None
    
    def matches(self, job_name: str, branch: Optional[str] = None, 
                product_name: Optional[str] = None) -> bool:
        """Check if this rule matches the given job."""
        if self.job_name_pattern:
            if not re.match(self.job_name_pattern, job_name):
                return False
        
        if self.branch_pattern and branch:
            if not re.match(self.branch_pattern, branch):
                return False
        
        if self.product_name and product_name:
            if self.product_name != product_name:
                return False
        
        return True


@dataclass
class SchedulingConfig:
    """
    Main scheduling configuration.
    
    Can be loaded from:
    - YAML configuration file
    - Environment variables
    - Airflow Variables
    - Default values
    """
    
    # Discovery settings
    discovery_interval_minutes: int = 10
    
    # Collection settings
    collection_interval_minutes: int = 5
    max_jobs_per_cycle: int = 50
    max_builds_per_job: int = 20
    
    # Parallelism
    max_parallel_collections: int = 10
    max_parallel_parsers: int = 20
    
    # Timeouts
    collection_timeout_seconds: int = 300
    parse_timeout_seconds: int = 120
    
    # Retry policy
    retry: RetryConfig = field(default_factory=RetryConfig)
    
    # Rate limits per platform
    rate_limits: Dict[str, RateLimitConfig] = field(default_factory=dict)
    
    # Backpressure
    backpressure: BackpressureConfig = field(default_factory=BackpressureConfig)
    
    # Collection limits
    limits: CollectionLimits = field(default_factory=CollectionLimits)
    
    # Priority rules
    priority_rules: List[PriorityRule] = field(default_factory=list)
    default_priority: JobPriority = JobPriority.NORMAL
    priority_overrides: Dict[str, JobPriority] = field(default_factory=dict)
    
    # Product-specific settings
    product_settings: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Job-specific settings
    job_settings: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    @classmethod
    def load(cls, config_path: Optional[str] = None) -> 'SchedulingConfig':
        """
        Load configuration from file and environment.
        
        Priority (highest to lowest):
        1. Environment variables
        2. Configuration file
        3. Default values
        """
        config = cls()
        
        # Load from file if exists
        if config_path is None:
            config_path = os.getenv(
                'CI_HARVESTER_SCHEDULING_CONFIG',
                '/etc/ci-harvester/scheduling.yaml'
            )
        
        if Path(config_path).exists():
            config = cls._load_from_file(config_path)
        
        # Override with environment variables
        config = cls._apply_env_overrides(config)
        
        return config
    
    @classmethod
    def _load_from_file(cls, path: str) -> 'SchedulingConfig':
        """Load configuration from YAML file."""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        
        config = cls()
        
        if not data:
            return config
        
        scheduling = data.get('scheduling', {})
        
        # Basic settings
        config.discovery_interval_minutes = scheduling.get(
            'discovery_interval_minutes', config.discovery_interval_minutes
        )
        config.collection_interval_minutes = scheduling.get(
            'collection_interval_minutes', config.collection_interval_minutes
        )
        config.max_jobs_per_cycle = scheduling.get(
            'max_jobs_per_cycle', config.max_jobs_per_cycle
        )
        config.max_builds_per_job = scheduling.get(
            'max_builds_per_job', config.max_builds_per_job
        )
        config.max_parallel_collections = scheduling.get(
            'max_parallel_collections', config.max_parallel_collections
        )
        config.max_parallel_parsers = scheduling.get(
            'max_parallel_parsers', config.max_parallel_parsers
        )
        config.collection_timeout_seconds = scheduling.get(
            'collection_timeout_seconds', config.collection_timeout_seconds
        )
        config.parse_timeout_seconds = scheduling.get(
            'parse_timeout_seconds', config.parse_timeout_seconds
        )
        
        # Retry config
        retry_data = scheduling.get('retry', {})
        config.retry = RetryConfig(
            max_attempts=retry_data.get('max_attempts', 3),
            initial_delay_seconds=retry_data.get('initial_delay_seconds', 60),
            max_delay_seconds=retry_data.get('max_delay_seconds', 3600),
            exponential_base=retry_data.get('exponential_base', 2.0),
        )
        
        # Rate limits
        rate_limits_data = data.get('rate_limits', {})
        for platform, limits in rate_limits_data.items():
            config.rate_limits[platform] = RateLimitConfig(
                requests_per_minute=limits.get('requests_per_minute', 100),
                max_concurrent=limits.get('max_concurrent', 10),
                min_request_interval_ms=limits.get('min_request_interval_ms', 100),
            )
        
        # Backpressure
        bp_data = data.get('backpressure', {})
        thresholds = bp_data.get('thresholds', {})
        config.backpressure = BackpressureConfig(
            warning_threshold=thresholds.get('warning', 0.25),
            critical_threshold=thresholds.get('critical', 0.50),
            emergency_threshold=thresholds.get('emergency', 0.75),
            resume_threshold=bp_data.get('recovery', {}).get('resume_threshold', 0.20),
            recovery_rate=bp_data.get('recovery', {}).get('recovery_rate', 0.10),
        )
        
        # Priority rules
        priority_data = data.get('priority_rules', {})
        for rule_data in priority_data.get('rules', []):
            match = rule_data.get('match', {})
            priority_str = rule_data.get('priority', 'NORMAL')
            priority = JobPriority[priority_str]
            
            rule = PriorityRule(
                name=rule_data.get('name', 'unnamed'),
                priority=priority,
                job_name_pattern=match.get('job_name_pattern'),
                branch_pattern=match.get('branch_pattern'),
                product_name=match.get('product_name'),
            )
            config.priority_rules.append(rule)
        
        default_priority_str = priority_data.get('default_priority', 'NORMAL')
        config.default_priority = JobPriority[default_priority_str]
        
        for job_id, priority_str in priority_data.get('overrides', {}).items():
            config.priority_overrides[job_id] = JobPriority[priority_str]
        
        # Product settings
        config.product_settings = data.get('products', {})
        
        # Job settings
        config.job_settings = data.get('jobs', {})
        
        return config
    
    @classmethod
    def _apply_env_overrides(cls, config: 'SchedulingConfig') -> 'SchedulingConfig':
        """Apply environment variable overrides."""
        env_mappings = {
            'CI_HARVESTER_DISCOVERY_INTERVAL': 'discovery_interval_minutes',
            'CI_HARVESTER_COLLECTION_INTERVAL': 'collection_interval_minutes',
            'CI_HARVESTER_MAX_JOBS_PER_CYCLE': 'max_jobs_per_cycle',
            'CI_HARVESTER_MAX_BUILDS_PER_JOB': 'max_builds_per_job',
            'CI_HARVESTER_MAX_PARALLEL_COLLECTIONS': 'max_parallel_collections',
            'CI_HARVESTER_MAX_PARALLEL_PARSERS': 'max_parallel_parsers',
            'CI_HARVESTER_COLLECTION_TIMEOUT': 'collection_timeout_seconds',
            'CI_HARVESTER_PARSE_TIMEOUT': 'parse_timeout_seconds',
        }
        
        for env_var, attr in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                setattr(config, attr, int(value))
        
        return config
    
    def get_job_priority(
        self, 
        job_id: str, 
        job_name: str,
        branch: Optional[str] = None,
        product_name: Optional[str] = None
    ) -> JobPriority:
        """
        Get priority for a job based on rules and overrides.
        
        Priority resolution order:
        1. Explicit override for job_id
        2. Matching priority rule
        3. Default priority
        """
        # Check explicit override
        if job_id in self.priority_overrides:
            return self.priority_overrides[job_id]
        
        # Check rules in order
        for rule in self.priority_rules:
            if rule.matches(job_name, branch, product_name):
                return rule.priority
        
        return self.default_priority
    
    def get_job_settings(self, job_id: str, job_name: str) -> Dict[str, Any]:
        """Get merged settings for a specific job."""
        settings = {
            'collection_interval_minutes': self.collection_interval_minutes,
            'max_builds': self.max_builds_per_job,
            'enabled': True,
        }
        
        # Apply job-specific settings
        if job_name in self.job_settings:
            settings.update(self.job_settings[job_name])
        if job_id in self.job_settings:
            settings.update(self.job_settings[job_id])
        
        return settings
    
    def get_product_settings(self, product_name: str) -> Dict[str, Any]:
        """Get settings for a specific product."""
        settings = {
            'collection_interval_minutes': self.collection_interval_minutes,
            'priority': self.default_priority,
            'max_builds_per_job': self.max_builds_per_job,
            'enabled': True,
        }
        
        if product_name in self.product_settings:
            settings.update(self.product_settings[product_name])
        
        return settings
    
    def get_rate_limit(self, platform: str) -> RateLimitConfig:
        """Get rate limit configuration for a CI platform."""
        if platform in self.rate_limits:
            return self.rate_limits[platform]
        
        # Default rate limits
        return RateLimitConfig()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            'discovery_interval_minutes': self.discovery_interval_minutes,
            'collection_interval_minutes': self.collection_interval_minutes,
            'max_jobs_per_cycle': self.max_jobs_per_cycle,
            'max_builds_per_job': self.max_builds_per_job,
            'max_parallel_collections': self.max_parallel_collections,
            'max_parallel_parsers': self.max_parallel_parsers,
            'collection_timeout_seconds': self.collection_timeout_seconds,
            'parse_timeout_seconds': self.parse_timeout_seconds,
            'default_priority': self.default_priority.name,
            'backpressure': {
                'warning_threshold': self.backpressure.warning_threshold,
                'critical_threshold': self.backpressure.critical_threshold,
                'emergency_threshold': self.backpressure.emergency_threshold,
            },
        }
