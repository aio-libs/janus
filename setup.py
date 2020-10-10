import codecs
import os
import re
import sys

from setuptools import find_packages, setup
from setuptools.command.test import test as TestCommand


class PyTest(TestCommand):
    user_options = [("pytest-args=", "a", "Arguments to pass to py.test")]

    def initialize_options(self):
        TestCommand.initialize_options(self)
        self.pytest_args = []

    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        # import here, cause outside the eggs aren't loaded
        import pytest

        errno = pytest.main(self.pytest_args)
        sys.exit(errno)


with codecs.open(
    os.path.join(os.path.abspath(os.path.dirname(__file__)), "janus", "__init__.py"),
    "r",
    "latin1",
) as fp:
    try:
        version = re.findall(r'^__version__ = "([^"]+)"$', fp.read(), re.M)[0]
    except IndexError:
        raise RuntimeError("Unable to determine version.")


def read(f):
    return open(os.path.join(os.path.dirname(__file__), f)).read().strip()


install_requires = []

tests_require = install_requires + [
    "pytest>=5.4",
    "pytest-asyncio>=0.10.0",
]
extras_require = {}


setup(
    name="janus",
    version=version,
    description=(
        "Mixed sync-async queue to interoperate between "
        "asyncio tasks and classic threads"
    ),
    long_description="\n\n".join((read("README.rst"), read("CHANGES.rst"))),
    classifiers=[
        "License :: OSI Approved :: Apache Software License",
        "Intended Audience :: Developers",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Topic :: Software Development :: Libraries",
        "Framework :: AsyncIO",
    ],
    author="Andrew Svetlov",
    author_email="andrew.svetlov@gmail.com",
    url="https://github.com/aio-libs/janus/",
    license="Apache 2",
    packages=find_packages(),
    python_requires=">=3.6",
    install_requires=install_requires,
    tests_require=tests_require,
    cmdclass={"test": PyTest},
    include_package_data=True,
    zip_safe=True,
    keywords=["janus", "queue", "asyncio"],
    extras_require=extras_require,
)
