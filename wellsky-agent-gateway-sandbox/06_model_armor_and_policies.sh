#!/usr/bin/env bash
# Model Armor templates + gateway authz extensions (IAP dry-run, IAP enforced, Model Armor) + policies.
# The IAP policy starts on the DRY_RUN extension; flip with: ./06_model_armor_and_policies.sh enforce
set -euo pipefail; source "$(dirname "$0")/env.sh"
H=(-H "Authorization: Bearer $(tok)" -H "Content-Type: application/json")
NS=https://networkservices.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION
NSEC=https://networksecurity.googleapis.com/v1beta1/projects/$PROJECT_ID/locations/$REGION
GW=projects/$PROJECT_ID/locations/$REGION/agentGateways/$GW_NAME
EXT=projects/$PROJECT_ID/locations/$REGION/authzExtensions

if [ "${1:-}" = "enforce" ] || [ "${1:-}" = "dryrun" ]; then
  [ "$1" = "enforce" ] && E=${PREFIX}-iap-enforced || E=${PREFIX}-iap-dryrun
  curl -sS -X PATCH "${H[@]}" "$NSEC/authzPolicies/${PREFIX}-gw-iap?updateMask=customProvider" \
    -d "{\"customProvider\":{\"authzExtension\":{\"resources\":[\"$EXT/$E\"]}}}"; exit 0
fi

# Model Armor: request template (prompt injection/jailbreak, PII/PHI via SDP basic, RAI) and response template.
MA=https://modelarmor.$REGION.rep.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION/templates
for t in request response; do
curl -sS -X POST "${H[@]}" "$MA?templateId=${PREFIX}-$t" -d '{
  "labels": {"owner":"searce-sc","purpose":"wellsky-replica"},
  "filterConfig": {
    "piAndJailbreakFilterSettings": {"filterEnforcement": "ENABLED", "confidenceLevel": "MEDIUM_AND_ABOVE"},
    "sdpSettings": {"basicConfig": {"filterEnforcement": "ENABLED"}},
    "maliciousUriFilterSettings": {"filterEnforcement": "ENABLED"},
    "raiSettings": {"raiFilters": [
      {"filterType": "DANGEROUS", "confidenceLevel": "MEDIUM_AND_ABOVE"},
      {"filterType": "HARASSMENT", "confidenceLevel": "MEDIUM_AND_ABOVE"}]}},
  "templateMetadata": {"logTemplateOperations": true, "logSanitizeOperations": true}}' | head -c 300; echo
done

# Authz extensions. Note failOpen: Google's own dry-run sample fails OPEN.
mkext(){ curl -sS -X POST "${H[@]}" "$NS/authzExtensions?authzExtensionId=$1" -d "$2" | head -c 400; echo; }
mkext ${PREFIX}-iap-dryrun   '{"service":"iap.googleapis.com","failOpen":true,"timeout":"1s","metadata":{"iamEnforcementMode":"DRY_RUN","iapPolicyVersion":"V1"}}'
mkext ${PREFIX}-iap-enforced '{"service":"iap.googleapis.com","failOpen":false,"timeout":"1s","metadata":{"iapPolicyVersion":"V1"}}'
mkext ${PREFIX}-model-armor "{\"service\":\"modelarmor.$REGION.rep.googleapis.com\",\"failOpen\":false,\"timeout\":\"1s\",
  \"metadata\":{\"model_armor_settings\":\"[{\\\"request_template_id\\\":\\\"projects/$PROJECT_ID/locations/$REGION/templates/${PREFIX}-request\\\",\\\"response_template_id\\\":\\\"projects/$PROJECT_ID/locations/$REGION/templates/${PREFIX}-response\\\"}]\"}}"
sleep 30
mkpol(){ curl -sS -X POST "${H[@]}" "$NSEC/authzPolicies?authzPolicyId=$1" -d "{
  \"policyProfile\":\"$2\",\"action\":\"CUSTOM\",\"target\":{\"resources\":[\"$GW\"]},
  \"labels\":{\"owner\":\"searce-sc\"},
  \"customProvider\":{\"authzExtension\":{\"resources\":[\"$EXT/$3\"]}}}" | head -c 400; echo; }
mkpol ${PREFIX}-gw-iap REQUEST_AUTHZ ${PREFIX}-iap-dryrun
mkpol ${PREFIX}-gw-model-armor CONTENT_AUTHZ ${PREFIX}-model-armor
