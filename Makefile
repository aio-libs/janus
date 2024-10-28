develop:
	python setup.py develop

lint flake: checkrst  pyroma bandit mypy
	# F401 is upset about typing.Deque, List, and Set which are used in hinting
	flake8 --ignore=F401 janus tests

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
	mypy janus --strict
