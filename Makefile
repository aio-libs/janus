develop:
	python setup.py develop

lint flake: checkrst  pyroma bandit mypy
	flake8 janus tests

test: flake develop
	pytest tests

vtest: flake develop
	pytest -v tests

fmt:
	isort -rc janus tests setup.py
	black janus tests setup.py

cov: flake develop
	pytest --cov=janus --cov=tests --cov-report=term --cov-report=html
	@echo "open file://`pwd`/htmlcov/index.html"

checkrst:
	python setup.py check --restructuredtext

pyroma:
	pyroma -d .

bandit:
	bandit -r ./janus

mypy:
	mypy janus --disallow-untyped-calls --disallow-incomplete-defs --strict
