# dud

dud checks the health of a rented NVIDIA data center GPU.
It reads the identity and the history of each GPU on a node, and writes a result file and a report.
A full test also goes into a shared registry, card by card, like a vehicle history report for GPUs.

This is version 0.1.0.
It has the quick test, login, the registry challenge and the registry.
The DCGM test, the performance tests, the load test and the verdict come in a later version.

## Commands

| Command | What it does |
|---|---|
| `dud quick` | Reads identity and history (approximately 1 minute). If you have registry access, it also shows earlier readings of each GPU. |
| `dud full` | Does the full test, does the registry challenge, and sends the result to the registry. An accepted full test gives 30 days of registry access. |
| `dud login` | Signs you in with GitHub. Use a browser on any computer or phone. |
| `dud status` | Shows your account, your access and your lookups today. |
| `dud logout` | Deletes your token from this computer. |
| `dud report <file>` | Shows the report for a saved result file. |

Flags: `--provider <name>`, `--gpus 0,1`, `--out-dir <folder>`.
`dud full` also has `--no-submit`, `--skip-dcgm` and `--load-minutes N`.
`dud quick` also has `--offline`.

## Run a test

1. Install dud: `pip install dud_gpu-0.1.0-py3-none-any.whl`
2. Sign in: `dud login`
3. Run the full test: `dud full --provider <name of the provider>`
4. Read the report in `dud-results/<folder>/report.md`.

The full test needs PyTorch with CUDA.
If PyTorch is not installed, dud asks before it installs it.

## The registry

- Anyone can run dud.
- Only accounts with an accepted full test in the last 30 days can read the registry.
- Each account can do 100 lookups each day.
- A lookup needs the card ID, which is the SHA-256 hash of the GPU UUID. There is no list of cards.

`THREATS.md` tells how the registry stops fraud, and what it cannot stop.
`docs/DEPLOY.md` tells how to put the registry on Cloudflare.
`docs/API.md` lists the registry requests.

## What leaves the node

- dud replaces each GPU UUID and serial number with its SHA-256 hash before it writes or sends a file.
- dud removes process names and process IDs from the raw output.
- `dud quick` sends only card IDs (to look up history). `dud full` sends the result file.

## Mock mode (no GPU)

Mock mode uses recorded raw output from the `fixtures/` folder.

1. Set `DUD_MOCK=1`.
2. Set `DUD_FIXTURE` to a fixture name, for example `container_ecc_hidden`.
3. Run `dud quick` or `dud full`.

The registry does not accept mock results. The local dev server does (see below).

## For developers

See `docs/DESIGN.md` for the data model and the challenge, and `docs/GLOSSARY.md` for the terms.

```
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]' pyyaml
.venv/bin/python -m pytest          # CLI tests (an end-to-end test starts the dev server)
cd server && npm test               # registry tests (Node 22.18 or later, no install needed)
node server/dev.ts                  # local registry for tests by hand
```

After a change to `specs.yaml`, run `.venv/bin/python scripts/build_specs.py`.
After a change to the fixtures or the schema, run `.venv/bin/python scripts/make_server_fixtures.py`.
