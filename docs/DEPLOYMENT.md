# CI Harvester - Deployment Guide

This guide covers deploying CI Harvester in different environments.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start (Docker Compose)](#quick-start-docker-compose)
- [Production Deployment (Kubernetes)](#production-deployment-kubernetes)
- [Configuration](#configuration)
- [Verification](#verification)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required
- Docker & Docker Compose (for containerized deployment)
- PostgreSQL 15+ (or use containerized version)
- Access to Jenkins server(s) with API token

### Optional
- Kubernetes cluster (for production)
- Helm 3+ (for Kubernetes deployment)
- External secrets manager (Vault, AWS Secrets Manager)

---

## Quick Start (Docker Compose)

Best for: Development, testing, small-scale production.

### Step 1: Clone and Configure

```bash
# Clone repository
git clone <repository-url>
cd ci-harvester

# Create configuration
cp config/ci_harvester.yaml.example config/ci_harvester.yaml
cp .env.example .env

# Edit configuration files
nano config/ci_harvester.yaml  # Add your Jenkins servers, products
nano .env                       # Set database passwords, etc.
```

### Step 2: Configure Jenkins Connection

Edit `config/ci_harvester.yaml`:

```yaml
ci_sources:
  - name: jenkins-main
    type: jenkins
    url: https://your-jenkins-server.com
    connection_id: jenkins_main
    discovery:
      include_patterns:
        - ".*"  # All jobs, or specify patterns
      exclude_patterns:
        - ".*-sandbox$"
    defaults:
      artifact_patterns:
        - "**/Test.xml"
        - "**/test-results.xml"

products:
  - name: MyProduct
    description: My product builds
    jobs:
      - pattern: "myproduct-.*"
        source: jenkins-main
```

### Step 3: Start Services

```bash
# Start all services
docker-compose -f docker/docker-compose.yml up -d

# Wait for services to be ready (about 30 seconds)
docker-compose -f docker/docker-compose.yml logs -f airflow-init
```

### Step 4: Configure Airflow

```bash
# Add Jenkins credentials to Airflow
docker-compose -f docker/docker-compose.yml exec airflow-webserver \
  airflow connections add jenkins_main \
    --conn-type http \
    --conn-host your-jenkins-server.com \
    --conn-port 443 \
    --conn-schema https \
    --conn-login your-username \
    --conn-password "your-api-token"

# Set scheduling variables
docker-compose -f docker/docker-compose.yml exec airflow-webserver \
  airflow variables set discovery_schedule "*/10 * * * *"

docker-compose -f docker/docker-compose.yml exec airflow-webserver \
  airflow variables set collection_schedule "*/5 * * * *"

docker-compose -f docker/docker-compose.yml exec airflow-webserver \
  airflow variables set max_jobs_per_run 50
```

### Step 5: Initialize Database

```bash
# Run database migrations
docker-compose -f docker/docker-compose.yml exec api \
  alembic upgrade head

# Bootstrap configuration into database
docker-compose -f docker/docker-compose.yml exec api \
  python -m ci_harvester.config.bootstrap
```

### Step 6: Enable DAGs

```bash
# Enable the DAGs
docker-compose -f docker/docker-compose.yml exec airflow-webserver \
  airflow dags unpause discover_jobs

docker-compose -f docker/docker-compose.yml exec airflow-webserver \
  airflow dags unpause collect_builds
```

### Step 7: Verify

```bash
# Check service status
docker-compose -f docker/docker-compose.yml ps

# View logs
docker-compose -f docker/docker-compose.yml logs -f airflow-scheduler

# Access UIs
# Airflow: http://localhost:8080 (admin/admin)
# API Docs: http://localhost:8000/docs
# Adminer (DB): http://localhost:8081
```

---

## Production Deployment (Kubernetes)

Best for: Large-scale, high-availability production environments.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Kubernetes Cluster                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                 Airflow (Helm Chart)                     │   │
│  │  ┌───────────┐ ┌───────────┐ ┌───────────────────────┐ │   │
│  │  │ Scheduler │ │ Webserver │ │ Workers (auto-scaled) │ │   │
│  │  │  (1 pod)  │ │ (2 pods)  │ │     (3-10 pods)       │ │   │
│  │  └───────────┘ └───────────┘ └───────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │
│  │ CI Harvester  │  │   PostgreSQL  │  │     Redis     │       │
│  │  API (3 pods) │  │   (RDS/HA)    │  │   (cluster)   │       │
│  └───────────────┘  └───────────────┘  └───────────────┘       │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │                    Ingress Controller                      │ │
│  │         api.ci-harvester.example.com                       │ │
│  │         airflow.ci-harvester.example.com                   │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Step 1: Create Namespace

```bash
kubectl create namespace ci-harvester
```

### Step 2: Create Secrets

```bash
# Database credentials
kubectl create secret generic ci-harvester-db \
  --namespace ci-harvester \
  --from-literal=username=ci_harvester \
  --from-literal=password='your-secure-password' \
  --from-literal=host=your-postgres-host \
  --from-literal=database=ci_harvester

# Jenkins credentials
kubectl create secret generic jenkins-credentials \
  --namespace ci-harvester \
  --from-literal=jenkins-main-user=your-username \
  --from-literal=jenkins-main-token='your-api-token'

# Airflow Fernet key (generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
kubectl create secret generic airflow-fernet-key \
  --namespace ci-harvester \
  --from-literal=fernet-key='your-fernet-key'
```

### Step 3: Create ConfigMap

```bash
# Create config file as ConfigMap
kubectl create configmap ci-harvester-config \
  --namespace ci-harvester \
  --from-file=config.yaml=config/ci_harvester.yaml
```

### Step 4: Deploy PostgreSQL (if not using external)

```bash
# Using Bitnami PostgreSQL Helm chart
helm repo add bitnami https://charts.bitnami.com/bitnami

helm install postgresql bitnami/postgresql \
  --namespace ci-harvester \
  --set auth.postgresPassword=adminpassword \
  --set auth.username=ci_harvester \
  --set auth.password=your-secure-password \
  --set auth.database=ci_harvester \
  --set primary.persistence.size=100Gi
```

### Step 5: Deploy Airflow

```bash
# Add Airflow Helm repo
helm repo add apache-airflow https://airflow.apache.org

# Create values file
cat > airflow-values.yaml << 'EOF'
executor: CeleryExecutor

images:
  airflow:
    repository: your-registry/ci-harvester-airflow
    tag: latest
    pullPolicy: Always

# Git sync for DAGs
dags:
  gitSync:
    enabled: true
    repo: git@github.com:your-org/ci-harvester.git
    branch: main
    subPath: dags
    sshKeySecret: git-ssh-key

# Workers
workers:
  replicas: 3
  resources:
    requests:
      memory: "1Gi"
      cpu: "500m"
    limits:
      memory: "2Gi"
      cpu: "1000m"

# Webserver
webserver:
  replicas: 2
  service:
    type: ClusterIP

# Use external PostgreSQL
postgresql:
  enabled: false

data:
  metadataConnection:
    user: airflow
    pass: airflow-password
    host: postgresql.ci-harvester.svc.cluster.local
    port: 5432
    db: airflow

# Redis for Celery
redis:
  enabled: true

# Extra environment variables
env:
  - name: CI_HARVESTER_CONFIG
    value: /opt/airflow/config/config.yaml
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: ci-harvester-db
        key: connection-string

# Mount config
extraVolumes:
  - name: ci-harvester-config
    configMap:
      name: ci-harvester-config

extraVolumeMounts:
  - name: ci-harvester-config
    mountPath: /opt/airflow/config
    readOnly: true
EOF

# Install Airflow
helm install airflow apache-airflow/airflow \
  --namespace ci-harvester \
  --values airflow-values.yaml \
  --timeout 10m
```

### Step 6: Deploy CI Harvester API

```bash
cat > api-deployment.yaml << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ci-harvester-api
  namespace: ci-harvester
spec:
  replicas: 3
  selector:
    matchLabels:
      app: ci-harvester-api
  template:
    metadata:
      labels:
        app: ci-harvester-api
    spec:
      containers:
        - name: api
          image: your-registry/ci-harvester-api:latest
          ports:
            - containerPort: 8000
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: ci-harvester-db
                  key: connection-string
            - name: CI_HARVESTER_CONFIG
              value: /app/config/config.yaml
          volumeMounts:
            - name: config
              mountPath: /app/config
              readOnly: true
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
      volumes:
        - name: config
          configMap:
            name: ci-harvester-config
---
apiVersion: v1
kind: Service
metadata:
  name: ci-harvester-api
  namespace: ci-harvester
spec:
  selector:
    app: ci-harvester-api
  ports:
    - port: 80
      targetPort: 8000
  type: ClusterIP
EOF

kubectl apply -f api-deployment.yaml
```

### Step 7: Create Ingress

```bash
cat > ingress.yaml << 'EOF'
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ci-harvester-ingress
  namespace: ci-harvester
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
    - hosts:
        - api.ci-harvester.example.com
        - airflow.ci-harvester.example.com
      secretName: ci-harvester-tls
  rules:
    - host: api.ci-harvester.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: ci-harvester-api
                port:
                  number: 80
    - host: airflow.ci-harvester.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: airflow-webserver
                port:
                  number: 8080
EOF

kubectl apply -f ingress.yaml
```

### Step 8: Configure Airflow Variables

```bash
# Port-forward to Airflow webserver
kubectl port-forward svc/airflow-webserver 8080:8080 -n ci-harvester &

# Set variables via CLI
kubectl exec -it deployment/airflow-scheduler -n ci-harvester -- \
  airflow variables set discovery_schedule "*/10 * * * *"

kubectl exec -it deployment/airflow-scheduler -n ci-harvester -- \
  airflow variables set collection_schedule "*/5 * * * *"

# Add Jenkins connection
kubectl exec -it deployment/airflow-scheduler -n ci-harvester -- \
  airflow connections add jenkins_main \
    --conn-type http \
    --conn-host your-jenkins-server.com \
    --conn-port 443 \
    --conn-schema https \
    --conn-login "$JENKINS_USER" \
    --conn-password "$JENKINS_TOKEN"
```

---

## Configuration

### Airflow Variables (Schedules & Limits)

| Variable | Default | Description |
|----------|---------|-------------|
| `discovery_schedule` | `*/10 * * * *` | How often to discover new jobs |
| `collection_schedule` | `*/5 * * * *` | How often to collect builds |
| `max_jobs_per_run` | `50` | Max jobs per collection cycle |
| `max_builds_per_job` | `20` | Max builds to collect per job |
| `jenkins_rate_limit` | `100` | Requests/min to Jenkins |

```bash
# Set via CLI
airflow variables set discovery_schedule "*/10 * * * *"

# Or via Airflow UI: Admin -> Variables
```

### Config File (Sources, Products, Patterns)

See `config/ci_harvester.yaml.example` for full reference.

```yaml
ci_sources:
  - name: jenkins-main
    type: jenkins
    url: https://jenkins.example.com
    connection_id: jenkins_main
    discovery:
      include_patterns: ["myproduct-.*"]
      exclude_patterns: [".*-experimental$"]
    defaults:
      artifact_patterns:
        - "**/Test.xml"

products:
  - name: MyProduct
    jobs:
      - pattern: "myproduct-.*"
        source: jenkins-main
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `CI_HARVESTER_CONFIG` | Path to config YAML file |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING) |

---

## Verification

### Check Services

```bash
# Docker Compose
docker-compose -f docker/docker-compose.yml ps

# Kubernetes
kubectl get pods -n ci-harvester
```

### Check DAGs

```bash
# List DAGs
airflow dags list

# Check DAG status
airflow dags list-runs -d discover_jobs --limit 5
```

### Check API

```bash
# Health check
curl http://localhost:8000/health

# List products
curl http://localhost:8000/api/v1/products
```

### Check Logs

```bash
# Docker Compose
docker-compose -f docker/docker-compose.yml logs -f airflow-scheduler

# Kubernetes
kubectl logs -f deployment/airflow-scheduler -n ci-harvester
```

### Trigger Manual Run

```bash
# Trigger discovery
airflow dags trigger discover_jobs

# Trigger collection
airflow dags trigger collect_builds
```

---

## Troubleshooting

### DAGs Not Appearing

```bash
# Check for syntax errors
python dags/discover_jobs.py

# Check Airflow logs
docker-compose logs airflow-scheduler | grep -i error

# Reserialize DAGs
airflow dags reserialize
```

### Connection Errors to Jenkins

```bash
# Test connection
airflow connections get jenkins_main

# Check from container
docker-compose exec airflow-scheduler \
  curl -u user:token https://jenkins.example.com/api/json
```

### Database Connection Issues

```bash
# Check database is running
docker-compose exec postgres-data pg_isready

# Check connection string
docker-compose exec api python -c "
from ci_harvester.db import get_session
with get_session() as s:
    print(s.execute('SELECT 1').scalar())
"
```

### Rate Limiting Issues

```bash
# Increase rate limit
airflow variables set jenkins_rate_limit 200

# Check current limit
airflow variables get jenkins_rate_limit
```

---

## Updating

### Docker Compose

```bash
# Pull latest images
docker-compose -f docker/docker-compose.yml pull

# Restart services
docker-compose -f docker/docker-compose.yml up -d

# Run migrations
docker-compose exec api alembic upgrade head
```

### Kubernetes

```bash
# Update image
kubectl set image deployment/ci-harvester-api \
  api=your-registry/ci-harvester-api:new-tag \
  -n ci-harvester

# Update Airflow
helm upgrade airflow apache-airflow/airflow \
  --namespace ci-harvester \
  --values airflow-values.yaml
```

---

## Backup & Recovery

### Database Backup

```bash
# Docker Compose
docker-compose exec postgres-data \
  pg_dump -U ci_harvester ci_harvester > backup.sql

# Kubernetes
kubectl exec -it postgresql-0 -n ci-harvester -- \
  pg_dump -U ci_harvester ci_harvester > backup.sql
```

### Restore

```bash
# Docker Compose
docker-compose exec -T postgres-data \
  psql -U ci_harvester ci_harvester < backup.sql
```
