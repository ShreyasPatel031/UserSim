"""Create the hn-sim-1 VM (e2-highcpu-16, Debian 12, the project's compute service account) with the job runner."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from auth import vertex_credentials  # noqa: E402
from google.cloud import compute_v1  # noqa: E402

P, Z = "project-amer-scs-sandbox", "us-central1-b"
NAME = sys.argv[1] if len(sys.argv) > 1 else "hn-sim-1"
TYPE = sys.argv[2] if len(sys.argv) > 2 else "e2-highcpu-16"
inst = compute_v1.Instance(
    name=NAME, machine_type=f"zones/{Z}/machineTypes/{TYPE}",
    disks=[compute_v1.AttachedDisk(boot=True, auto_delete=True, initialize_params=compute_v1.AttachedDiskInitializeParams(
        source_image="projects/debian-cloud/global/images/family/debian-12", disk_size_gb=100))],
    network_interfaces=[compute_v1.NetworkInterface(network="global/networks/main-vpc", subnetwork="regions/us-central1/subnetworks/primary-subnet",
                                                    access_configs=[compute_v1.AccessConfig(name="External NAT")])],
    service_accounts=[compute_v1.ServiceAccount(email="347838016394-compute@developer.gserviceaccount.com",
                                                scopes=["https://www.googleapis.com/auth/cloud-platform"])],
    metadata=compute_v1.Metadata(items=[compute_v1.Items(key="startup-script",
                                                         value=(Path(__file__).parent / "startup.sh").read_text())]),
    labels={"owner": "hn-sim", "purpose": "show-hn-backtest"})
op = compute_v1.InstancesClient(credentials=vertex_credentials()).insert(project=P, zone=Z, instance_resource=inst)
op.result(timeout=300)
print("created", NAME)
