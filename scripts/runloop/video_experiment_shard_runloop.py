"""Run the existing video shard on Runloop without relying on GCE metadata.

The Devbox receives Google credentials as a Runloop account secret. Browser
authentication state is mounted separately at runtime and is never part of the
blueprint.
"""

from __future__ import annotations

import google.auth
from google.auth.credentials import with_scopes_if_required

from scripts.vm import video_experiment_shard as shard


def runloop_credentials():
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    return with_scopes_if_required(
        credentials, ["https://www.googleapis.com/auth/cloud-platform"]
    )


shard.gce_credentials = runloop_credentials


if __name__ == "__main__":
    raise SystemExit(shard.main())
