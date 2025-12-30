#!/bin/bash
# Deploy py-code-mode agent to Azure Container Apps
#
# This deploys:
# - Azure Cache for Redis: Stores tools, skills, deps
# - Azure OpenAI (GPT-4o): LLM for agent
# - Session server (internal): Code execution with tools
# - Agent server (external): AutoGen agent with GPT-4o
#
# Prerequisites:
# - Azure CLI installed and logged in (az login)
# - Docker installed (for building images)
# - jq installed (for JSON parsing)
# - Python 3.11+ with py-code-mode installed (for bootstrap)
#
# Usage:
#   ./deploy.sh [resource-group] [location]
#
# Example:
#   ./deploy.sh py-code-mode-demo eastus

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Configuration
RESOURCE_GROUP="${1:-py-code-mode-demo}"
LOCATION="${2:-eastus}"

echo "============================================"
echo "  py-code-mode Azure Deployment"
echo "============================================"
echo ""
echo "Resource Group: $RESOURCE_GROUP"
echo "Location: $LOCATION"
echo ""

# Step 1: Create resource group
echo "[1/7] Creating resource group..."
az group create \
    --name "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none

# Step 2: Deploy infrastructure (ACR, Storage, Redis, AI Services, Environment)
echo "[2/7] Deploying infrastructure..."
INFRA_OUTPUT=$(az deployment group create \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$SCRIPT_DIR/infra.bicep" \
    --query 'properties.outputs' \
    --output json)

# Extract outputs
ACR_NAME=$(echo "$INFRA_OUTPUT" | jq -r '.acrName.value')
ACR_SERVER=$(echo "$INFRA_OUTPUT" | jq -r '.acrLoginServer.value')
ACR_PASSWORD=$(echo "$INFRA_OUTPUT" | jq -r '.acrPassword.value')
ENV_ID=$(echo "$INFRA_OUTPUT" | jq -r '.environmentId.value')
STORAGE_NAME=$(echo "$INFRA_OUTPUT" | jq -r '.storageAccountName.value')
REDIS_HOSTNAME=$(echo "$INFRA_OUTPUT" | jq -r '.redisHostname.value')
REDIS_PRIMARY_KEY=$(echo "$INFRA_OUTPUT" | jq -r '.redisPrimaryKey.value')
REDIS_CONNECTION_STRING=$(echo "$INFRA_OUTPUT" | jq -r '.redisConnectionString.value')
AZURE_OPENAI_ENDPOINT=$(echo "$INFRA_OUTPUT" | jq -r '.openAiEndpoint.value')
AZURE_OPENAI_DEPLOYMENT=$(echo "$INFRA_OUTPUT" | jq -r '.openAiDeployment.value')

echo "   ACR: $ACR_SERVER"
echo "   Storage: $STORAGE_NAME"
echo "   Redis: $REDIS_HOSTNAME"

# Step 3: Build and push Docker images
# Note: Uses buildx for cross-platform builds (ARM Mac -> AMD64 Linux)
# If builds fail due to disk space, run: docker builder prune
echo "[3/7] Building and pushing Docker images..."
cd "$REPO_ROOT"

# Login to ACR
az acr login --name "$ACR_NAME" --output none

# Build and push session server image (AMD64 for Azure Container Apps)
echo "   Building and pushing session server..."
docker buildx build --platform linux/amd64 --push \
    -f examples/azure-container-apps/Dockerfile \
    -t "$ACR_SERVER/py-code-mode-session:latest" . 2>&1 | tail -5

# Build and push agent server image (AMD64 for Azure Container Apps)
echo "   Building and pushing agent server..."
docker buildx build --platform linux/amd64 --push \
    -f examples/azure-container-apps/Dockerfile.agent \
    -t "$ACR_SERVER/py-code-mode-agent:latest" . 2>&1 | tail -5

# Step 4: Bootstrap Redis with tools, skills, and deps
echo "[4/7] Bootstrapping tools, skills, and deps to Redis..."
SHARED_DIR="$SCRIPT_DIR/../../shared"

# Use built-in CLI for bootstrapping (run from repo root for module resolution)
cd "$REPO_ROOT"

echo "   Bootstrapping tools..."
uv run python -m py_code_mode.cli.store bootstrap \
    --type tools \
    --source "$SHARED_DIR/tools" \
    --target "$REDIS_CONNECTION_STRING" \
    --prefix "pycodemode:tools" \
    --clear

echo "   Bootstrapping skills..."
uv run python -m py_code_mode.cli.store bootstrap \
    --type skills \
    --source "$SHARED_DIR/skills" \
    --target "$REDIS_CONNECTION_STRING" \
    --prefix "pycodemode:skills" \
    --clear

echo "   Bootstrapping deps..."
uv run python -m py_code_mode.cli.store bootstrap \
    --type deps \
    --target "$REDIS_CONNECTION_STRING" \
    --prefix "pycodemode:deps" \
    --deps "requests>=2.31" "beautifulsoup4>=4.12" "pandas>=2.0" \
    --clear

# Step 5: Generate auth token for session server
echo "[5/7] Generating session auth token..."
SESSION_AUTH_TOKEN=$(openssl rand -hex 32)
echo "   Token generated: $SESSION_AUTH_TOKEN"
echo "   (Copy this token - it will not be saved to disk)"

# Step 6: Deploy Container Apps
echo "[6/7] Deploying Container Apps..."
APP_OUTPUT=$(az deployment group create \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$SCRIPT_DIR/app.bicep" \
    --parameters \
        environmentId="$ENV_ID" \
        acrLoginServer="$ACR_SERVER" \
        acrUsername="$ACR_NAME" \
        acrPassword="$ACR_PASSWORD" \
        redisUrl="$REDIS_CONNECTION_STRING" \
        sessionAuthToken="$SESSION_AUTH_TOKEN" \
        azureOpenAiEndpoint="$AZURE_OPENAI_ENDPOINT" \
        azureOpenAiDeployment="$AZURE_OPENAI_DEPLOYMENT" \
    --query 'properties.outputs' \
    --output json)

AGENT_URL=$(echo "$APP_OUTPUT" | jq -r '.agentUrl.value')

# Step 7: Wait for apps to be ready
echo "[7/7] Waiting for apps to be ready..."
for i in {1..30}; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$AGENT_URL/health" 2>/dev/null || echo "000")
    if [[ "$STATUS" == "200" ]]; then
        echo "   Agent is healthy!"
        break
    fi
    echo "   Waiting... ($i/30)"
    sleep 5
done

echo ""
echo "============================================"
echo "  Deployment Complete!"
echo "============================================"
echo ""
echo "Agent URL: $AGENT_URL"
echo "Redis Host: $REDIS_HOSTNAME"
echo ""
echo "Saved files:"
echo "  $SCRIPT_DIR/.agent_url"
echo "  $SCRIPT_DIR/.resource_group"
echo ""
echo "Submit a task:"
echo "  curl -X POST $AGENT_URL/task \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"task\": \"Scan scanme.nmap.org and tell me what ports are open\"}'"
echo ""
echo "Check health:"
echo "  curl $AGENT_URL/health"
echo ""
echo "View logs:"
echo "  az containerapp logs show --name agent-server --resource-group $RESOURCE_GROUP --follow"
echo "  az containerapp logs show --name session-server --resource-group $RESOURCE_GROUP --follow"
echo ""
echo "Cleanup when done:"
echo "  az group delete --name $RESOURCE_GROUP --yes --no-wait"
echo ""

# Save outputs for later use
echo "$AGENT_URL" > "$SCRIPT_DIR/.agent_url"
echo "$RESOURCE_GROUP" > "$SCRIPT_DIR/.resource_group"
