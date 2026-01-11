# CI Harvester

A data pipeline for scraping CI/CD job logs and test results, storing them in PostgreSQL for analysis and reporting.

## Overview

CI Harvester is designed to:
- **Collect** build logs and test results from various CI systems (starting with Jenkins)
- **Parse** test results from multiple frameworks (starting with CTest)
- **Store** structured data in PostgreSQL for querying and analysis
- **Orchestrate** collection workflows using Apache Airflow

## Documentation

- [Design Document](docs/design/DESIGN.md) - High-level architecture and design decisions
- [Data Model](docs/design/DATA_MODEL.md) - PostgreSQL schema and data structures
- [Jenkins Integration](docs/design/JENKINS_INTEGRATION.md) - Jenkins API integration details
- [CTest Parser](docs/design/CTEST_PARSER.md) - CTest XML result parsing
- [Airflow Workflows](docs/design/AIRFLOW_WORKFLOWS.md) - DAG definitions and scheduling
- [API Design](docs/design/API_DESIGN.md) - REST API for querying harvested data

## Quick Start

```bash
# Clone the repository
git clone <repository-url>
cd ci-harvester

# Set up Python environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Initialize database
python -m ci_harvester.db.init

# Start Airflow (development)
airflow standalone
```

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
