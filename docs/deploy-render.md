# Deploying Wingmates on Render

This is the paid route. For a free one, see [deploy-vercel.md](deploy-vercel.md).

Wingmates runs as one small web service with a 1 GB disk. Render's free
instances sleep and cannot have a disk, so this uses the smallest paid
instance: about $7 a month, plus $0.25 a month for the disk.

## Before you start

- Google sign-in is set up: see [google-sign-in-setup.md](google-sign-in-setup.md).
- The code is pushed to the `main` branch on GitHub.

## 1. Create the service

1. Sign up at https://render.com and add a payment method.
2. In the dashboard choose **New**, then **Blueprint**.
3. Connect your GitHub account and give Render access to the `wingmates`
   repository.
4. Render reads `render.yaml` and shows one web service, `wingmates`, with a
   disk. Check the instance type is the smallest paid one.
5. It asks for two values. Open `~/.wingmates/google-client.json` and copy:
   - `GOOGLE_CLIENT_ID`: the `client_id` value
   - `GOOGLE_CLIENT_SECRET`: the `client_secret` value
6. Apply. The first build takes a few minutes.

## 2. Tell Google the new address

Render shows the service's address, like `https://wingmates-ab12.onrender.com`.

1. In the Google Cloud console open **Google Auth Platform**, then **Clients**,
   then your client.
2. Under **Authorized redirect URIs** add, with no trailing slash:
   `https://YOUR-ADDRESS/auth/callback`
3. Save. Keep the `http://localhost:8817/auth/callback` entry for local use.

## 3. Sign in and invite people

1. Open the address and press **Continue with Google**.
2. Choose your username.
3. To bring flights across from your own machine, use **Export** there and
   **Import CSV** here.
4. Add each friend's Google address under **Audience**, **Test users** in the
   Google console, then send them the address.

**That test users list is your invite list.** While the Google app's
publishing status is **Testing**, only the people on it can sign in. Wingmates
itself has no invite system: if you switch the Google app to **In
production**, anyone with a Google account who finds the address can create an
account. Leave it in Testing unless that is what you want.

## Updating

Every push to `main` deploys automatically. Because the service has a disk,
Render stops the old version before starting the new one, so the site is
unavailable for a few seconds during a deploy.

## Backups

Render snapshots the disk once a day and keeps each snapshot for at least
seven days. To restore, open the service's **Disks** page and pick a snapshot;
everything written after it is lost. Each person can also export their own
flights as CSV at any time.

## Settings

| Variable | Set by | Purpose |
|---|---|---|
| `WINGMATES_AUTH` | `render.yaml` | `google`. The server refuses to start otherwise. |
| `WINGMATES_DATA_DIR` | `render.yaml` | `/data`, the disk. |
| `SECRET_KEY` | Render, generated once | Signs session cookies. Changing it signs everyone out. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | you, in the dashboard | The Google client. |
| `WINGMATES_BASE_URL` | optional | Set this when you add a custom domain. Otherwise the service's `onrender.com` address is used. |

## A custom domain

Add the domain in the service's **Settings**, set `WINGMATES_BASE_URL` to
`https://your-domain`, and add `https://your-domain/auth/callback` to the
Google client's redirect URIs.

## If something is wrong

- **The deploy never goes live.** Open **Logs**. A line saying a hosted
  Wingmates needs `WINGMATES_AUTH=google` means that variable was removed. A
  line about Google sign-in needing a client means one of the two Google
  values is empty.
- **Google shows `redirect_uri_mismatch`.** The redirect URI in the Google
  console does not exactly match `https://YOUR-ADDRESS/auth/callback`.
- **Google shows `access_denied`.** That person is not in the test users list.
- **Everyone was signed out.** `SECRET_KEY` changed, or you pressed Sign out:
  signing out ends every session of your account, on every device.
