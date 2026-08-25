#!/usr/bin/env bash
# ==============================================================================
# GCP Infrastructure Provisioning Script for Real-Time Anti-Mule Solution
# ==============================================================================

set -euo pipefail

# Configuration (Customize as needed)
PROJECT_ID="${1:-${GCP_PROJECT_ID:-}}"
REGION="${2:-us-central1}"
CLUSTER_NAME="antimule-cluster"
GAR_REPO_NAME="antimule"
SA_NAME="github-actions-gke"
WORKLOAD_IDENTITY_POOL="github-pool"
WORKLOAD_IDENTITY_PROVIDER="github-provider"
REPO_OWNER_AND_NAME="${3:-}" # Format: owner/repository

if [ -z "$PROJECT_ID" ]; then
  echo "Usage: ./gcp-setup.sh <PROJECT_ID> [REGION] [OWNER/REPO]"
  echo "Example: ./gcp-setup.sh my-gcp-project us-central1 myuser/anti-mule"
  exit 1
fi

echo "=============================================================================="
echo " Setting up GCP Infrastructure for Project: $PROJECT_ID ($REGION)"
echo "=============================================================================="

# 1. Set default project
gcloud config set project "$PROJECT_ID"

# 2. Enable required GCP API Services
echo "[1/6] Enabling Google Cloud APIs..."
gcloud services enable \
  container.googleapis.com \
  artifactregistry.googleapis.com \
  iamcredentials.googleapis.com \
  cloudresourcemanager.googleapis.com \
  secretmanager.googleapis.com \
  redis.googleapis.com

# 3. Create Artifact Registry Repository
echo "[2/6] Setting up Artifact Registry repository ($GAR_REPO_NAME)..."
if ! gcloud artifacts repositories describe "$GAR_REPO_NAME" --location="$REGION" &>/dev/null; then
  gcloud artifacts repositories create "$GAR_REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --description="Docker repository for Anti-Mule microservices"
  echo "✓ Artifact Registry created."
else
  echo "✓ Artifact Registry already exists."
fi

# 4. Create GKE Autopilot Cluster
echo "[3/6] Creating GKE Autopilot Cluster ($CLUSTER_NAME)..."
if ! gcloud container clusters describe "$CLUSTER_NAME" --location="$REGION" &>/dev/null; then
  gcloud container clusters create-auto "$CLUSTER_NAME" \
    --location="$REGION" \
    --release-channel="regular"
  echo "✓ GKE Autopilot cluster created."
else
  echo "✓ GKE Cluster already exists."
fi

# 5. Create IAM Service Account for GitHub Actions
echo "[4/6] Configuring Service Account ($SA_NAME)..."
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if ! gcloud iam service-accounts describe "$SA_EMAIL" &>/dev/null; then
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="GitHub Actions GKE Deployment Account"
  echo "✓ Service Account created."
fi

# Grant necessary IAM roles
echo "[5/6] Assigning IAM roles..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/container.developer" --quiet

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/artifactregistry.writer" --quiet

# 6. Configure Workload Identity Federation (Keyless Auth)
if [ -n "$REPO_OWNER_AND_NAME" ]; then
  echo "[6/6] Configuring Workload Identity Federation for $REPO_OWNER_AND_NAME..."
  
  if ! gcloud iam workload-identity-pools describe "$WORKLOAD_IDENTITY_POOL" --location="global" &>/dev/null; then
    gcloud iam workload-identity-pools create "$WORKLOAD_IDENTITY_POOL" \
      --location="global" \
      --display-name="GitHub Actions Pool"
  fi

  if ! gcloud iam workload-identity-pools providers describe "$WORKLOAD_IDENTITY_PROVIDER" \
    --workload-identity-pool="$WORKLOAD_IDENTITY_POOL" --location="global" &>/dev/null; then
    gcloud iam workload-identity-pools providers create-oidc "$WORKLOAD_IDENTITY_PROVIDER" \
      --location="global" \
      --workload-identity-pool="$WORKLOAD_IDENTITY_POOL" \
      --issuer-uri="https://token.actions.githubusercontent.com" \
      --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository"
  fi

  POOL_ID=$(gcloud iam workload-identity-pools describe "$WORKLOAD_IDENTITY_POOL" --location="global" --format="value(name)")
  PROVIDER_RESOURCE="${POOL_ID}/providers/${WORKLOAD_IDENTITY_PROVIDER}"

  gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
    --role="roles/iam.workloadIdentityUser" \
    --member="principalSet://iam.googleapis.com/${POOL_ID}/attribute.repository/${REPO_OWNER_AND_NAME}" --quiet

  echo "=============================================================================="
  echo " SETUP COMPLETE! Configure the following secrets in your GitHub Repository:"
  echo "=============================================================================="
  echo " GCP_PROJECT_ID                  : $PROJECT_ID"
  echo " GCP_SA_EMAIL                    : $SA_EMAIL"
  echo " GCP_WORKLOAD_IDENTITY_PROVIDER  : $PROVIDER_RESOURCE"
  echo "=============================================================================="
else
  echo "✓ Infrastructure created. Pass repository owner/name to set up GitHub OIDC."
fi
