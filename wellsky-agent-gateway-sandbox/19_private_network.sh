#!/usr/bin/env bash
# Private network for a private MCP server (pattern from Google's GE -> private MCP codelab):
# VPC + /28 subnet with Private Google Access, PSC network attachment for the gateway,
# PSC endpoint for Google APIs, and a private run.app zone pointing at that endpoint.
set -euo pipefail; source "$(dirname "$0")/env.sh"
NET=${PREFIX}-vnet; SUB=${PREFIX}-agw-subnet
gcloud compute networks describe $NET >/dev/null 2>&1 || gcloud compute networks create $NET --subnet-mode=custom --quiet
gcloud compute networks subnets describe $SUB --region $REGION >/dev/null 2>&1 || \
  gcloud compute networks subnets create $SUB --network=$NET --region=$REGION --range=192.168.10.0/28 --enable-private-ip-google-access --quiet
gcloud compute network-attachments describe ${PREFIX}-psc-na --region $REGION >/dev/null 2>&1 || \
  gcloud compute network-attachments create ${PREFIX}-psc-na --region=$REGION --subnets=$SUB --connection-preference=ACCEPT_AUTOMATIC --quiet
gcloud compute addresses describe ${PREFIX}-psc2gapis --global >/dev/null 2>&1 || \
  gcloud compute addresses create ${PREFIX}-psc2gapis --global --purpose=PRIVATE_SERVICE_CONNECT --addresses=172.16.20.20 --network=$NET --quiet
# PSC forwarding rules for Google APIs: 1-20 chars, lowercase letters and digits only.
gcloud compute forwarding-rules describe wskypsc2gapis --global >/dev/null 2>&1 || \
  gcloud compute forwarding-rules create wskypsc2gapis --global --network=$NET --address=${PREFIX}-psc2gapis --target-google-apis-bundle=all-apis --quiet
gcloud dns managed-zones describe ${PREFIX}-priv-run >/dev/null 2>&1 || \
  gcloud dns managed-zones create ${PREFIX}-priv-run --dns-name="run.app." --visibility=private --networks=$NET --description="WellSky replica: run.app via PSC" --quiet
gcloud dns record-sets describe "*.run.app." --zone ${PREFIX}-priv-run --type A >/dev/null 2>&1 || \
  gcloud dns record-sets create "*.run.app." --zone=${PREFIX}-priv-run --type=A --ttl=300 --rrdatas=172.16.20.20 --quiet
gcloud compute network-attachments describe ${PREFIX}-psc-na --region $REGION --format="value(selfLink)"
