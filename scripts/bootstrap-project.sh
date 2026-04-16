#!/usr/bin/env bash
# Bootstrap GCP project for expert-agent deploys.
#
# Idempotent: safe to run multiple times.
#
# Usage:
#   ./scripts/bootstrap-project.sh <PROJECT_ID> [REGION]
#
# Example:
#   ./scripts/bootstrap-project.sh micromed-agents southamerica-east1

set -euo pipefail

PROJECT_ID="${1:?usage: $0 <PROJECT_ID> [REGION]}"
REGION="${2:-southamerica-east1}"

echo "==> Bootstrapping project ${PROJECT_ID} in region ${REGION}"
gcloud config set project "${PROJECT_ID}" >/dev/null

APIS=(
  cloudresourcemanager.googleapis.com
  iam.googleapis.com
  iamcredentials.googleapis.com
  serviceusage.googleapis.com
  compute.googleapis.com
  run.googleapis.com
  artifactregistry.googleapis.com
  storage.googleapis.com
  storage-component.googleapis.com
  firestore.googleapis.com
  secretmanager.googleapis.com
  generativelanguage.googleapis.com
  aiplatform.googleapis.com
  cloudscheduler.googleapis.com
  cloudbuild.googleapis.com
  logging.googleapis.com
  monitoring.googleapis.com
)

echo "==> Enabling APIs (may take a minute)..."
gcloud services enable "${APIS[@]}" --project="${PROJECT_ID}"

echo "==> Creating tfstate bucket (if missing)..."
TFSTATE_BUCKET="${PROJECT_ID}-tfstate"
if ! gcloud storage buckets describe "gs://${TFSTATE_BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${TFSTATE_BUCKET}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --uniform-bucket-level-access \
    --public-access-prevention
  gcloud storage buckets update "gs://${TFSTATE_BUCKET}" --versioning
fi

echo "==> Creating Artifact Registry repo 'expert-agent' (if missing)..."
if ! gcloud artifacts repositories describe expert-agent \
      --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud artifacts repositories create expert-agent \
    --repository-format=docker \
    --location="${REGION}" \
    --project="${PROJECT_ID}" \
    --description="expert-agent backend + chroma images"
fi

echo "==> Creating Firestore database (if missing)..."
if ! gcloud firestore databases describe --database="(default)" \
      --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud firestore databases create \
    --location="${REGION}" \
    --type=firestore-native \
    --project="${PROJECT_ID}"
fi

echo ""
echo "==> Bootstrap complete ✓"
echo ""
echo "Next steps:"
echo "  1. Provision a Gemini API key (https://aistudio.google.com/apikey)"
echo "  2. Store it in Secret Manager:"
echo "     echo -n 'YOUR_KEY' | gcloud secrets create gemini-api-key --data-file=- --project=${PROJECT_ID}"
echo "  3. Run 'tofu apply' in infra/platform/"
echo "  4. Run 'tofu apply' in infra/chroma/"
echo "  5. Run 'tofu apply' in infra/agent/ per agent"
