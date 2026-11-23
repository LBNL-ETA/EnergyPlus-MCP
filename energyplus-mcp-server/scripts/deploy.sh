#!/usr/bin/env bash
# Build Dockerfile.prod with Cloud Build and deploy it to Google Cloud Run.
#
# One-time setup (replace names as you like; see README "Remote deployment"):
#   gcloud artifacts repositories create energyplus-mcp \
#       --location="$REGION" --repository-format=docker
#   gcloud secrets create mcp-tokens --replication-policy=automatic
#   echo '[{"label":"alice","token":"<openssl rand -hex 32>"}]' \
#       | gcloud secrets versions add mcp-tokens --data-file=-
#   gcloud storage buckets create "gs://$BUCKET" --location="$REGION" \
#       --uniform-bucket-level-access --public-access-prevention
#   gcloud iam service-accounts create energyplus-mcp-run
#   # The runtime account needs only the token secret and the bucket:
#   gcloud secrets add-iam-policy-binding mcp-tokens \
#       --member="serviceAccount:$SERVICE_ACCOUNT" --role=roles/secretmanager.secretAccessor
#   gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
#       --member="serviceAccount:$SERVICE_ACCOUNT" --role=roles/storage.objectUser
#
# Then, from the energyplus-mcp-server directory:
#   PROJECT=my-project BUCKET=my-bucket \
#   SERVICE_ACCOUNT=energyplus-mcp-run@my-project.iam.gserviceaccount.com \
#   ./scripts/deploy.sh

set -euo pipefail

PROJECT="${PROJECT:?PROJECT is required (GCP project ID)}"
REGION="${REGION:-us-west1}"
SERVICE="${SERVICE:-energyplus-mcp}"
REPO="${REPO:-energyplus-mcp}"
SECRET="${SECRET:-mcp-tokens}"
BUCKET="${BUCKET:-}"                  # Cloud Storage bucket for per-user files
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-}" # runtime identity; avoid the default compute account
ADMIN_LABELS="${ADMIN_LABELS:-}"       # token labels allowed to read logs/config
OAUTH_SECRET="${OAUTH_SECRET:-}"       # optional: secret holding MCP_OAUTH (Google sign-in)
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-}" # the service's https URL; required with OAUTH_SECRET
TAG="${TAG:-$(git rev-parse --short HEAD)}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/server:${TAG}"

echo "==> Building ${IMAGE}"
# --config (not --tag) pins the build to Dockerfile.prod. Some gcloud versions
# read `--config=-` as a file name, so use a temporary file.
CLOUDBUILD_YAML="$(mktemp -t cloudbuild.XXXXXX).yaml"
trap 'rm -f "$CLOUDBUILD_YAML"' EXIT
cat > "$CLOUDBUILD_YAML" <<EOF
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: ['build', '-f', 'Dockerfile.prod', '-t', '${IMAGE}', '.']
images:
- '${IMAGE}'
EOF

gcloud builds submit \
    --project "${PROJECT}" \
    --gcs-source-staging-dir "gs://${PROJECT}_cloudbuild/source" \
    --config="$CLOUDBUILD_YAML" \
    .

# ';'-separated (see --set-env-vars below) so ADMIN_LABELS may contain commas.
ENV_VARS="MCP_TRANSPORT=streamable-http;MCP_USER_DATA_ROOT=/data/users"
if [[ -n "$ADMIN_LABELS" ]]; then
    ENV_VARS="${ENV_VARS};MCP_ADMIN_LABELS=${ADMIN_LABELS}"
fi
SECRETS="MCP_TOKENS=${SECRET}:latest"
if [[ -n "$OAUTH_SECRET" ]]; then
    : "${PUBLIC_BASE_URL:?PUBLIC_BASE_URL is required with OAUTH_SECRET}"
    SECRETS="${SECRETS},MCP_OAUTH=${OAUTH_SECRET}:latest"
fi
if [[ -n "$PUBLIC_BASE_URL" ]]; then
    ENV_VARS="${ENV_VARS};MCP_PUBLIC_BASE_URL=${PUBLIC_BASE_URL}"
fi

DEPLOY_ARGS=(
    --image="${IMAGE}"
    --region="${REGION}"
    --project="${PROJECT}"
    # One instance: upload/download links and the simulation queue live in
    # process memory.
    --max-instances=1
    --min-instances=0
    --memory=4Gi
    --cpu=2
    --timeout=3600
    # Connections per instance. Simulations are limited separately by the
    # server's own queue, so this only needs to cover open MCP requests.
    --concurrency=80
    --cpu-boost
    --no-cpu-throttling
    --execution-environment=gen2
    # Bearer tokens (MCP_TOKENS) or OAuth sign-in (MCP_OAUTH) authenticate
    # callers; /health, the sign-in pages and the one-time /files links must
    # be reachable without Google Cloud credentials.
    --allow-unauthenticated
    --set-secrets="${SECRETS}"
    --set-env-vars="^;^${ENV_VARS}"
)
if [[ -n "$SERVICE_ACCOUNT" ]]; then
    DEPLOY_ARGS+=(--service-account="${SERVICE_ACCOUNT}")
fi
if [[ -n "$BUCKET" ]]; then
    # Keep uploads and results across instance restarts.
    DEPLOY_ARGS+=(
        --add-volume="name=userdata,type=cloud-storage,bucket=${BUCKET}"
        --add-volume-mount="volume=userdata,mount-path=/data/users"
    )
else
    echo "==> BUCKET not set: per-user files are lost when the instance restarts"
fi

echo "==> Deploying ${SERVICE} to Cloud Run (${REGION})"
gcloud run deploy "${SERVICE}" "${DEPLOY_ARGS[@]}"

URL="$(gcloud run services describe "${SERVICE}" \
        --region="${REGION}" --project="${PROJECT}" \
        --format='value(status.url)')"
echo "==> Deployed: ${URL}"
echo "==> Smoke-test with: SVC_URL=${URL} TOKEN=<your-token> ./scripts/smoke.sh"
