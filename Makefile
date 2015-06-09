develop:
	python setup.py develop

flake:
	flake8 mixedqueue tests

test: flake develop
	py.test tests

vtest: flake develop
	py.test -v tests

yapf:
	yapf -ri mixedqueue tests setup.py

cov: flake develop
	py.test --cov=mixedqueue --cov=tests --cov-report=term --cov-report=html
	@echo "open file://`pwd`/htmlcov/index.html"
