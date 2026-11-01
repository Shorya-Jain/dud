# dud

dud checks the health of a rented NVIDIA data center GPU.
It reads the identity and the history of each GPU on a node, and writes a result file and a report.
A full test also goes into a shared registry, card by card, like a vehicle history report for GPUs.

This is version 0.2.0.
It has the quick test, the full test with DCGM, performance tests and a load test, verdicts, login and the registry.

## Status

- All tests pass in mock mode and against the local dev registry.
- dud did a full test on a real GPU: an A100 SXM4 40GB on Vast.ai, with DCGM. The verdict was KEEP. That run is now the fixture `a100_sxm4_40gb_real`.
- The registry challenge has not run on a real GPU yet. Its time limits are not final.
- The registry is not on Cloudflare yet. Until it is, use `--no-submit` with `dud full`, and `--offline` with `dud quick`.
- dud is not on PyPI yet. Build the wheel from this repository (see "Run a test").

**Skip the test when someone already did it.**
`dud quick` takes approximately 1 minute.
If another renter did a full test of the GPU recently and the verdict was KEEP, start your work.
If the registry has a KILL verdict for the GPU, dud tells you.

## Website

The website is one page in `site/index.html`. It has no build step.
It explains the value of dud: skip the GPU test when someone already did it.
It shows the KEEP and KILL outcomes, the steps, an example card record, and a tool that calculates a card ID in the browser.

- To see it on your computer, open `site/index.html` in a browser.
- To put it on Cloudflare Pages, do `docs/DEPLOY.md`, step 11.
- The website is not online yet. Make the repository public before you put it online, because the links on the page go to GitHub.

## Commands

| Command | What it does |
|---|---|
| `dud quick` | Reads identity and history (approximately 1 minute), and gives a verdict for each GPU. If you have registry access, it uses the earlier full tests of each GPU. |
| `dud full` | Reads identity and history, runs the DCGM diagnostic, does the registry challenge, runs the performance tests and a load test, gives a verdict, and sends the result to the registry (approximately 30 to 60 minutes). An accepted full test gives 30 days of registry access. |
| `dud login` | Signs you in with GitHub. Use a browser on any computer or phone. |
| `dud status` | Shows your account, your access and your lookups today. |
| `dud logout` | Deletes your token from this computer. |
| `dud report <file>` | Shows the report for a saved result file. |

Flags: `--provider <name>`, `--gpus 0,1`, `--out-dir <folder>`.
`dud full` also has `--no-submit`, `--skip-dcgm`, `--install-dcgm` and `--load-minutes N`.
`dud quick` also has `--offline`.

## Run a test

1. On your computer, make the wheel file: `python3 -m pip wheel --no-deps -w dist .`
2. Copy `dist/dud_gpu-0.2.0-py3-none-any.whl` to the node.
3. On the node, install dud: `pip install dud_gpu-0.2.0-py3-none-any.whl`
4. Sign in: `dud login`
5. Run the full test: `dud full --provider <name of the provider>`
6. Read the report in `dud-results/<folder>/report.md`.

To replace an earlier copy of the same version, add `--force-reinstall --no-deps` to the install command in step 3.

The full test needs PyTorch with CUDA.
If PyTorch is not installed, dud asks before it installs it.

The full test uses the DCGM diagnostic.
If DCGM is not installed, dud asks before it installs it (Ubuntu or Debian, as root or with sudo).
To install DCGM without a question, use `--install-dcgm`.
If dud cannot install DCGM, the full test continues without the DCGM diagnostic.

## Verdicts

Each GPU gets one verdict:

| Verdict | Meaning |
|---|---|
| KEEP | All checks passed. |
| KILL | A check failed, for example uncorrectable ECC errors since the last reset, a pending or failed row remap, low bank availability, a DCGM failure, low sustained performance or constant throttling. |
| UNKNOWN | dud cannot read a key value, for example because the provider blocks ECC data. |

The rules and their limits are in `grading.yaml`. The report explains each verdict.
The registry calculates its own verdict with the same rules. It does not use the verdict that the client sends.

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

After a change to `specs.yaml` or `grading.yaml`, run `.venv/bin/python scripts/build_specs.py`.
After a change to the fixtures or the schema, run `.venv/bin/python scripts/make_server_fixtures.py`.
