import os
import json
import re
import random
from datetime import datetime

# --- KONFIGURASI ---
# Folder target otomatis di direktori tempat script ini berada
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET_FOLDER = SCRIPT_DIR  # semua file dicari & hasil disimpan di folder ini
OUTPUT_FILENAME_PREFIX = "merge_"
PAUSE_BETWEEN_CLIPS = 0.1  # jeda antar klip (0.0 untuk tanpa jeda)
# ---------------------

def get_sort_key(filename):
    """Kunci sortir 'natural' agar checkpoint_10 muncul setelah checkpoint_9."""
    parts = re.split(r'(\d+)', filename)
    key_parts = []
    for part in parts:
        key_parts.append(int(part) if part.isdigit() else part.lower())
    return tuple(key_parts)

def find_checkpoint_files(folder):
    """Cari semua file JSON yang bukan 'pos*.json'."""
    all_files = []
    try:
        for f in os.listdir(folder):
            if f.endswith(".json") and not re.match(r"^pos\d+\.json$", f, re.IGNORECASE):
                all_files.append(f)
    except FileNotFoundError:
        return None

    all_files.sort(key=get_sort_key)
    return [os.path.join(folder, f) for f in all_files]

def main():
    print(f"Starting 'smart merge' process in folder: '{TARGET_FOLDER}'")

    checkpoint_files = find_checkpoint_files(TARGET_FOLDER)
    if checkpoint_files is None:
        print(f"Error: Folder '{TARGET_FOLDER}' not found.")
        return

    if not checkpoint_files:
        print("No checkpoint files found to merge.")
        return

    print(f"Found {len(checkpoint_files)} files to merge:")
    for f in checkpoint_files:
        print(f"  -> {os.path.basename(f)}")

    merged_data = []
    total_time_offset = 0.0

    for filepath in checkpoint_files:
        filename = os.path.basename(filepath)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, list) or not data:
                print(f"- Skipping {filename} (empty or invalid format)")
                continue

            data.sort(key=lambda f: f.get("time", 0.0))

            base_time = data[0].get("time", 0.0)
            last_time = data[-1].get("time", 0.0)
            clip_duration = last_time - base_time

            print(f"+ Processing {filename} (duration: {clip_duration:.2f}s)")

            for frame in data:
                new_frame = frame.copy()
                original_frame_time = frame.get("time", 0.0)
                new_frame["time"] = (original_frame_time - base_time) + total_time_offset
                merged_data.append(new_frame)

            total_time_offset += clip_duration
            print(f"  ...Time offset: {total_time_offset:.2f}s")

            if PAUSE_BETWEEN_CLIPS > 0:
                total_time_offset += PAUSE_BETWEEN_CLIPS
                print(f"  ...Added {PAUSE_BETWEEN_CLIPS}s pause (new offset: {total_time_offset:.2f}s)")

        except Exception as e:
            print(f"✘ Error processing {filename}: {e}")

    if not merged_data:
        print("No valid data was merged.")
        return

    try:
        rand_num = random.randint(0, 9999)
        output_name = f"{OUTPUT_FILENAME_PREFIX}{rand_num:04d}.json"
        output_path = os.path.join(TARGET_FOLDER, output_name)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(merged_data, f, separators=(',', ':'))

        final_duration = merged_data[-1].get("time", 0.0)
        print("\n✔ Merge Complete!")
        print(f"Saved {len(merged_data)} frames → {output_path}")
        print(f"Total merged duration: {final_duration:.2f}s")

    except Exception as e:
        print(f"✘ Error saving merged file: {e}")

if __name__ == "__main__":
    main()