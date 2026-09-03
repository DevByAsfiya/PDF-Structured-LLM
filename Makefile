.PHONY: install ingest run eval test ui clean

install:
	pip install -e .

ingest:
	python -m pdfscraper.cli ingest

run:
	python -m pdfscraper.cli run --stages 02-06 --pages 38-45

run-full:
	python -m pdfscraper.cli run --stages 02-06

eval:
	python -m pdfscraper.cli eval

test:
	pytest -q

ui:
	streamlit run app/Home.py

clean:
	rmdir /s /q __pycache__ .pytest_cache
