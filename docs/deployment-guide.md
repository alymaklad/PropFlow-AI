# Deployment guide: free public demo (Oracle Cloud or AWS free plan)

Step-by-step instructions for putting the PropFlow demo online for reviewers (a company you are
applying to). Why this setup was chosen, and what to consider, is in
`docs/deployment-plan.md`. Oracle's console changes from time to time; if a menu name differs,
look for the closest equivalent.

What reviewers will get:

| Address | What | Access |
|---|---|---|
| `https://<name>.duckdns.org` | Buyer site | Public |
| `https://<name>.duckdns.org/staff` | Staff dashboard | Staff token you share |
| `https://<name>.duckdns.org/mail/` | Every email the system sent (captured; optionally also delivered, section 8b) | User `reviewer` + a password you share |
| `https://odoo.<name>.duckdns.org` | Odoo CRM: leads, PropFlow tab, notes, activities | User `reviewer` + `ODOO_REVIEWER_PASSWORD` (read-only) |

DuckDNS answers for sub-names automatically, so `odoo.<name>.duckdns.org` needs no setup. Every
deploy refreshes the read-only reviewer login and replaces Odoo's default admin password if it
is still `admin` (`scripts/odoo-accounts.sh`, passwords in `/opt/propflow/.env`). n8n stays
private (you reach it over SSH); show it with screenshots or a short video.

## AWS free plan (instead of sections 1 to 3)

AWS's free plan gives new accounts credits (about USD 100 at sign-up, up to 100 more for
getting-started tasks) for up to six months; you are never charged on the free plan, and at
the end you upgrade or the account is closed. Check your balance and end date under Billing and
Cost Management > Credits. That is enough for an application period, not for a permanent demo.

### A. Secure the account (10 minutes)

1. Account menu (top right) > **Security credentials** > **Assign MFA device** for the root
   user.
2. **Billing and Cost Management > Budgets > Create budget**: use the **Zero spend budget**
   template, and add a monthly cost budget (for example USD 25) to watch how fast credits are
   used.
3. Optional but good practice: create an admin user in IAM Identity Center and stop using the
   root user day to day.

### B. Launch the server (10 minutes)

1. Region (top right): **Europe (Frankfurt) eu-central-1** (no opt-in needed, close to Cairo).
2. **EC2 > Instances > Launch instances**, name `propflow-demo`.
3. **AMI**: Ubuntu Server 24.04 LTS, architecture **64-bit (Arm)**.
4. **Instance type**: **t4g.small** (2 vCPU, 2 GB). It must show "Free tier eligible"; if it
   does not in your account, pick the eligible type with at least 2 GB (for example t3.small,
   then choose the 64-bit (x86) Ubuntu image instead). 1 GB types are too small.
5. **Key pair**: Create new key pair, name `propflow-aws`, type **ED25519**, format **.pem**.
   Save it as `~/.ssh/propflow-aws.pem` and run `chmod 400 ~/.ssh/propflow-aws.pem`.
6. **Network settings**: allow SSH from **Anywhere** (GitHub Actions deploys over SSH from
   changing addresses; the server accepts keys only and runs fail2ban); tick **Allow HTTPS
   traffic from the internet** and **Allow HTTP traffic from the internet** (Caddy redirects
   HTTP to HTTPS and renews certificates over it).
7. **Storage**: **30 GiB gp3**.
8. **Launch instance**.
9. **EC2 > Elastic IPs > Allocate Elastic IP address**, then **Actions > Associate** it with
   `propflow-demo`. This keeps the address fixed (AWS bills public IPv4 hourly, from the
   credits, about USD 4 a month).
10. Test: `ssh -i ~/.ssh/propflow-aws.pem ubuntu@<Elastic IP>`.

On a 2 GB machine the stack idles at about 1 GB; the bootstrap script adds 4 GB of swap for
image builds and spikes. Then continue with section 4 (DuckDNS) using the Elastic IP, and in the
later sections use `~/.ssh/propflow-aws.pem` wherever `~/.ssh/propflow_oracle` appears. The
server bootstrap's firewall step is harmless on AWS (the security group does the filtering).

## 1. Oracle Cloud account (about 20 minutes)

1. Go to <https://www.oracle.com/cloud/free/> and choose **Start for free**.
2. Enter your country, name and email; confirm the email.
3. Set a password and choose your **home region**. This cannot be changed later and Always Free
   machines can only be created there. Pick the closest region to you and your reviewers, for
   example UAE East (Dubai), Saudi Arabia West (Jeddah) or Germany Central (Frankfurt). Popular
   regions sometimes run out of free ARM capacity; if creating the machine fails later, that is
   the usual reason.
4. Enter your address and verify your phone number.
5. Add a payment card for **identity verification**. Oracle places a small temporary
   authorisation that is released; Always Free resources are not charged. Prepaid and virtual
   cards are often refused.
6. Wait for the "account is ready" email (usually minutes, sometimes longer), then sign in to the
   Cloud Console.
7. Turn on multi-factor authentication (your profile > Security).
8. Create a **budget alert** so any charge is noticed immediately: Billing & Cost Management >
   Budgets > Create budget, amount 1 (USD), alert when actual spend exceeds 1%.

## 2. SSH key (on your computer)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/propflow_oracle -C propflow-oracle
```

This creates `~/.ssh/propflow_oracle` (private, never share) and `~/.ssh/propflow_oracle.pub`.

## 3. The virtual machine (about 10 minutes)

1. Menu > **Compute > Instances > Create instance**. Name: `propflow-demo`.
2. **Image**: Change image > Canonical Ubuntu > **24.04** (the ARM/aarch64 build is selected
   automatically for Ampere shapes).
3. **Shape**: Change shape > Ampere > **VM.Standard.A1.Flex**, **2 OCPUs and 12 GB** memory.
   Check that it is labelled "Always Free-eligible".
4. **Networking**: create a new virtual cloud network and public subnet; keep **Assign a public
   IPv4 address** on.
5. **SSH keys**: upload `~/.ssh/propflow_oracle.pub`.
6. **Boot volume**: set a custom size of **100 GB** (the free allowance is 200 GB in total).
7. **Create**. "Out of capacity" means no free ARM machines are available right now: try
   another availability domain, try 1 OCPU / 6 GB, or try again later.
8. Make the public IP permanent: open the instance > Attached VNICs > the VNIC > IPv4 addresses
   > edit > **Reserved public IP** (create one). Note the address.
9. Open the web ports: Networking > Virtual cloud networks > your network > the public subnet >
   its security list > **Add ingress rules**: source `0.0.0.0/0`, TCP, destination port `80`;
   again for `443`. Port 22 is already open; you may restrict it to your own IP.
10. Test: `ssh -i ~/.ssh/propflow_oracle ubuntu@<public IP>` and accept the host fingerprint.

Oracle may reclaim Always Free machines that look idle for a week (low CPU, network and memory
use). While your application is under review, keep UptimeRobot alerts on (section 8) so you
notice; upgrading the account to pay-as-you-go stops reclamation (Always Free resources stay
free) but then the budget alert is essential.

## 4. Free address (DuckDNS, 2 minutes)

1. Sign in at <https://www.duckdns.org> (GitHub or Google).
2. Add a sub domain, for example `propflow-demo`, and set **current ip** to the VM's reserved
   public IP.
3. Check: `dig +short propflow-demo.duckdns.org` returns that IP.

## 5. GitHub repository

A **public** repository lets the company read the code; the history was scanned with gitleaks
and contains only synthetic data. Note that commit author emails are public in a public
repository.

On your computer, in the project folder:

```bash
git switch main
git merge --ff-only phase-4
git remote add origin git@github.com:<your-user>/propflow-ai.git
git push -u origin main
```

(Create the empty repository on github.com first, without a README.)

## 6. Server setup (once, about 10 minutes)

```bash
ssh -i ~/.ssh/propflow_oracle ubuntu@<public IP>
curl -fsSL https://raw.githubusercontent.com/<your-user>/propflow-ai/main/deploy/server-bootstrap.sh -o bootstrap.sh
less bootstrap.sh        # read what it will do
sudo bash bootstrap.sh https://github.com/<your-user>/propflow-ai.git
```

It installs Docker, opens ports 80/443 in the server firewall (Oracle's Ubuntu image blocks
them by default), adds swap, disables SSH passwords, creates a `deploy` user, clones the
repository into `/opt/propflow`, and schedules a nightly backup and the daily refresh that keeps
the demo listings "recently checked".

Then create the configuration (asks for the DuckDNS name, your Groq key and a password for the
mail viewer, and generates every other secret):

```bash
sudo -iu deploy
cd /opt/propflow && deploy/make-env.sh
exit
```

Use a **separate Groq key** for the demo (create one at console.groq.com), not the one used
during development.

## 7. GitHub Actions deploy

1. On your computer, create a key used only by GitHub Actions:

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/propflow_deploy -N "" -C github-actions-deploy
   cat ~/.ssh/propflow_deploy.pub | ssh -i ~/.ssh/propflow_oracle ubuntu@<public IP> \
     "sudo tee -a /home/deploy/.ssh/authorized_keys >/dev/null"
   ssh-keyscan -t ed25519 <public IP>
   ```

   The last command prints the server's host key; check it matches the fingerprint you accepted
   in step 3.10.
2. On GitHub: repository **Settings > Environments > New environment** named `production`
   (optionally add yourself as a required reviewer so every deploy waits for your approval).
3. In that environment add **secrets**:
   - `DEPLOY_HOST`: the public IP
   - `DEPLOY_SSH_KEY`: the full contents of `~/.ssh/propflow_deploy` (the private key)
   - `DEPLOY_KNOWN_HOSTS`: the line printed by `ssh-keyscan`
4. Add an environment **variable** `PUBLIC_HOST`: your DuckDNS name, e.g.
   `propflow-demo.duckdns.org`.
5. Deploy: **Actions > Deploy > Run workflow** (branch `main`), or tag a release:

   ```bash
   git tag v1.0.0 && git push origin v1.0.0
   ```

   The workflow runs every test, then deploys over SSH and checks the public site. The first
   deploy takes 10 to 20 minutes (image builds, Odoo initialisation, demo team, catalog,
   workflows); later deploys a few minutes.

## 8. After the first deploy

1. Open Odoo and n8n through an SSH tunnel:

   ```bash
   ssh -i ~/.ssh/propflow_oracle -L 8069:localhost:8069 -L 5678:localhost:5678 ubuntu@<public IP>
   ```

   - <http://localhost:8069> (or `https://odoo.<name>.duckdns.org`): log in as `admin` with
     `ODOO_ADMIN_PASSWORD` from `/opt/propflow/.env` (the deploy replaced the default), then
     set your own password.
   - <http://localhost:5678>: create the n8n owner account.
2. Send yourself through the demo: an inquiry on the buyer site, the captured emails at
   `/mail/`, the staff dashboard at `/staff` (token: `STAFF_TOKEN` in `/opt/propflow/.env`).
3. Test from a phone on mobile data, so you see what an outside reviewer sees.
4. Free monitoring: an UptimeRobot monitor on `https://<name>.duckdns.org`, and optionally a
   Healthchecks.io check whose ping URL you put in `.env` as `HEALTHCHECK_URL` (the nightly
   backup pings it).
5. Copy a backup off the server once to know it works:
   `scp -i ~/.ssh/propflow_oracle -r ubuntu@<public IP>:/opt/propflow-backups ./propflow-backups`.

## 8b. Optional: send real emails to visitors

By default every email is only captured in the mail viewer. To let visitors receive the reply
to their inquiry:

1. Create a Gmail account for the demo (for example `propflow.demo@gmail.com`), turn on
   **2-Step Verification**, then create an **App Password** at
   <https://myaccount.google.com/apppasswords>.
2. On the server:

   ```bash
   sudo -iu deploy
   cd /opt/propflow && deploy/enable-email.sh     # asks for the address and the App Password
   ```

   The script checks the login with Gmail before saving it in `.env`.

What changes: Mailpit still keeps every email for `/mail/` and relays it through Gmail, except
to the fictional staff and test domains (`example.com`, `.test`); manual "release" from the
viewer is disabled. Customer emails end with a demo notice instead of the STOP line (replies
go to the Gmail inbox and are not processed), and no reminders are sent. The buyer site says
that emails really arrive. Gmail allows about 500 emails a day; the demo caps public inquiries
at `PUBLIC_DAILY_LIMIT` (100) a day and 3 emails per address. Undo with
`deploy/enable-email.sh --disable`.

## 9. What to send the company

- The buyer site address, the staff dashboard address with the staff token, and the mail viewer
  address with the `reviewer` password.
- The GitHub repository and `docs/demo.md` (a 10-minute walkthrough), plus screenshots or a
  short video of Odoo and n8n.
- One sentence of context: all homes, people and data are fictional; emails to staff are
  captured, not delivered; the AI runs on a free tier, so under heavy use some inquiries are handed to a
  salesperson instead of being qualified automatically (by design).

## 10. Day-to-day

| Task | How |
|---|---|
| Deploy a change | Push to `main`, then run the Deploy workflow (or push a `v*` tag) |
| Check health | `https://<name>.duckdns.org`, UptimeRobot, or `ssh ... 'cd /opt/propflow && docker compose ps'` |
| Logs | `ssh` then `cd /opt/propflow && docker compose logs --tail 100 ai-service` |
| Rotate a secret | Edit `/opt/propflow/.env` as `deploy`, then run the Deploy workflow; see `docs/security-and-operations.md` |
| Restore a backup | `docs/security-and-operations.md`, "Backups and restore" |
| Take it offline after the application | Stop the instance in the Oracle console (or terminate it and delete the boot volume) |
