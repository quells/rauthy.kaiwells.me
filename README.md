# Rauthy on Fly.io

[Rauthy](https://github.com/sebadob/rauthy) (OIDC provider), single node, deployed to the Fly app
`corolla-retreat` and served at <https://rauthy.kaiwells.me>.

- `fly.toml`: Fly app config (one Machine in `lax`, `rauthy_data` volume at `/app/data`).
- `config.toml`: Rauthy config, **non-secret values only**. Shipped into the Machine with `[[files]]`.
- `tools/uitype.py`: types a secret from an env var into a named browser field (see
  [Browser testing](#browser-testing-as-the-agent)).

This README also covers how to let a coding agent (e.g. Claude Code) deploy and test this app
**without handing it access to the whole Fly org or to real accounts**.

---

## Agent access: the principles

1. **Scope every credential to the smallest thing that works.** Use an app-scoped Fly deploy token,
   not your login or an org token. Give the agent a non-admin test user, not your admin account.
2. **Credentials go in files or env vars, never in the chat.** Anything pasted into the chat ends
   up in the session transcript. The agent should load a secret only inside a shell command
   (`. file; ... "$VAR"`) and never print it.
3. **Make it expire and make it revocable.** Give tokens short expiries and names, and revoke them
   when the work is done.
4. **The human keeps the irreversible steps.** You create the app, the DNS records and the org.
   You hold the backups of the encryption keys.

---

## One-time setup (human)

### 1. (Recommended) Use a separate org

A deploy token is limited to one app, **but every app in a Fly org shares the private 6PN
network** (`*.internal`). Code the agent deploys can reach your other apps' internal services.
Only a separate org isolates it, and it also keeps any cost surprises separate:

```sh
fly orgs create agent-sandbox
```

> `corolla-retreat` currently lives in the `personal` org. Move it if `personal` holds anything
> sensitive.

### 2. Create the app yourself

```sh
fly apps create corolla-retreat --org <org>
```

A deploy token can't create apps, which is good: the agent can't create new apps that bill to
your org.

### 3. Create an app-scoped deploy token with an expiry

```sh
fly tokens create deploy -a corolla-retreat -x 168h -n "claude-code" > ~/.fly-claude-token
chmod 600 ~/.fly-claude-token
```

With this token the agent **can** deploy, manage this app's Machines, volumes and certs, set and
read its secrets (SSH into the Machine shows the env), and read its logs. It **cannot** see or
touch other apps (`fly apps list` returns `unauthorized`), billing, members or org settings.

Hand it to the agent through the environment, not the chat:

```sh
export FLY_API_TOKEN="$(cat ~/.fly-claude-token)"
claude
```

Revoke it when you're done:

```sh
fly tokens list -a corolla-retreat
fly tokens revoke <token-id>
```

### 4. DNS and TLS

Rauthy must be public over HTTPS: OIDC clients need a stable `https://` issuer, and WebAuthn
needs a secure origin. Fly terminates TLS, and Rauthy runs plain HTTP behind it
(`scheme = "http"`, `proxy_mode = true`).

```sh
fly certs add rauthy.kaiwells.me -a corolla-retreat   # the deploy token can do this
fly ips list -a corolla-retreat
```

Then, at your DNS provider, add `A` and `AAAA` records for `rauthy.kaiwells.me` pointing at those
IPs. Fly may report the cert as "Issued" before DNS resolves, so test the real hostname.

> **Choose the hostname before anyone registers a passkey.** `pub_url`, `webauthn.rp_id` and
> `rp_origin` are effectively permanent. Changing them breaks every registered passkey and every
> OIDC client's issuer.

### 5. Secrets

Generate them once. Stage them on Fly and **keep a backup outside Fly**:

```sh
umask 077
KID=$(date +%Y%m%d)k1
cat > ~/.config/corolla-retreat-rauthy-secrets.env <<EOF
HQL_SECRET_RAFT=$(openssl rand -hex 32)
HQL_SECRET_API=$(openssl rand -hex 32)
ENC_KEYS="$KID/$(openssl rand -base64 32)"
ENC_KEY_ACTIVE=$KID
BOOTSTRAP_ADMIN_EMAIL=you@example.com
EVENT_EMAIL=you@example.com
EOF
fly secrets import --stage -a corolla-retreat < ~/.config/corolla-retreat-rauthy-secrets.env
```

**If you lose `ENC_KEYS`, the encrypted data in the database can't be read.** Put a copy in your
password manager.

Later: `SMTP_PASSWORD` plus the `[email]` block in `config.toml`. Until then Rauthy can't send
any email (password resets, event alerts).

### 6. Volume and first deploy

```sh
fly volumes create rauthy_data -r lax -s 1 -y -a corolla-retreat
fly deploy --ha=false -a corolla-retreat
```

### 7. Admin account

On first boot Rauthy prints a random admin password to the logs. **Read it yourself:**

```sh
fly logs -a corolla-retreat | grep -i password
```

Log in as `BOOTSTRAP_ADMIN_EMAIL`, change the password, and add MFA. Rauthy's MFA is
**passkeys only (no TOTP/QR codes)**. 1Password works as a passkey store. Register it on
`https://rauthy.kaiwells.me` (the `rp_id`), not on `*.fly.dev`, and register a second passkey as
a backup.

The agent should never see this password. When it reads logs, it should filter it out
(`grep -vi password`).

---

## Giving the agent a test user

Create a **non-admin, password-only** user in the admin UI. The agent can't use passkeys, and it
doesn't need admin rights to test logins. Put the credentials in a file only you can read:

```sh
umask 077
cat > ~/.config/rauthy.kaiwells.me.env <<'EOF'
RAUTHY_TEST_USER=...
RAUTHY_TEST_PASSWORD=...
EOF
```

Then tell the agent the **path**, not the values. If the test is "can an app authenticate", a
dedicated OIDC client is often a better fit than a user. Its secret goes in a file the same way.

---

## Browser testing as the agent

This works on GNOME/Wayland with the local helpers `~/.local/bin/shot` (screenshot through the
desktop portal) and `~/.local/bin/uiclick` (focus a control by its accessible name and press
Enter). Neither one can type, so `tools/uitype.py` adds typing.

1. **Turn on accessibility, then (re)start Firefox.** Firefox only shows up in the AT-SPI tree if
   this is on when it launches:
   ```sh
   gsettings set org.gnome.desktop.interface toolkit-accessibility true
   # undo: gsettings set org.gnome.desktop.interface toolkit-accessibility false
   ```
2. **Type secrets only into a field confirmed to have focus.** `uitype.py` looks up the field by
   name and refuses to type unless that field reports FOCUSED, so a password can't land in another
   window. It reads the value from an env var and never prints it:
   ```sh
   set -a; . ~/.config/rauthy.kaiwells.me.env; set +a
   python3 tools/uitype.py --app Firefox "E-Mail" RAUTHY_TEST_USER
   ~/.local/bin/uiclick --app Firefox Login
   python3 tools/uitype.py --app Firefox --enter "Password" RAUTHY_TEST_PASSWORD
   ```
3. **Rauthy gotchas:**
   - The **Passkey** button has no accessible name. Activating "Login" by name after entering the
     email can land on it and start a WebAuthn prompt. If that happens, cancel and check focus.
     Submitting with `--enter` from inside the password field avoids the problem.
   - Dismiss Firefox's "Save password?" prompt; don't save test credentials in the browser.
4. Remember that screenshots capture the **whole desktop**, not just the browser.

---

## Upgrading Rauthy

```sh
# 1. Validate the config against the new image (use throwaway secrets, not the real ones)
K=$(openssl rand -base64 32)
podman run --rm -v "$PWD/config.toml:/app/config.toml:ro,Z" \
  -e ENC_KEYS="d1/$K" -e ENC_KEY_ACTIVE=d1 \
  -e HQL_SECRET_RAFT=$(openssl rand -hex 24) -e HQL_SECRET_API=$(openssl rand -hex 24) \
  ghcr.io/sebadob/rauthy:<new> validate-config -p config.toml

# 2. Snapshot the volume and wait until it shows "created"
fly volumes snapshots create <vol-id> -a corolla-retreat
fly volumes snapshots list <vol-id> -a corolla-retreat

# 3. Bump the tag in fly.toml, deploy and verify
fly deploy --ha=false -a corolla-retreat
curl -fsS https://rauthy.kaiwells.me/auth/v1/health
fly status -a corolla-retreat | grep -i image
```

Since v0.36, Rauthy panics on unknown config keys, so always run step 1.

---

## Known pitfalls

- **Don't shrink `cluster.wal_size`.** At 256 KB, first boot panics with
  ``data` length must not exceed `wal_size``, because the `fido_mds` migration writes a single
  entry of about 516 KB. Leave it at the default.
- **`trusted_proxies`** must cover Fly's proxy ranges (`172.16.0.0/12`, `fdaa::/16`). If every
  request returns 403, check `fly logs` for the real peer IP.
- **The app gets scanned within minutes of going public.** Rauthy blacklists the scanners. Change
  the bootstrap admin password right away.
- **The agent can read the app's secrets** (via `fly ssh console`). Use test or sandbox
  credentials for upstream services such as SMTP or upstream OAuth providers.
