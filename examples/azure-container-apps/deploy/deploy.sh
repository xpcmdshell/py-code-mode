#!/bin/bash
# Deploy py-code-mode agent to Azure Container Apps
#
# This deploys:
# - Session server (internal): Code execution with tools
# - Agent server (external): AutoGen agent with Claude via Azure AI Foundry
#
# Prerequisites:
# - Azure CLI installed and logged in (az login)
# - Docker installed (for building images)
# - jq installed (for JSON parsing)
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

# Step 2: Deploy infrastructure (ACR, Storage, AI Services, Environment)
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
AI_ENDPOINT=$(echo "$INFRA_OUTPUT" | jq -r '.openAiEndpoint.value // empty')

echo "   ACR: $ACR_SERVER"
echo "   AI Endpoint: ${AI_ENDPOINT:-'(configure manually)'}"
echo "   Storage: $STORAGE_NAME"

# Step 3: Build and push Docker images
echo "[3/7] Building and pushing Docker images..."
cd "$REPO_ROOT"

# Login to ACR
az acr login --name "$ACR_NAME" --output none

# Build session server image
echo "   Building session server..."
docker build --platform linux/amd64 \
    -f examples/azure-container-apps/Dockerfile \
    -t "$ACR_SERVER/py-code-mode-session:latest" . 2>&1 | tail -3

# Build agent server image
echo "   Building agent server..."
docker build --platform linux/amd64 \
    -f examples/azure-container-apps/Dockerfile.agent \
    -t "$ACR_SERVER/py-code-mode-agent:latest" . 2>&1 | tail -3

# Push images
echo "   Pushing images..."
docker push "$ACR_SERVER/py-code-mode-session:latest" 2>&1 | tail -2
docker push "$ACR_SERVER/py-code-mode-agent:latest" 2>&1 | tail -2

# Step 4: Upload config files to storage
echo "[4/7] Uploading configuration files..."
STORAGE_KEY=$(az storage account keys list \
    --account-name "$STORAGE_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "[0].value" -o tsv)

# Create directories in file share
az storage directory create \
    --account-name "$STORAGE_NAME" \
    --account-key "$STORAGE_KEY" \
    --share-name "configs" \
    --name "tools" \
    --output none 2>/dev/null || true

az storage directory create \
    --account-name "$STORAGE_NAME" \
    --account-key "$STORAGE_KEY" \
    --share-name "configs" \
    --name "skills" \
    --output none 2>/dev/null || true

# Upload tools from shared directory
SHARED_DIR="$SCRIPT_DIR/../../shared"
if [[ -d "$SHARED_DIR/tools" ]]; then
    for tool in "$SHARED_DIR/tools"/*.yaml; do
        if [[ -f "$tool" ]]; then
            az storage file upload \
                --account-name "$STORAGE_NAME" \
                --account-key "$STORAGE_KEY" \
                --share-name "configs" \
                --source "$tool" \
                --path "tools/$(basename "$tool")" \
                --output none
            echo "   Uploaded: tools/$(basename "$tool")"
        fi
    done
fi

# Upload skills from shared directory
if [[ -d "$SHARED_DIR/skills" ]]; then
    for skill in "$SHARED_DIR/skills"/*.py; do
        if [[ -f "$skill" ]]; then
            az storage file upload \
                --account-name "$STORAGE_NAME" \
                --account-key "$STORAGE_KEY" \
                --share-name "configs" \
                --source "$skill" \
                --path "skills/$(basename "$skill")" \
                --output none
            echo "   Uploaded: skills/$(basename "$skill")"
        fi
    done
fi

# Step 5: Deploy Container Apps
echo "[5/7] Deploying Container Apps..."
APP_OUTPUT=$(az deployment group create \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$SCRIPT_DIR/app.bicep" \
    --parameters \
        environmentId="$ENV_ID" \
        acrLoginServer="$ACR_SERVER" \
        acrUsername="$ACR_NAME" \
        acrPassword="$ACR_PASSWORD" \
        openAiEndpoint="${AI_ENDPOINT:-}" \
    --query 'properties.outputs' \
    --output json)

AGENT_URL=$(echo "$APP_OUTPUT" | jq -r '.agentUrl.value')

# Step 6: Grant agent managed identity access to Azure AI
echo "[6/7] Configuring Azure AI access..."
AGENT_PRINCIPAL_ID=$(az containerapp show \
    --name agent-server \
    --resource-group "$RESOURCE_GROUP" \
    --query "identity.principalId" -o tsv)

# Grant access to AI services if endpoint was deployed
if [[ -n "$AI_ENDPOINT" ]]; then
    AI_RESOURCE_NAME=$(echo "$AI_ENDPOINT" | sed 's|https://||' | sed 's|\..*||')
    az role assignment create \
        --role "Cognitive Services User" \
        --assignee-object-id "$AGENT_PRINCIPAL_ID" \
        --assignee-principal-type ServicePrincipal \
        --scope "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.CognitiveServices/accounts/$AI_RESOURCE_NAME" \
        --output none 2>/dev/null || echo "   Role assignment may already exist"
fi

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
