"""
Tests for rate limiting utilities.
"""

import pytest
import time
import os
from unittest.mock import patch, MagicMock

from ci_harvester.utils.rate_limit import (
    rate_limited_jenkins,
    rate_limited_github,
    get_rate_limiter,
)


class TestRateLimitDecorators:
    """Tests for rate limit decorators."""
    
    def test_rate_limited_jenkins_allows_calls(self):
        """Test that decorated function is callable."""
        call_count = 0
        
        @rate_limited_jenkins
        def my_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2
        
        result = my_function(5)
        
        assert result == 10
        assert call_count == 1
    
    def test_rate_limited_github_allows_calls(self):
        """Test that GitHub rate limiter works."""
        @rate_limited_github
        def my_function():
            return "success"
        
        result = my_function()
        
        assert result == "success"
    
    def test_get_rate_limiter_jenkins(self):
        """Test getting rate limiter for Jenkins."""
        limiter = get_rate_limiter('jenkins')
        
        assert limiter is rate_limited_jenkins
    
    def test_get_rate_limiter_github(self):
        """Test getting rate limiter for GitHub."""
        limiter = get_rate_limiter('github')
        assert limiter is rate_limited_github
        
        limiter = get_rate_limiter('github_actions')
        assert limiter is rate_limited_github
    
    def test_get_rate_limiter_unknown(self):
        """Test getting rate limiter for unknown platform."""
        limiter = get_rate_limiter('unknown_platform')
        
        # Should return no-op decorator
        @limiter
        def my_function():
            return "success"
        
        assert my_function() == "success"
    
    def test_decorated_function_preserves_metadata(self):
        """Test that decorator preserves function metadata."""
        @rate_limited_jenkins
        def documented_function():
            """This is the docstring."""
            pass
        
        assert documented_function.__name__ == 'documented_function'
        assert 'docstring' in documented_function.__doc__


class TestRateLimitConfiguration:
    """Tests for rate limit configuration."""
    
    def test_rate_limit_from_environment(self):
        """Test that rate limits can be set via environment."""
        # This tests that the module reads from environment
        # when Airflow is not available
        original = os.environ.get('JENKINS_RATE_LIMIT')
        
        try:
            os.environ['JENKINS_RATE_LIMIT'] = '200'
            
            # Reload the module to pick up new env var
            import importlib
            from ci_harvester.utils import rate_limit
            importlib.reload(rate_limit)
            
            assert rate_limit.JENKINS_RATE_LIMIT == 200
            
        finally:
            if original:
                os.environ['JENKINS_RATE_LIMIT'] = original
            else:
                os.environ.pop('JENKINS_RATE_LIMIT', None)
            
            # Reload to restore
            import importlib
            from ci_harvester.utils import rate_limit
            importlib.reload(rate_limit)


class TestRateLimitBehavior:
    """Tests for actual rate limiting behavior."""
    
    @pytest.mark.slow
    def test_rate_limit_delays_calls(self):
        """Test that rate limiter actually delays calls when limit exceeded."""
        # Create a limiter with very low limit for testing
        from ratelimit import limits, sleep_and_retry
        
        call_times = []
        
        @sleep_and_retry
        @limits(calls=2, period=1)  # 2 calls per second
        def limited_function():
            call_times.append(time.time())
            return True
        
        # Make 3 calls - third should be delayed
        limited_function()
        limited_function()
        limited_function()
        
        assert len(call_times) == 3
        
        # First two calls should be close together
        assert call_times[1] - call_times[0] < 0.5
        
        # Third call should be delayed (rate limited)
        # It should wait until the next second window
        assert call_times[2] - call_times[0] >= 0.9
