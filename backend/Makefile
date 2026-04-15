.PHONY: install install-dev ingest serve query clean test lint

install:
	python -m venv .venv && . .venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt

install-dev: install
	. .venv/bin/activate && pip install pytest ruff

ingest:
	. .venv/bin/activate && python -m entrypoint.ingest

ingest-file:
	. .venv/bin/activate && python -m entrypoint.ingest $(FILE)

serve:
	. .venv/bin/activate && python -m entrypoint.serve

query:
	. .venv/bin/activate && python -m entrypoint.query "$(Q)"

test:
	. .venv/bin/activate && pytest tests/ -v

lint:
	. .venv/bin/activate && ruff check src/ entrypoint/ tests/

clean:
	rm -rf data/vector_store/* data/embeddings/* data/raw/*.pdf data/registry.sqlite
	find . -type d -name __pycache__ -exec rm -rf {} +
