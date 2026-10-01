# Setting up Google sign-in

Wingmates signs people in with Google. This takes about ten minutes, is free,
and needs no billing account.

## 1. Create a project

1. Go to https://console.cloud.google.com and sign in.
2. Open the project picker, choose **New Project**, name it `Wingmates`.
3. Make sure that project is selected.

## 2. Set up the consent screen

1. Open **Google Auth Platform** and press **Get started**.
2. App name `Wingmates`, your email for support and contact, audience
   **External**.

## 3. Add test users

A new app is in **Testing** mode: only listed people can sign in.

1. Open **Audience**.
2. Under **Test users**, add your own Google address and each friend's.

An app that uses only the basic sign-in scopes does not have to be verified
by Google, so it can be published later without a review.

## 4. Create the client

1. Open **Clients**, press **Create Client**, type **Web application**.
2. Under **Authorized redirect URIs** add, with no trailing slash:
   `http://localhost:8817/auth/callback`
3. Press **Create**.

When the app is deployed, add its address here too: see
[deploy-render.md](deploy-render.md).

## 5. Save the secret

Google shows the client secret once. Press **Download JSON** and move the file
into the data folder:

    mv ~/Downloads/client_secret_*.json ~/.wingmates/google-client.json
    chmod 600 ~/.wingmates/google-client.json

That folder is outside the repository, so the secret cannot be committed.
On a server, set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` instead.

## 6. Start with sign-in on

    WINGMATES_AUTH=google .venv/bin/python run.py

Open `http://localhost:8817`, not `127.0.0.1`: the address must match the
redirect address registered above.

## Moving your existing flights

Flights logged before sign-in belong to the local user `@you`, which is not a
Google account and is not merged with one. To bring them across: start without
`WINGMATES_AUTH`, press **Export** in My flights, then start with sign-in,
sign in, and use **Import CSV**.
