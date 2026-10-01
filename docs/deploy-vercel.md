# Deploying Wingmates for free: Vercel + Turso

The app runs on Vercel's free Hobby plan and keeps its data in a free Turso
database. Neither needs a payment card. Vercel's Hobby plan is for personal,
non-commercial use; if a usage limit is exceeded the site is paused, not
billed.

For a paid alternative with faster pages and week-long backups, see
[deploy-render.md](deploy-render.md).

## Before you start

- Google sign-in is set up: see [google-sign-in-setup.md](google-sign-in-setup.md).
- The code is pushed to the `main` branch on GitHub.

## 1. Create the database

1. Sign up at https://turso.tech.
2. Create a database named `wingmates`.
3. Copy its URL (it starts with `libsql://`) and create a token for it.
4. Save both on your own machine and check they work:

       .venv/bin/python tools/save_turso.py
       .venv/bin/python tools/turso_check.py

   The check creates a throwaway user and flight, reads them back and removes
   them. It should end with `OK`.

## 2. Create the Vercel project

1. Sign up at https://vercel.com with your GitHub account.
2. Choose **Add New**, **Project**, and import the `wingmates` repository.
3. Before deploying, open **Environment Variables** and add:

   | Name | Value |
   |---|---|
   | `WINGMATES_AUTH` | `google` |
   | `SECRET_KEY` | a long random string; `python3 -c "import secrets; print(secrets.token_hex(32))"` makes one |
   | `GOOGLE_CLIENT_ID` | `client_id` from `~/.wingmates/google-client.json` |
   | `GOOGLE_CLIENT_SECRET` | `client_secret` from the same file |
   | `TURSO_DATABASE_URL` | the `libsql://` URL |
   | `TURSO_AUTH_TOKEN` | the Turso token |

4. Deploy.

## 3. Tell Google the new address

Vercel shows the project's address, like `https://wingmates.vercel.app`.

1. In the Google Cloud console open **Google Auth Platform**, **Clients**, your
   client.
2. Under **Authorized redirect URIs** add `https://YOUR-ADDRESS/auth/callback`.
3. Save.

## 4. Sign in and invite people

Open the address, press **Continue with Google**, and choose a username.

**Google's test users list is your invite list.** While the Google app's
publishing status is **Testing**, only people on that list can sign in.
Wingmates has no invite system of its own.

## Updating

Every push to `main` deploys automatically. Vercel also builds a preview for
other branches at a different address; previews answer "unknown host", because
the app only answers at its real address.

## Limits and backups

- A CSV import holds at most 5,000 flights.
- Pages are slower than on your own machine: every database query is a network
  request. The first visit after a quiet spell is slower still.
- Turso's free plan keeps one day of point-in-time restore. Each person can
  export their own flights as CSV.
- The database tables are created on first start. A later change to their
  shape will need a migration step that does not exist yet.

## If something is wrong

- **Every page says "unknown host".** Set `WINGMATES_BASE_URL` to the site's
  address, including `https://`, and redeploy.
- **The deployment fails at start.** Open the function logs. The message names
  the missing setting: `WINGMATES_AUTH`, `SECRET_KEY`, the Google client, or
  the Turso pair.
- **Sign-in works but nothing saves.** Run `tools/turso_check.py` locally; it
  reports whether Turso is reachable with the saved token.
- **Google shows `redirect_uri_mismatch`.** The redirect URI in the Google
  console does not exactly match `https://YOUR-ADDRESS/auth/callback`.
