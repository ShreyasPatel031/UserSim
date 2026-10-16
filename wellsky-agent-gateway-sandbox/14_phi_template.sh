#!/usr/bin/env bash
# Healthcare-aware Sensitive Data Protection inspect template, attached to the wsky-request/response
# Model Armor templates (advanced SDP config). The basic config misses SSN, MRN, DOB and diagnoses.
set -euo pipefail; source "$(dirname "$0")/env.sh"
gcloud services enable dlp.googleapis.com --quiet
DLP=https://dlp.googleapis.com/v2/projects/$PROJECT_ID/locations/$REGION/inspectTemplates
curl -sS -X POST -H "Authorization: Bearer $(tok)" -H "Content-Type: application/json" -H "X-Goog-User-Project: $PROJECT_ID" "$DLP" -d '{
  "templateId": "wsky-phi-pii",
  "inspectTemplate": {"displayName": "wsky PHI/PII (WellSky replica)", "inspectConfig": {
    "minLikelihood": "POSSIBLE",
    "infoTypes": [{"name":"US_SOCIAL_SECURITY_NUMBER"},{"name":"DATE_OF_BIRTH"},{"name":"MEDICAL_RECORD_NUMBER"},
      {"name":"US_HEALTHCARE_NPI"},{"name":"MEDICAL_TERM"},{"name":"PERSON_NAME"},{"name":"PHONE_NUMBER"},
      {"name":"EMAIL_ADDRESS"},{"name":"CREDIT_CARD_NUMBER"},{"name":"US_MEDICARE_BENEFICIARY_ID_NUMBER"}],
    "customInfoTypes": [{"infoType": {"name": "WSKY_MRN"}, "likelihood": "LIKELY",
      "regex": {"pattern": "(?i)\\bMRN[:# ]*[0-9A-Z-]{6,}\\b"}}]}}}' | head -c 200; echo
MA_SA=service-$PROJECT_NUMBER@gcp-sa-modelarmor.iam.gserviceaccount.com
for r in roles/dlp.user roles/dlp.reader; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$MA_SA" --role=$r --condition=None --format=none; done
MA=https://modelarmor.$REGION.rep.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION/templates
for t in request response; do
  curl -sS -X PATCH -H "Authorization: Bearer $(tok)" -H "Content-Type: application/json" \
    "$MA/${PREFIX}-$t?updateMask=filterConfig.sdpSettings" -d "{\"filterConfig\":{\"sdpSettings\":{\"advancedConfig\":{
      \"inspectTemplate\":\"projects/$PROJECT_ID/locations/$REGION/inspectTemplates/wsky-phi-pii\"}}}}" | head -c 150; echo
done
