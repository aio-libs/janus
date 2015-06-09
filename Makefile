develop:
	python setup.py develop

flake:
	flake8 mixedqueue tests

test:
	py.test tests
