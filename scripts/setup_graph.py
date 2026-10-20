"""Initialize Neo4j schema constraints and indexes for SentinelPOMDP.

Usage:
    uv run python scripts/setup_graph.py
"""
import sys
import logging
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.repository import Neo4jGraphRepository

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("setup_graph")


def main() -> int:
    print("=" * 70)
    print("SentinelPOMDP — Knowledge Graph Schema & Constraints Setup")
    print("=" * 70)

    cm = Neo4jConnectionManager()
    print(f"Connecting to Neo4j at {cm.config.uri} (user: {cm.config.user})...")

    if not cm.ping():
        print("\n[!] WARNING: Neo4j database service is not reachable at", cm.config.uri)
        print("    To start local Neo4j using Docker Compose, run:")
        print("        docker compose -f infra/compose.yaml up -d")
        print("    Then re-run this setup script.")
        return 1

    repo = Neo4jGraphRepository(cm)
    print("Applying uniqueness constraints and indexes...")
    repo.init_schema_constraints()
    print("[+] Successfully initialized schema constraints and indexes in Neo4j!")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
