develop:
	python setup.py develop

flake:
	flake8 mixedqueue tests

test: flake develop
	py.test tests

vtest: flake develop
	py.test -v tests
