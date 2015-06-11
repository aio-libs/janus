develop:
	python setup.py develop

flake:
	flake8 janus tests

test: flake develop
	py.test tests

vtest: flake develop
	py.test -v tests

yapf:
	yapf -ri janus tests setup.py

cov: flake develop
	py.test --cov=janus --cov=tests --cov-report=term --cov-report=html
	@echo "open file://`pwd`/htmlcov/index.html"
