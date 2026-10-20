"""Seed the Knowledge Graph with synthetic enterprise supplier-delay evidence.

Usage:
    uv run python scripts/seed_graph.py [--in-memory]
"""
import argparse
import sys
import logging
from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.repository import InMemoryGraphRepository, Neo4jGraphRepository
from sentinel_pomdp.graph.seed import seed_graph_database

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_graph")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed SentinelPOMDP Knowledge Graph")
    parser.add_argument(
        "--in-memory",
        action="store_true",
        help="Seed an in-memory repository instead of connecting to Neo4j",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("SentinelPOMDP — Knowledge Graph Data Seeding")
    print("=" * 70)

    if args.in_memory:
        print("[*] Mode: Pure-Python InMemoryGraphRepository")
        repo = InMemoryGraphRepository()
    else:
        cm = Neo4jConnectionManager()
        if cm.ping():
            print(f"[*] Mode: Live Neo4j at {cm.config.uri}")
            repo = Neo4jGraphRepository(cm)
        else:
            print(f"[!] Neo4j service at {cm.config.uri} is not reachable.")
            print("    Falling back to InMemoryGraphRepository to verify dataset seeding.")
            repo = InMemoryGraphRepository()

    dataset = generate_supplier_delay_dataset()
    print(f"[*] Generated synthetic dataset: {len(dataset.entities)} entities, {len(dataset.documents)} documents, "
          f"{len(dataset.facts)} facts, {len(dataset.evidence)} evidence items, {len(dataset.links)} links.")

    report = seed_graph_database(repo, dataset)
    print("\n" + report.summary())

    if report.is_success:
        print("[+] Seeding completed successfully with 0 errors!")
        print("=" * 70)
        return 0
    else:
        print("[!] Seeding encountered errors:")
        for err in report.errors:
            print(f"    - {err}")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
