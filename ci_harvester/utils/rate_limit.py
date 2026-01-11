"""
Rate Limiting utilities for CI platform API calls.

Uses the `ratelimit` library to prevent overwhelming CI servers.
Configure limits via Airflow Variables.
"""

from functools import wraps
from typing import Callable, Any
from ratelimit import limits, sleep_and_retry

# Try to get limits from Airflow Variables, fall back to defaults
try:
    from airflow.models import Variable
    JENKINS_RATE_LIMIT = int(Variable.get('jenkins_rate_limit', 100))
    GITHUB_RATE_LIMIT = int(Variable.get('github_rate_limit', 60))
except ImportError:
    # Not running in Airflow context
    import os
    JENKINS_RATE_LIMIT = int(os.getenv('JENKINS_RATE_LIMIT', 100))
    GITHUB_RATE_LIMIT = int(os.getenv('GITHUB_RATE_LIMIT', 60))


def rate_limited_jenkins(func: Callable) -> Callable:
    """
    Decorator to rate limit Jenkins API calls.
    
    Default: 100 requests per minute.
    Configure via Airflow Variable 'jenkins_rate_limit'.
    
    Usage:
        @rate_limited_jenkins
        def get_builds(client, job_name):
            return client.get_job_info(job_name)
    """
    @sleep_and_retry
    @limits(calls=JENKINS_RATE_LIMIT, period=60)
    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        return func(*args, **kwargs)
    return wrapper


def rate_limited_github(func: Callable) -> Callable:
    """
    Decorator to rate limit GitHub API calls.
    
    Default: 60 requests per minute.
    Configure via Airflow Variable 'github_rate_limit'.
    """
    @sleep_and_retry
    @limits(calls=GITHUB_RATE_LIMIT, period=60)
    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        return func(*args, **kwargs)
    return wrapper


def get_rate_limiter(platform: str) -> Callable:
    """
    Get rate limiter decorator for a platform.
    
    Args:
        platform: 'jenkins', 'github', etc.
        
    Returns:
        Decorator function
    """
    limiters = {
        'jenkins': rate_limited_jenkins,
        'github': rate_limited_github,
        'github_actions': rate_limited_github,
    }
    return limiters.get(platform, lambda f: f)  # No-op if unknown
