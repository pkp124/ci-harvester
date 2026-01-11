"""
Tests for configuration module.
"""

import pytest
import tempfile
import os
from pathlib import Path

from ci_harvester.config import Config, CISourceConfig, CollectionSettings


class TestConfig:
    """Tests for Config class."""
    
    @pytest.fixture
    def sample_config_yaml(self):
        """Create a sample config file."""
        content = """
ci_sources:
  - name: jenkins-main
    type: jenkins
    url: https://jenkins.example.com
    connection_id: jenkins_main
    discovery:
      include_patterns:
        - "myproduct-.*"
        - "platform-.*"
      exclude_patterns:
        - ".*-experimental$"
      folder_depth: 3
    defaults:
      collect_logs: true
      max_log_size_mb: 100
      artifact_patterns:
        - "**/Test.xml"
        - "**/junit.xml"

  - name: jenkins-legacy
    type: jenkins
    url: https://legacy.example.com
    connection_id: jenkins_legacy
    defaults:
      collect_logs: false

products:
  - name: MyProduct
    description: Main product
    repository_url: https://github.com/org/myproduct
    jobs:
      - pattern: "myproduct-.*"
        source: jenkins-main
      - name: "myproduct-special"
        source: jenkins-main
        settings:
          priority: high
          artifact_patterns:
            - "**/CustomTest.xml"
    settings:
      priority: normal
      collect_logs: true
      max_builds_per_collection: 50

  - name: Platform
    description: Platform libraries
    jobs:
      - pattern: "platform-.*"
        source: jenkins-main

settings:
  test_artifact_patterns:
    - "**/Test.xml"
    - "**/test-results.xml"
  ctest_patterns:
    - "**/Testing/**/Test.xml"
  logs:
    enabled: true
    max_size_mb: 50
  collection:
    max_builds_per_job: 20
    timeout_seconds: 300
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(content)
            return f.name
    
    @pytest.fixture
    def config(self, sample_config_yaml):
        """Load config from sample file."""
        cfg = Config.load(sample_config_yaml)
        yield cfg
        os.unlink(sample_config_yaml)
    
    def test_load_ci_sources(self, config):
        """Test loading CI sources from config."""
        sources = config.get_ci_sources()
        
        assert len(sources) == 2
        
        main = config.get_ci_source('jenkins-main')
        assert main is not None
        assert main.type == 'jenkins'
        assert main.url == 'https://jenkins.example.com'
        assert main.connection_id == 'jenkins_main'
        assert main.collect_logs == True
        assert main.max_log_size_mb == 100
    
    def test_load_products(self, config):
        """Test loading products from config."""
        products = config.get_products()
        
        assert len(products) == 2
        
        myproduct = config.get_product('MyProduct')
        assert myproduct is not None
        assert myproduct.description == 'Main product'
        assert myproduct.priority == 'normal'
        assert myproduct.max_builds_per_collection == 50
    
    def test_find_product_for_job_pattern(self, config):
        """Test finding product for a job by pattern."""
        # Should match MyProduct via pattern
        product = config.find_product_for_job('myproduct-linux-build', 'jenkins-main')
        assert product == 'MyProduct'
        
        # Should match Platform via pattern
        product = config.find_product_for_job('platform-core', 'jenkins-main')
        assert product == 'Platform'
        
        # No match
        product = config.find_product_for_job('other-job', 'jenkins-main')
        assert product is None
    
    def test_find_product_for_job_exact_name(self, config):
        """Test finding product for a job by exact name."""
        product = config.find_product_for_job('myproduct-special', 'jenkins-main')
        assert product == 'MyProduct'
    
    def test_ci_source_include_exclude(self, config):
        """Test job inclusion/exclusion patterns."""
        source = config.get_ci_source('jenkins-main')
        
        # Should include
        assert source.should_include_job('myproduct-build') == True
        assert source.should_include_job('platform-test') == True
        
        # Should exclude (matches exclude pattern)
        assert source.should_include_job('myproduct-experimental') == False
        
        # Should exclude (doesn't match include pattern)
        assert source.should_include_job('other-job') == False
    
    def test_get_artifact_patterns(self, config):
        """Test getting artifact patterns."""
        patterns = config.get_artifact_patterns()
        
        # Should include global patterns
        assert '**/Test.xml' in patterns
        assert '**/test-results.xml' in patterns
        assert '**/Testing/**/Test.xml' in patterns
        
    def test_get_artifact_patterns_with_source(self, config):
        """Test artifact patterns include source defaults."""
        patterns = config.get_artifact_patterns(source_name='jenkins-main')
        
        # Should include source-specific patterns
        assert '**/junit.xml' in patterns
    
    def test_is_test_artifact(self, config):
        """Test checking if file is a test artifact."""
        assert config.is_test_artifact('build/Testing/results/Test.xml') == True
        assert config.is_test_artifact('Test.xml') == True
        assert config.is_test_artifact('output/junit.xml') == True
        assert config.is_test_artifact('build.log') == False
        assert config.is_test_artifact('random.txt') == False
    
    def test_get_collection_settings(self, config):
        """Test getting merged collection settings."""
        settings = config.get_collection_settings()
        
        assert isinstance(settings, CollectionSettings)
        assert settings.enabled == True
        assert settings.collect_logs == True
        assert settings.max_log_size_mb == 50  # From global settings
    
    def test_get_collection_settings_with_source(self, config):
        """Test collection settings include source overrides."""
        settings = config.get_collection_settings(source_name='jenkins-main')
        
        assert settings.max_log_size_mb == 100  # Overridden by source
        
        settings_legacy = config.get_collection_settings(source_name='jenkins-legacy')
        assert settings_legacy.collect_logs == False  # Overridden by source
    
    def test_get_collection_settings_with_product(self, config):
        """Test collection settings include product overrides."""
        settings = config.get_collection_settings(
            product_name='MyProduct',
            source_name='jenkins-main'
        )
        
        assert settings.priority == 'normal'
        assert settings.max_builds_per_collection == 50  # From product
    
    def test_config_singleton(self, sample_config_yaml):
        """Test config singleton pattern."""
        os.environ['CI_HARVESTER_CONFIG'] = sample_config_yaml
        
        config1 = Config.get()
        config2 = Config.get()
        
        assert config1 is config2
        
        # Reload should create new instance
        config3 = Config.reload()
        assert config3 is not config1
        
        del os.environ['CI_HARVESTER_CONFIG']
    
    def test_load_missing_file(self):
        """Test loading from non-existent file."""
        config = Config.load('/nonexistent/path/config.yaml')
        
        # Should return empty config, not error
        assert config.get_ci_sources() == []
        assert config.get_products() == []


class TestCISourceConfig:
    """Tests for CISourceConfig."""
    
    def test_should_include_job_basic(self):
        """Test basic include/exclude logic."""
        source = CISourceConfig(
            name='test',
            type='jenkins',
            url='https://test.com',
            connection_id='test',
            include_patterns=['build-.*', 'test-.*'],
            exclude_patterns=['.*-skip$']
        )
        
        assert source.should_include_job('build-linux') == True
        assert source.should_include_job('test-unit') == True
        assert source.should_include_job('deploy-prod') == False  # No match
        assert source.should_include_job('build-skip') == False  # Excluded
    
    def test_should_include_job_default(self):
        """Test default include pattern."""
        source = CISourceConfig(
            name='test',
            type='jenkins',
            url='https://test.com',
            connection_id='test'
            # Default: include_patterns=['.*']
        )
        
        assert source.should_include_job('any-job') == True
        assert source.should_include_job('another-job') == True
