# CI Harvester

A data pipeline for scraping CI/CD job logs and test results, storing them in PostgreSQL for analysis and reporting.

## Overview

CI Harvester is designed to:
- **Collect** build logs and test results from various CI systems (starting with Jenkins)
- **Parse** test results from multiple frameworks (starting with CTest)
- **Store** structured data in PostgreSQL for querying and analysis
- **Orchestrate** collection workflows using Apache Airflow

## Documentation

### Getting Started
- [Deployment Guide](docs/DEPLOYMENT.md) - Docker Compose and Kubernetes deployment
- [Development Guide](docs/DEVELOPMENT.md) - Setup, workflow, and debugging
- [Contributing](CONTRIBUTING.md) - Contribution guidelines and TDD practices

### Design Documents
- [Design Document](docs/design/DESIGN.md) - High-level architecture and design decisions
- [Data Model](docs/design/DATA_MODEL.md) - PostgreSQL schema and data structures
- [Configuration](docs/design/CONFIGURATION.md) - CI sources, products, job mappings
- [Scheduling Policy](docs/design/SCHEDULING_POLICY.md) - Collection schedules and priorities
- [Jenkins Integration](docs/design/JENKINS_INTEGRATION.md) - Jenkins API integration details
- [CTest Parser](docs/design/CTEST_PARSER.md) - CTest XML result parsing
- [Airflow Workflows](docs/design/AIRFLOW_WORKFLOWS.md) - DAG definitions and scheduling
- [API Design](docs/design/API_DESIGN.md) - REST API for querying harvested data

### For AI Agents
- [Agent Guidelines](AGENTS.md) - Context and rules for AI coding assistants
- [Cursor Rules](.cursorrules) - Development rules for Cursor AI

## Quick Start

### Using Docker Compose (Recommended)

```bash
# Clone the repository
git clone <repository-url>
cd ci-harvester

# Configure
cp config/ci_harvester.yaml.example config/ci_harvester.yaml
# Edit config/ci_harvester.yaml with your Jenkins URL and job patterns

# Start all services
docker-compose -f docker/docker-compose.yml up -d

# Add Jenkins credentials to Airflow
docker-compose -f docker/docker-compose.yml exec airflow-webserver \
  airflow connections add jenkins_main \
    --conn-type http \
    --conn-host your-jenkins.com \
    --conn-port 443 \
    --conn-schema https \
    --conn-login your-user \
    --conn-password "your-api-token"

# Bootstrap configuration
docker-compose -f docker/docker-compose.yml exec api \
  python -m ci_harvester.config.bootstrap

# Enable DAGs
docker-compose -f docker/docker-compose.yml exec airflow-webserver \
  airflow dags unpause discover_jobs collect_builds

# Access UIs
# Airflow: http://localhost:8080 (admin/admin)
# API: http://localhost:8000/docs
```

### Manual Setup

```bash
# Set up Python environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
cp config/ci_harvester.yaml.example config/ci_harvester.yaml

# Initialize database
python -m ci_harvester.config.bootstrap --create-tables

# Start Airflow (development)
airflow standalone
```

See [Deployment Guide](docs/DEPLOYMENT.md) for detailed instructions.

## Project Structure

```
ci-harvester/
├── docs/
│   └── design/           # Design documentation
├── ci_harvester/
│   ├── collectors/       # CI system collectors (Jenkins, etc.)
│   ├── parsers/          # Test result parsers (CTest, etc.)
│   ├── db/               # Database models and operations
│   ├── api/              # REST API endpoints
│   └── utils/            # Shared utilities
├── dags/                 # Airflow DAG definitions
├── tests/                # Unit and integration tests
├── docker/               # Docker configurations
└── requirements.txt      # Python dependencies
```

## License

MIT License - see [LICENSE](LICENSE) for details.
