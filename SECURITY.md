# Security policy

This repository is an unofficial fork of
[Instagram/Fixit](https://github.com/Instagram/Fixit). Report the
vulnerabilities of this fork here. For upstream Fixit, follow the policy of
Instagram/Fixit.

## Supported versions

The `main` branch only: this fork has no release yet.

## Reporting a vulnerability

Report it privately, with the private vulnerability reporting of GitHub: on the
Security tab of this repository, choose "Report a vulnerability". Do not open a
public issue for it.

Include what you can: the commit of Fixit, how to reproduce the vulnerability,
and its impact.

This fork has one maintainer. A report gets a reply as soon as possible, with
no fixed deadline.

## Not a vulnerability

Fixit imports the lint rules that a configuration enables, and so runs their
code: linting a repository runs the rules that its configurations name. That is
by design. The [Security](docs/guide/configuration.rst#security) section of the
user guide says which configurations to trust, and how `--no-custom-rules` turns
off the rules that do not come with Fixit.
