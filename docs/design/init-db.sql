-- CI Harvester Database Initialization Script
-- Run this to set up the PostgreSQL database schema

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Note: Tables are created by SQLAlchemy/Alembic migrations
-- This script is for reference and initial setup

-- Create indexes for text search (if not created by SQLAlchemy)
-- These use pg_trgm for fuzzy text matching

-- Example: Create GIN index for job name search
-- CREATE INDEX IF NOT EXISTS idx_jobs_name_gin ON jobs USING gin(name gin_trgm_ops);

-- Example: Create GIN index for test name search  
-- CREATE INDEX IF NOT EXISTS idx_test_results_name_gin ON test_results USING gin(name gin_trgm_ops);

-- Grant permissions (adjust as needed)
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ci_harvester;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ci_harvester;

-- Create read-only user for API (optional)
-- CREATE USER ci_harvester_readonly WITH PASSWORD 'readonly_password';
-- GRANT CONNECT ON DATABASE ci_harvester TO ci_harvester_readonly;
-- GRANT USAGE ON SCHEMA public TO ci_harvester_readonly;
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO ci_harvester_readonly;

SELECT 'CI Harvester database initialized' AS status;
