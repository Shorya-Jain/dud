# Deploy the dud registry

This guide puts the registry on Cloudflare and connects it to GitHub sign-in.
Do the steps in sequence.
Type each command in the Terminal app on your Mac.
A line that starts with `#` is a note, not a command.

Time: approximately 45 minutes.

## Before you start

You need:

- A Cloudflare account. Make one at https://dash.cloudflare.com/sign-up if you do not have one.
- The Workers Paid plan (5 USD each month). The challenge check needs more CPU time than the free plan gives.
- A GitHub account.
- Node.js 22.18 or later. Check with `node --version`.
- A password manager, for three secret values.

## Step 0: Try the registry on your Mac first (optional, 5 minutes)

The dev server runs the real registry code on your Mac. It needs no Cloudflare account.

1. Open a terminal and go to the project: `cd ~/Documents/dud`
2. Start the dev server: `node server/dev.ts`
3. Copy the token that it shows in the line `Token for the account "dev"`.
4. Open a second terminal and go to the project: `cd ~/Documents/dud`
5. Set the registry address: `export DUD_API_URL=http://localhost:8787`
6. Set the token. Replace `<token>` with the token from step 3: `export DUD_TOKEN=<token>`
7. Run a mock full test: `DUD_MOCK=1 PYTHONPATH=src .venv/bin/python -m dud full`
8. Make sure that the last line says "You have registry access until".
9. Run a mock quick test: `DUD_MOCK=1 PYTHONPATH=src .venv/bin/python -m dud quick`
10. Make sure that the output says "earlier readings in the registry: 1".
11. In the first terminal, push Ctrl+C to stop the dev server.

## Step 1: Install the Cloudflare tool (wrangler)

1. Go to the server folder: `cd ~/Documents/dud/server`
2. Install wrangler: `npm install`

   This downloads approximately 120 MB into `server/node_modules`. Git ignores this folder.

3. Make sure that it works: `npx wrangler --version`

## Step 2: Make the GitHub OAuth app

`dud login` uses this app to sign users in with the GitHub device flow.

1. Open https://github.com/settings/developers in your browser.
2. Click **OAuth Apps**.
3. Click **New OAuth App**.
4. Type these values:
   - **Application name:** `dud registry`
   - **Homepage URL:** `https://github.com/Shorya-Jain/dud`
   - **Authorization callback URL:** `https://github.com/Shorya-Jain/dud`

     The device flow does not use the callback URL, but GitHub needs a value.

5. Click **Register application**.
6. On the next page, select **Enable Device Flow**.
7. Click **Update application**.
8. Copy the **Client ID**. It is not a secret.
9. Open `server/wrangler.toml` in a text editor.
10. Replace `REPLACE_WITH_YOUR_GITHUB_CLIENT_ID` with the Client ID.
11. Save the file.
12. On the GitHub app page, click **Generate a new client secret**.
13. Copy the secret into your password manager now. GitHub shows it only one time. You need it in step 7.

## Step 3: Connect wrangler to your Cloudflare account

1. Run: `npx wrangler login`
2. A browser window opens. Click **Allow**.
3. Make sure that wrangler sees your account: `npx wrangler whoami`
4. In the Cloudflare dashboard (https://dash.cloudflare.com), click **Workers & Pages**.
5. Click **Plans**.
6. Select **Workers Paid**.

## Step 4: Make the D1 database

1. Run: `npx wrangler d1 create dud-registry`
2. The output shows a `database_id`, a long value with dashes. Copy it.
3. Open `server/wrangler.toml`.
4. Replace `REPLACE_WITH_YOUR_D1_DATABASE_ID` with the value from item 2.
5. Save the file.
6. Make the tables: `npx wrangler d1 migrations apply dud-registry --remote`
7. Type `y` when wrangler asks.

## Step 5: Make the R2 bucket for raw output

1. In the Cloudflare dashboard, click **R2 Object Storage**.
2. If Cloudflare asks, enable R2. The free tier is sufficient. Cloudflare can ask for a payment card.
3. In the terminal, run: `npx wrangler r2 bucket create dud-raw`
4. Do not enable public access for this bucket. Do not connect a custom domain or an r2.dev address to it. The bucket must stay private.

## Step 6: Deploy the Worker

1. Run: `npx wrangler deploy`
2. The output shows the address of the Worker, for example `https://dud-registry.your-name.workers.dev`. Copy it.
3. Make sure that the Worker answers. Replace the address with yours:

   `curl https://dud-registry.your-name.workers.dev/v1/config`

4. Make sure that the answer contains your GitHub Client ID.

## Step 7: Set the secrets

Do not put these values in any file in the project.

1. Make two random values. Run this command two times, and keep each output in your password manager:

   `openssl rand -hex 32`

   - Name the first value `CARD_ID_PEPPER`.
   - Name the second value `ADMIN_TOKEN`.

2. Set the GitHub secret: `npx wrangler secret put GITHUB_CLIENT_SECRET`
3. Paste the client secret from step 2, then push Enter.
4. Set the pepper: `npx wrangler secret put CARD_ID_PEPPER`
5. Paste the first random value, then push Enter.
6. Set the admin token: `npx wrangler secret put ADMIN_TOKEN`
7. Paste the second random value, then push Enter.

**Warning:** Never change `CARD_ID_PEPPER` after the first submission. The registry stores each card ID as a hash with the pepper. A new pepper breaks the link between old and new readings of each card. Do not lose it.

## Step 8: Point dud at your registry

1. Open `src/dud/registry.py`.
2. Find the line that starts with `DEFAULT_API_URL`.
3. Replace the address on that line with your Worker address from step 6.
4. Save the file.
5. Build a new package: `cd ~/Documents/dud && .venv/bin/pip wheel --no-deps . -w dist`

To test without a change to the file, set `DUD_API_URL` to the Worker address.

## Step 9: Sign in for the first time

1. Go to the project: `cd ~/Documents/dud`
2. Run: `PYTHONPATH=src .venv/bin/python -m dud login`
3. dud shows an address and a code.
4. Open the address on any computer or phone, and type the code.
5. Click **Authorize**.
6. Make sure that dud says "You are signed in as".
7. Run: `PYTHONPATH=src .venv/bin/python -m dud status`
8. Make sure that the output says "You do not have registry access". This is correct until your first accepted full test.

## Step 10: Use the admin tool

1. Set the registry address. Replace the address with yours:

   `export DUD_API_URL=https://dud-registry.your-name.workers.dev`

2. Set the admin token: `export DUD_ADMIN_TOKEN=<the ADMIN_TOKEN value>`
3. Show the open flags: `python3 admin/dud_admin.py flags`
4. Show the flagged submissions: `python3 admin/dud_admin.py submissions`
5. Read `admin/dud_admin.py` for all commands.

## Step 11: Put the website on Cloudflare

The website is the folder `site/`. It is one HTML page with no build step.
`site/_headers` adds security headers to every page.
`site/wrangler.toml` makes it a Worker with static files only. It has no code and no connection to the registry.

1. Go to the project: `cd ~/Documents/dud`
2. Deploy the site: `server/node_modules/.bin/wrangler deploy -c site/wrangler.toml`
3. The output shows the address, for example `https://dud.your-name.workers.dev`. Open it in your browser.
4. Make sure that the card ID tool shows a 64-character card ID.

After a change to `site/index.html`, do item 2 again.

**Warning:** Do not use `wrangler pages` commands in the `server/` folder. wrangler 4.156 sends them to Workers, and they use `server/wrangler.toml`, which is the registry.

The links on the website go to the GitHub repository. Make the repository public before you share the website. Before that, the links show "404" to other people.

## Change a setting

1. Open `server/wrangler.toml`.
2. Change the value in `[vars]`. The defaults and the full list are in `server/src/env.ts`.
3. Run `cd ~/Documents/dud/server && npx wrangler deploy`.

`REQUIRE_LOAD` is `"true"`. The registry rejects a full test that has no load test. dud 0.1.0 has no load test, so do not use it with this registry.

## Change the datasheet values, the challenge limits or the grading rules

1. Edit `specs.yaml` or `grading.yaml`.
2. Run `.venv/bin/python scripts/build_specs.py`.
3. Run the tests: `cd server && npm test`
4. Deploy: `npx wrangler deploy`

## Update the registry code

1. Run all tests:
   - `cd ~/Documents/dud && .venv/bin/python -m pytest -q`
   - `cd server && npm test`
2. Deploy: `npx wrangler deploy`
3. If there is a new file in `server/migrations/`, apply it: `npx wrangler d1 migrations apply dud-registry --remote`

   dud 0.2.0 adds `0002_verdict_reasons.sql`. If you deployed the registry before 0.2.0, apply it.

## See what the registry does

- Live log: `npx wrangler tail`
- Dashboard: **Workers & Pages** > **dud-registry** > **Observability**

## Costs

- Workers Paid: 5 USD each month. It includes 10 million requests and 30 million CPU milliseconds.
- D1 and R2: the free tiers are sufficient for a long time. One submission is approximately 0.1 to 5 MB in R2.
