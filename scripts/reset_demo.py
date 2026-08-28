import os
import json
from pathlib import Path

def main():
    root_dir = Path(__file__).resolve().parent.parent

    # Files to delete
    files_to_delete = [
        root_dir / "data" / "orchestrai.db",
        root_dir / "data" / "orchestrai.db-shm",
        root_dir / "data" / "orchestrai.db-wal",
    ]

    for f in files_to_delete:
        if f.exists():
            f.unlink()
            print(f"Deleted: {f}")

    # Delete PDFs
    generated_dir = root_dir / "generated"
    if generated_dir.exists():
        for pdf_file in generated_dir.glob("*.pdf"):
            pdf_file.unlink()
            print(f"Deleted: {pdf_file}")
    
    # Reset sequence
    seq_file = generated_dir / "_po_seq.json"
    if generated_dir.exists():
        with open(seq_file, "w") as f:
            json.dump({"n": 1}, f)
        print(f"Reset: {seq_file}")

    print("Demo reset complete.")

if __name__ == "__main__":
    main()
