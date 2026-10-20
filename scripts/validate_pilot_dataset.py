from __future__ import annotations

import argparse
from pathlib import Path

from sentinel_pomdp.pilot import PilotDataset, validate_dataset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    dataset = PilotDataset.model_validate_json(args.dataset.read_text(encoding="utf-8"))
    report = validate_dataset(dataset)
    print(report.model_dump_json(indent=2))
    raise SystemExit(0 if report.valid else 1)


if __name__ == "__main__":
    main()
