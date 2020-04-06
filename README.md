# `deckz`

[![CI Status](https://img.shields.io/github/workflow/status/m09/deckz/CI?label=CI&style=for-the-badge)](https://github.com/m09/deckz/actions?query=workflow%3ACI)
[![CD Status](https://img.shields.io/github/workflow/status/m09/deckz/CD?label=CD&style=for-the-badge)](https://github.com/m09/deckz/actions?query=workflow%3ACD)
[![PyPI Project](https://img.shields.io/pypi/v/deckz?style=for-the-badge)](https://pypi.org/project/deckz/)
[![Docker Hub Image](https://img.shields.io/docker/v/hugomougard/deckz?label=DOCKER&style=for-the-badge)](https://hub.docker.com/r/hugomougard/deckz)

Tool to handle a large number of beamer decks, used by several persons, with shared slides amongst the decks. It is currently not meant to be usable directly by people finding about the package on GitHub. Please open an issue if you want more details or want to discuss this solution.

## Installation

With `pip`:

    pip install deckz

## Directory Structure

`deckz` works with big assumptions on the directory structure of your presentation repository. Among those assumptions:

- your directory should be a git repository
- it should contain a `shared` folder for everything that will be shared by all decks during compilation (images, code snippets, etc)
- it should contain jinja2 LaTeX templates in the `jinja2` directory, with a specific name (`$VERSION.tex.jinja2`) containing a version for reference in configuration, for example: `v1.tex.jinja2`
- your deck folders should be contained in an organization/company folder. This is meant to avoid repeating the company details all over the place
- several configuration should be present to customize the decks efficiently (more on that later)

```
root (git repository)
├── global-config.yml
├── jinja2
│   ├── v1.tex.jinja2
│   └── v2.tex.jinja2
├── shared
│   ├── img
│   │   ├── image1.png
│   │   └── image2.jpg
│   ├── code
│   │   ├── snippet1.py
│   │   └── snippet2.js
│   └── latex
│       ├── module1.tex
│       └── module2.tex
├── company1
│   ├── company-config.yml
│   └── deck1
│       ├── session-config.yml
│       ├── deck-config.yml
│       ├── targets.yml
│       └── module3.tex
└── company2
    ├── company-config.yml
    └── deck2
        ├── session-config.yml
        ├── deck-config.yml
        ├── targets.yml
        └── module4.tex
```

## Configuration

`deckz` uses small configuration files in several places to avoid repetition.

### Configuration merging

The configuration are merged in this order (a value from a configuration on the bottom overrides a value from a configuration on the top):

- `global-config.yml`
- `user-config.yml`
- `company-config.yml`
- `deck-config.yml`
- `session-config.yml`

### Using the configuration values in LaTeX files

The values obtained from the merged configurations can be used in LaTeX after a conversion from snake case to camel case: if the configuration contains the key `trainer_email`, it will be defined as the `\TrainerEmail` command in LaTeX.

### Details about specific configurations

#### Global configuration

The global configuration contains the default values that don't fit at a more specific level.

Example:

```
presentation_size: 10pt
```

#### User configuration

The user configuration contains the values that change when the speaker changes. It is located in the XDG compliant config location. It is `$HOME/.config/deckz/user-config.yml` on GNU/Linux for example.

Example:

```
trainer_activity: Data Scientist
trainer_email: john@doe.me
trainer_name: John Doe
trainer_specialization: NLP, NLU
trainer_training: MSc at UCL
```

#### Company configuration

The company configuration contains everything required to brand the presentations according to the represented company.

Example:

```
company_logo: logo_company
company_logo_height: 1cm
company_name: Company
company_website: https://www.company.com
```

#### Deck configuration

The deck configuration contains the title and acronym of the talk.

Example:

```
deck_acronym: COV19
deck_title: Machine Learning and COVID-19
```

#### Session configuration

The session configuration contains everything that will change from one session of a specific talk to another one.

Example:

```
session_end: 30/04/2020
session_start: 27/04/2020
```

## Usage

See the `-h` flag of the `deckz` command line tool.
