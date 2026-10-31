# dud

dud checks the health of a rented NVIDIA data center GPU.
dud reads the identity and the history of each GPU on a node.
dud writes a result file and a report.

This is version 0.1.0 (milestone 1).
This version has the quick test only.
It does not give a verdict and it does not send data to the registry.

## Run the quick test

1. Install dud: `pip install dud_gpu-0.1.0-py3-none-any.whl`
2. Run the quick test: `dud quick --provider <name of the provider>`
3. Read the report in `dud-results/<folder>/report.md`.

## Re-render a report

Run `dud report dud-results/<folder>/result.json`.

## Mock mode (no GPU)

Mock mode uses recorded raw output from the `fixtures/` folder.

1. Set `DUD_MOCK=1`.
2. Set `DUD_FIXTURE` to a fixture name, for example `container_ecc_hidden`.
3. Run `dud quick`.

## What leaves the node

In this version, nothing leaves the node.
dud replaces each GPU UUID and serial number with its SHA-256 hash before it writes a file.
dud removes process names and process IDs from the raw output.

## For developers

See `docs/DESIGN.md` for the data model and `docs/GLOSSARY.md` for the terms.

```
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```
