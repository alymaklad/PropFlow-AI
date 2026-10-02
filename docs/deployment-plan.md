# Deployment plan (free)

Goal: put PropFlow online at no cost, safely, as a **public portfolio demo on synthetic data**.
Running it for real customers is a different decision (section 6): it needs a domain, real
email authentication and legal checks, which cannot all be done for free.

Provider terms and free-tier limits change often. Every number below was correct to the best
of our knowledge in October 2026; check the provider's current page before relying on it.

## 1. What has to run

Measured on the development machine (idle): about 1 GB of RAM in total (n8n 430 MB, Odoo
210 MB, the two Postgres instances 100 MB, the rest under 300 MB), 7.4 GB of images, 0.2 GB of
data. Under load expect 2 to 3 GB. Every image has an ARM64 build (checked on Docker Hub:
Odoo 17, n8n 2.42.2, Postgres, nginx, Python, Node, Mailpit, GreenMail, Caddy).

That rules out the free 1 GB machines and the "free web service" platforms, and leaves one
realistic always-free host.

## 2. Recommended setup: one Oracle Cloud Always Free ARM VM

| Piece | Free option | Notes |
|---|---|---|
| Server | Oracle Cloud Always Free, Ampere A1 (ARM): start with 2 OCPU / 12 GB RAM, 100 GB disk, Ubuntu 24.04 | The free allowance covers up to 4 OCPU / 24 GB in total. Needs a card for identity verification. |
| HTTPS + reverse proxy | Caddy (automatic Let's Encrypt certificates) | One container in front; only ports 80 and 443 open. |
| Domain | DuckDNS subdomain, e.g. `propflow-demo.duckdns.org` | Free, up to 5 names. No email authentication possible (see section 6). |
| Private admin access | SSH tunnel (Tailscale optional) | Odoo and n8n are reachable only through an SSH tunnel. The staff dashboard and the mail viewer are public but protected by credentials shared with reviewers. |
| Bot protection | Cloudflare Turnstile (free) on the inquiry form | Works on any domain; small frontend and service change. |
| Outgoing email | **Keep Mailpit**: emails are captured, not delivered | A public form that emails any address would be a spam tool. Reviewers see the emails in Mailpit (private, or behind a password). |
| LLM | Groq free tier (1,000 requests/day, 8,000 tokens/minute measured) | Enough for a demo; the built-in fallback hands leads to a person when it runs out. |
| Backups | Nightly `pg_dump` + volume archives to Oracle Object Storage (free allowance) | Off the VM, so a lost VM is recoverable. |
| Monitoring | UptimeRobot (uptime), Healthchecks.io (backup job pings) | Free plans; alerts by email. |
| CI/CD | GitHub Actions (free for public repositories) | Tests on every push; optional deploy job over SSH. |

Total cost: 0, as long as only Always Free resources are used (section 5).

### Network layout

```
Internet ──443──► Caddy ──► web (buyer site, /api/public only)
                              │
Tailscale only ──► Caddy ──► Odoo, n8n editor, Mailpit, /staff
                              │
inside Docker network ──► ai-service, n8n webhooks, Postgres x2
```

n8n does not need to be public: the buyer site posts to the service, which signs and forwards
to n8n inside the Docker network. Nothing but Caddy listens on a public interface (the compose
file already binds every port to 127.0.0.1).

### Alternatives considered

| Option | Why not (as the main host) |
|---|---|
| Google Cloud e2-micro, AWS/Azure free tiers | 1 GB RAM (too small) or time-limited / credit-based, not free forever |
| Render, Railway, Koyeb, other PaaS free tiers | Services sleep, little RAM, no persistent disks for databases; a 7-service stack does not fit |
| Odoo Online "One App Free" | Free CRM, but custom modules cannot be installed, so `propflow_crm` cannot run |
| Neon / Supabase free Postgres | Possible for the PropFlow database, but adds a network hop and a second provider for no gain |
| Your own computer + Cloudflare quick tunnel | Free and fine for **demos on demand** (random `trycloudflare.com` URL, only while your machine runs). Good fallback if Oracle capacity is unavailable. |

## 3. Work before deploying (repository changes)

| # | Change | Why |
|---|---|---|
| R1 | `docker-compose.prod.yml` override: Caddy service, memory limits per container, restart policies, GreenMail removed (no inbound mail on the demo), `N8N_WEBHOOK_URL` and `ODOO_PUBLIC_URL` set to the real hosts | One command to start production; nothing exposed by accident |
| R2 | `Caddyfile`: public host → `web`; admin hosts → Odoo, n8n, Mailpit, restricted to Tailscale addresses | HTTPS everywhere, private admin |
| R3 | Demo mode: a banner on the buyer site ("Demo: emails are captured, not delivered") and a daily cap on public inquiries (e.g. 100/day) on top of the per-client limit | Honest to visitors; protects the Groq quota and the CRM from spam |
| R4 | Cloudflare Turnstile on the inquiry form, verified by the service | Stops bots before they reach the AI or Odoo |
| R5 | `scripts/backup.sh` + restore instructions, tested once end to end | A backup that was never restored is not a backup |
| R6 | Swap file and Odoo memory limits (`--limit-memory-hard`) in the deploy notes | Survive memory spikes on a small VM |
| R7 | Optional GitHub Actions deploy job: on a tag, SSH to the VM, pull, `docker compose up -d --build`, run `make scenarios --only valid_new_lead,bad_signature` | Repeatable deploys; secrets stay on the server |

## 4. Deployment steps

| Step | What | Done when |
|---|---|---|
| D1 | Create the Oracle Cloud account; choose the home region carefully (it cannot be changed later): the nearest region with A1 capacity | Account active, budget alert set at a few dollars |
| D2 | Create the A1 VM (Always Free-eligible shape only), add your SSH key, open 80/443 in the security list, keep 22 restricted | You can SSH in with a key; password login disabled |
| D3 | Harden: `ufw` (22, 80, 443), unattended security upgrades, fail2ban, a swap file; install Docker and the Compose plugin; join Tailscale | `docker run hello-world` works; the VM appears in Tailscale |
| D4 | DuckDNS names pointing at the VM's public IP (cron updater not needed: Oracle public IPs are static if reserved) | `dig` returns the VM IP |
| D5 | Clone the repository onto the VM's own disk (ext4, not NTFS), create `.env` from `.env.production.example` with **new** secrets, `LLM_PROVIDER=groq` and a separate Groq key for the demo | `docker compose config` passes; no dev secrets reused |
| D6 | Start: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`, then `make odoo-init odoo-bootstrap odoo-seed seed-properties n8n-import` | All services healthy; Caddy has certificates |
| D7 | Admin setup over Tailscale: change Odoo's admin password, create the n8n owner, check the staff dashboard | Admin UIs unreachable from a non-Tailscale network (test from a phone on mobile data) |
| D8 | Smoke test: `make scenarios` (or the core subset), one inquiry from the public site | Lead in Odoo, email in Mailpit, report correct |
| D9 | Backups and monitoring on: nightly backup job, UptimeRobot on the public URL, Healthchecks.io ping from the backup job; do one restore into a scratch database | Alerts arrive; the restore worked |
| D10 | Publish: README link, demo walkthrough (`docs/demo.md`) updated with the public URL | Someone else can follow the demo |

## 5. Cost traps (how "free" turns into a bill)

- Use only Always Free shapes and stay inside the free allowances (A1 total CPU and RAM,
  block storage, Object Storage, outbound data). Set a budget alert before creating anything.
- Oracle can reclaim Always Free instances it considers idle (low CPU, network and memory use
  over several days). A quiet demo can look idle. Either accept the risk and keep backups
  ready, or upgrade the account to pay-as-you-go: Always Free resources stay free and idle
  reclamation does not apply, but anything outside the free shapes is then billed, so the
  budget alert matters even more.
- Free A1 capacity is often unavailable in popular regions; retrying later or choosing another
  region is normal. The fallback in section 2 (your own machine + tunnel) costs nothing.
- Do not enable paid add-ons (managed databases, load balancers beyond the free one, paid
  monitoring) "just to try".
- Groq's free tier never bills; when it runs out the system falls back to handoffs. If you add
  a payment method to Groq, set a spend limit.

## 6. What to consider before deploying

### Purpose: demo or real customers?

Everything above assumes a **demo with synthetic data**. Taking real inquiries changes the
requirements:

| Need | Demo (free) | Real customers |
|---|---|---|
| Domain | DuckDNS subdomain | Your own domain (about USD 10/year) |
| Email | Captured in Mailpit | Real sending with SPF, DKIM and DMARC on your domain (Brevo/Resend free tiers exist, but need the domain); a real inbox for replies |
| Data protection | Synthetic only | Privacy notice on the form, lawful basis and consent records, retention schedule, erasure procedure (built), a data-processing review |
| Legal | None | Egypt's Personal Data Protection Law (Law 151 of 2020) and its executive regulations: check registration/licensing duties and cross-border transfer rules (the VM region and Groq are outside Egypt) |
| Staff access | Shared staff token over Tailscale | Individual accounts / SSO |
| Support | Best effort | Someone on call for the error alerts and dead letters |

### Security

- Only the buyer site is public. Odoo, n8n, Mailpit and the staff dashboard stay behind
  Tailscale. The webhook secret and API keys never reach the browser (already true).
- New secrets for production; never copy the development `.env`. Rotate the Groq key used in
  development, since it has been used on this machine.
- Change Odoo's `admin` password first; delete the "zz probe" workflow from n8n.
- Keep the VM patched; SSH keys only; review `docs/security-and-operations.md` "Before
  production".

### Abuse and quotas

- A public form attracts bots: Turnstile, the per-client limit (5 per 10 minutes) and a daily
  cap keep spam out of Odoo and protect the 1,000 Groq requests per day.
- Outgoing email stays captured in demo mode so the system cannot be used to send mail to
  strangers.

### Reliability

- One free VM is a single point of failure with no SLA. Backups off the VM, a tested restore,
  and uptime alerts are the mitigation. Recovery is "new VM + restore", documented in the
  runbook.
- The free LLM tier limits throughput to a few qualifications per minute; the 150-second
  qualification timeout and the handoff fallback already cover bursts.

### Licences and branding

- n8n's Sustainable Use License allows self-hosting for your own use, including a public demo
  of your project; it does not allow offering n8n itself as a service to others.
- Odoo Community is LGPL; the fonts are SIL OFL; GreenMail and Mailpit are open source.
- Do not present the demo as a real agency or use a real company's name or logo.

### Maintenance

- Odoo 17 is leaving official support; plan an upgrade path before anything real.
- Pin image versions (already done) and update deliberately; re-run `make scenarios` after
  each update.
- Groq models get deprecated; the model name is configuration (`GROQ_MODEL`), and `make eval`
  shows whether a replacement is as accurate.

## 7. Decisions (2026-10-03)

1. **Demo only**, to show a company during a job application.
2. **AWS free plan** (credits for up to six months) on a t4g.small in Frankfurt; Oracle Cloud
   Always Free stays the permanent option if its sign-up works later.
3. **GitHub Actions** deploys (`.github/workflows/deploy.yml`).
4. Reviewers get the buyer site publicly and, with credentials you share, the staff dashboard
   (`/staff`) and the captured emails (`/mail/`, Mailpit behind a password). Odoo and n8n stay
   private and are shown with screenshots or a video.

Step-by-step instructions: `docs/deployment-guide.md`.
