# Source this, then:  load_proxy SECRET_NAME SECRET_PROJECT GCS_URI
# Exports PROXY_URL from Secret Manager if it gives a value, else from the private GCS object GCS_URI. Prints only WHICH source was used,
# never the value (stderr of the readers is discarded). Returns 1 with no fallback to anything else when neither gives an http(s) URL.
load_proxy() {
  local secret=${1:-} project=${2:-} uri=${3:-} v="" src=""
  if [ -n "$secret" ] && [ -n "$project" ]; then
    v=$(gcloud secrets versions access latest --secret="$secret" --project="$project" 2>/dev/null) && src=secret_manager
  fi
  if [ -z "$v" ] && [ -n "$uri" ]; then
    v=$(gsutil -q cat "$uri" 2>/dev/null | tr -d '\r\n') && src=gcs_object
  fi
  [ -n "$v" ] || { echo "proxy: no source gave a value" >&2; return 1; }
  case "$v" in http://*|https://*) ;; *) echo "proxy: the value is not an http(s) URL" >&2; return 1 ;; esac
  export PROXY_URL="$v"
  echo "proxy: loaded from $src" >&2
}
