"""Validate and inventory a local Olist ZIP/directory without modifying it."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sentinel_pomdp.olist import OlistDataset,discover_olist,inventory_olist
p=argparse.ArgumentParser(); p.add_argument("--data-path"); p.add_argument("--dataset-version",default="olist-public-2018")
a=p.parse_args(); root=Path(__file__).resolve().parents[1]
d=OlistDataset(Path(a.data_path).resolve() if a.data_path else discover_olist(root))
print(json.dumps(inventory_olist(d,a.dataset_version).to_dict(),indent=2,default=str))
