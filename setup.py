from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

from setuptools import find_packages, setup


loader = SourceFileLoader("deckz", "./deckz/__init__.py")
deckz = ModuleType(loader.name)
loader.exec_module(deckz)

setup(
    name="deckz",
    version=deckz.__version__,  # type: ignore
    description="Tool to handle multiple beamer decks.",
    long_description=(Path(__file__).parent / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    author="m09",
    python_requires=">=3.6.0",
    url="https://github.com/m09/deckz",
    packages=find_packages(exclude=["tests"]),
    entry_points={"console_scripts": ["deckz=deckz.__main__:main"]},
    install_requires=["appdirs", "click", "coloredlogs", "Jinja2", "pygit2", "PyYAML"],
    include_package_data=True,
    classifiers=[
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
)
