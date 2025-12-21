#!/usr/bin/env python3
"""
process_all_json_bypass.py

Remove duplicate positions in top-level JSON arrays and bypass removed time gaps.

By default:
 - duplicate positions are removed (keep earliest)
 - original time fields are ADJUSTED by removing time gaps introduced by removed entries
   (i.e. removed entries' durations are subtracted so the next kept entry happens "sooner")
 - times are NOT fully re-assigned in fixed steps unless --reassign-times is passed.

Behavior:
 - Creates ONE random backup folder (timestamp + random hex) at start,
   all original JSON files are moved there before rewriting.

Flags:
  --tol                 position tolerance per-component (default 0.1)
  --global-dedupe       remove later entries whose position matches an earlier kept one
  --min-consecutive N   only start dropping when a run has ≥N consecutive repeats
  --reassign-times      fully reassign times (start + i*delta)
  --delta               delta used with --reassign-times (default 0.016)
  --keep-first-time     preserve original first kept entry's time when reassigning
  --backup-root         base folder for random backups (default 'backups')
  --backup-prefix       optional prefix for random backup folder name
  --no-backup           disable backup (default = ON)
  --pretty              pretty-print JSON output
  --force-rewrite       always rewrite files even if unchanged
"""
import argparse
import json
import os
import shutil
import secrets
import datetime
from typing import Any, Dict, List, Tuple

# -----------------------------------------------------------
# Utility
# -----------------------------------------------------------
def pos_tuple(entry: Dict[str, Any]) -> Tuple[float, float, float]:
    p = entry.get("position", {})
    try:
        return (float(p.get("x", 0.0)), float(p.get("y", 0.0)), float(p.get("z", 0.0)))
    except Exception:
        return (0.0, 0.0, 0.0)

def almost_equal(a: Tuple[float,float,float], b: Tuple[float,float,float], tol: float) -> bool:
    return all(abs(x-y) <= tol for x,y in zip(a,b))

def quantize_key(pos: Tuple[float,float,float], tol: float) -> Tuple[int,int,int]:
    q = tol if tol > 0 else 1e-9
    return (int(round(pos[0] / q)), int(round(pos[1] / q)), int(round(pos[2] / q)))

# -----------------------------------------------------------
# Compression logic
# -----------------------------------------------------------
def compress_consecutive_indices(data: List[Dict[str,Any]], tol: float = 0.1, min_consecutive: int = 2) -> List[int]:
    if not data:
        return []
    kept = []
    prev_pos = None
    run = 0
    for i, e in enumerate(data):
        cur = pos_tuple(e)
        if prev_pos is None:
            kept.append(i)
            prev_pos, run = cur, 1
            continue
        if almost_equal(cur, prev_pos, tol):
            run += 1
            if run >= min_consecutive:
                continue
            kept.append(i)
        else:
            kept.append(i)
            prev_pos, run = cur, 1
    return kept

def compress_global_indices(data: List[Dict[str,Any]], tol: float = 0.1) -> List[int]:
    if not data:
        return []
    seen, kept = set(), []
    for i, e in enumerate(data):
        key = quantize_key(pos_tuple(e), tol)
        if key in seen:
            continue
        seen.add(key)
        kept.append(i)
    return kept

# -----------------------------------------------------------
# Time adjustment
# -----------------------------------------------------------
def reassign_times(data: List[Dict[str,Any]], delta: float = 0.016, keep_first_time: bool = False) -> List[Dict[str,Any]]:
    if not data:
        return []
    start = float(data[0].get("time", 0.0)) if keep_first_time else 0.0
    out = []
    for i, e in enumerate(data):
        e2 = dict(e)
        e2["time"] = start + i * delta
        out.append(e2)
    return out

def bypass_removed_times(raw: List[Dict[str,Any]], kept_idx: List[int]) -> List[Dict[str,Any]]:
    if not raw:
        return []
    n = len(raw)
    times = [float(e.get("time", 0.0)) for e in raw]
    deltas = [0.0] + [times[i] - times[i-1] for i in range(1, n)]
    kept = set(kept_idx)
    removed_sum = 0.0
    out = []
    for i in range(n):
        if i in kept:
            e = dict(raw[i])
            e["time"] = times[i] - removed_sum
            out.append(e)
        else:
            removed_sum += deltas[i]
    return out

# -----------------------------------------------------------
# Backup utilities
# -----------------------------------------------------------
def make_single_backup_folder(backup_root: str = "backups", prefix: str | None = None) -> str:
    os.makedirs(backup_root, exist_ok=True)
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    rand = secrets.token_hex(6)
    folder_name = f"{prefix + '_' if prefix else ''}{ts}_{rand}"
    folder = os.path.join(backup_root, folder_name)
    os.makedirs(folder, exist_ok=True)
    return folder

# -----------------------------------------------------------
# Processing
# -----------------------------------------------------------
def process_file(path: str, args: argparse.Namespace, backup_folder: str | None) -> Tuple[bool,int,int]:
    name = os.path.basename(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        print(f"  [skip] {name} - invalid JSON: {e}")
        return (False, 0, 0)

    if not isinstance(raw, list):
        print(f"  [skip] {name} - not an array")
        return (False, 0, 0)

    orig_count = len(raw)
    if args.global_dedupe:
        kept = compress_global_indices(raw, tol=args.tol)
    else:
        kept = compress_consecutive_indices(raw, tol=args.tol, min_consecutive=args.min_consecutive)

    if args.reassign_times:
        output = reassign_times([raw[i] for i in kept], args.delta, args.keep_first_time)
    else:
        output = bypass_removed_times(raw, kept)

    removed = orig_count - len(output)
    if removed <= 0 and not (args.force_rewrite or args.reassign_times):
        return (False, len(output), orig_count)

    # --- Backup handling ---
    if backup_folder:
        dest = os.path.join(backup_folder, name)
        shutil.move(path, dest)
        print(f"  backup → {dest}")

    # --- Write new file ---
    with open(path, "w", encoding="utf-8") as f:
        if args.pretty:
            json.dump(output, f, ensure_ascii=False, indent=2)
        else:
            json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    return (True, len(output), orig_count)

# -----------------------------------------------------------
# CLI
# -----------------------------------------------------------
def find_json_files(d: str) -> List[str]:
    return sorted(
        os.path.join(d, n)
        for n in os.listdir(d)
        if n.lower().endswith(".json") and os.path.isfile(os.path.join(d, n))
    )

def main():
    p = argparse.ArgumentParser(description="Remove duplicate positions (keep earliest) and bypass removed time gaps.")
    p.add_argument("--tol", type=float, default=0.1)
    p.add_argument("--global-dedupe", action="store_true")
    p.add_argument("--min-consecutive", type=int, default=2)
    p.add_argument("--reassign-times", action="store_true")
    p.add_argument("--delta", type=float, default=0.016)
    p.add_argument("--keep-first-time", action="store_true")
    p.add_argument("--pretty", action="store_true")
    p.add_argument("--force-rewrite", action="store_true")
    p.add_argument("--backup-root", type=str, default="backups")
    p.add_argument("--backup-prefix", type=str, default=None)
    p.add_argument("--no-backup", action="store_true", help="disable automatic random backup (default = ON)")
    args = p.parse_args()

    here = os.getcwd()
    json_files = find_json_files(here)
    if not json_files:
        print("No .json files found.")
        return

    # Create one random folder for all backups
    backup_folder = None
    if not args.no_backup:
        backup_folder = make_single_backup_folder(args.backup_root, args.backup_prefix)
        print(f"Created backup folder: {backup_folder}")

    print(f"Found {len(json_files)} JSON files in {here}")
    for path in json_files:
        name = os.path.basename(path)
        print(f"Processing {name} ...")
        try:
            mod, kept, orig = process_file(path, args, backup_folder)
            if mod:
                print(f"  updated: kept {kept}/{orig}")
            else:
                print(f"  unchanged: kept {kept}/{orig}")
        except Exception as e:
            print(f"  error processing {name}: {e}")

if __name__ == "__main__":
    main()