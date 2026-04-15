"""CLI ingestion script. Ingests a single file or the sample PDF if no arg is given.

Usage:
    python -m entrypoint.ingest                         # seeds TechNova sample if registry empty
    python -m entrypoint.ingest path/to/doc.pdf         # ingests a specific file
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings
from src.pipelines.embedding_pipeline import ingest_file, load_sample_if_empty


def main() -> None:
    args = sys.argv[1:]
    if not args:
        doc = load_sample_if_empty()
        if doc:
            print(f"Seeded sample: {doc.filename}  pages={doc.pages}  chunks={doc.chunks}")
        else:
            print("Registry already populated or sample PDF missing; nothing to do.")
        return

    for a in args:
        path = Path(a)
        if not path.exists():
            print(f"[skip] not found: {path}")
            continue
        doc = ingest_file(path)
        print(f"Ingested: {doc.filename}  pages={doc.pages}  chunks={doc.chunks}  sections={doc.sections}")


if __name__ == "__main__":
    main()
