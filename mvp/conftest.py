"""Tests never probe real sites: create_matrix_study checks each site's TLS/DNS unless this is off."""
import os

os.environ.setdefault("MVP_MCP_PROBE_SITES", "0")
