#!/bin/bash
# Upload SimBench training data to GCS
# Run this from a machine with GCS access (e.g., a GCE VM or local with gcloud auth)

set -e

DATA_DIR=${1:-/tmp/simbench_train_data}
GCS_BUCKET=${2:-gs://ai-studio-bucket-347838016394-us-east1/usersim-models/simbench_train}

echo "Uploading SimBench training data to GCS"
echo "  Source: $DATA_DIR"
echo "  Destination: $GCS_BUCKET"

# Check if gsutil is available
if ! command -v gsutil &> /dev/null; then
    if ! command -v gcloud &> /dev/null; then
        echo "ERROR: Neither gsutil nor gcloud found. Install Google Cloud SDK first."
        exit 1
    fi
    # Use gcloud storage instead
    UPLOAD_CMD="gcloud storage cp"
else
    UPLOAD_CMD="gsutil -m cp"
fi

# Upload data
echo "Uploading armA_humandist..."
$UPLOAD_CMD -r $DATA_DIR/armA_humandist $GCS_BUCKET/data/

echo "Uploading distill_pool.jsonl..."
$UPLOAD_CMD $DATA_DIR/distill_pool.jsonl $GCS_BUCKET/data/

echo "Uploading dedup_report.json..."
$UPLOAD_CMD $DATA_DIR/dedup_report.json $GCS_BUCKET/data/

echo "Uploading summary.json..."
$UPLOAD_CMD $DATA_DIR/summary.json $GCS_BUCKET/data/

# Upload scripts
SCRIPTS_DIR=$(dirname "$0")
echo "Uploading training scripts..."
$UPLOAD_CMD $SCRIPTS_DIR/sft_simbench_qlora.py $GCS_BUCKET/scripts/
$UPLOAD_CMD $SCRIPTS_DIR/teacher_distill.py $GCS_BUCKET/scripts/
$UPLOAD_CMD $SCRIPTS_DIR/DATA_CARD.md $GCS_BUCKET/

echo "Upload complete!"
echo ""
echo "To verify:"
echo "  gsutil ls -la $GCS_BUCKET/"
