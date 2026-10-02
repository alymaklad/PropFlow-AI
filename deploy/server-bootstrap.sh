#!/usr/bin/env bash
# One-time setup of a fresh Oracle Cloud Ubuntu 24.04 VM for the PropFlow demo.
# Run as the default "ubuntu" user:
#   curl -fsSL https://raw.githubusercontent.com/<you>/<repo>/main/deploy/server-bootstrap.sh -o bootstrap.sh
#   sudo bash bootstrap.sh https://github.com/<you>/<repo>.git
# Safe to re-run.
set -euo pipefail

REPO_URL="${1:?usage: sudo bash server-bootstrap.sh <git clone URL>}"
APP_DIR=/opt/propflow
DEPLOY_USER=deploy

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }

echo "==> Packages and automatic security updates"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -yq
apt-get install -yq docker.io docker-compose-v2 docker-buildx git make curl fail2ban \
  unattended-upgrades netfilter-persistent iptables-persistent
dpkg-reconfigure -f noninteractive unattended-upgrades
systemctl enable --now docker fail2ban

echo "==> Firewall: Oracle's Ubuntu image rejects everything except SSH in iptables"
for port in 80 443; do
  if ! iptables -C INPUT -p tcp -m state --state NEW --dport "$port" -j ACCEPT 2>/dev/null; then
    reject_line=$(iptables -L INPUT --line-numbers | awk '/REJECT/ {print $1; exit}')
    iptables -I INPUT "${reject_line:-1}" -p tcp -m state --state NEW --dport "$port" -j ACCEPT
  fi
done
netfilter-persistent save

echo "==> Swap (4 GB) for memory spikes"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> SSH: keys only"
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload ssh || systemctl reload sshd

echo "==> Deploy user (used by GitHub Actions; can run docker, nothing else)"
id "$DEPLOY_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$DEPLOY_USER"
usermod -aG docker "$DEPLOY_USER"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
touch "/home/$DEPLOY_USER/.ssh/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh/authorized_keys"
chmod 600 "/home/$DEPLOY_USER/.ssh/authorized_keys"

echo "==> Application checkout in $APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" /opt/propflow-backups

echo "==> Daily jobs: refresh listing verification dates, nightly backup"
cat > /etc/cron.d/propflow <<CRON
SHELL=/bin/bash
# Keep the synthetic catalog "recently checked" (listings older than 14 days are hidden)
15 3 * * * $DEPLOY_USER cd $APP_DIR && make -s seed-properties >/dev/null 2>&1
30 3 * * * $DEPLOY_USER cd $APP_DIR && scripts/backup.sh >> /opt/propflow-backups/backup.log 2>&1
CRON

cat <<NEXT

Done. Next steps (docs/deployment-guide.md, "First deploy"):
  1. Add the GitHub Actions public key to /home/$DEPLOY_USER/.ssh/authorized_keys
  2. As $DEPLOY_USER: cp $APP_DIR/.env.production.example $APP_DIR/.env and fill it in
  3. Run the Deploy workflow in GitHub Actions
NEXT
