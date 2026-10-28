#!/bin/sh
# Same as preprovision.ps1: object id and login from the ARM token claims, no Graph call.
set -e
TOKEN=$(az account get-access-token --query accessToken -o tsv)
PAYLOAD=$(echo "$TOKEN" | cut -d. -f2 | tr '_-' '/+')
PAD=$(( (4 - ${#PAYLOAD} % 4) % 4 )); i=0; while [ $i -lt $PAD ]; do PAYLOAD="$PAYLOAD="; i=$((i+1)); done
CLAIMS=$(echo "$PAYLOAD" | base64 -d 2>/dev/null)
OBJECT_ID=${DEPLOYER_OBJECT_ID:-$(echo "$CLAIMS" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("oid",""))')}
LOGIN=${DEPLOYER_LOGIN:-$(echo "$CLAIMS" | python3 -c 'import json,sys; c=json.load(sys.stdin); print(c.get("upn") or c.get("unique_name") or c.get("email") or c.get("name") or "")')}
IP=${DEPLOYER_IP:-$(curl -s --max-time 10 https://api.ipify.org || echo "")}
[ -z "$OBJECT_ID" ] && { echo "no oid claim in token"; exit 1; }
[ -z "$LOGIN" ] && { echo "no login claim in token; azd env set DEPLOYER_LOGIN <value>"; exit 1; }
azd env set DEPLOYER_OBJECT_ID "$OBJECT_ID"
azd env set DEPLOYER_LOGIN "$LOGIN"
azd env set DEPLOYER_IP "$IP"
echo "Deployer: $LOGIN ($OBJECT_ID), IP: $IP"
