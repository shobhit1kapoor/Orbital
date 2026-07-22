#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "ORBITAL requires an x86_64 native host." >&2
  exit 1
fi

. /etc/os-release
if [[ "${ID}" != "ubuntu" || "${VERSION_ID}" != "24.04" ]]; then
  echo "Expected Ubuntu 24.04; found ${PRETTY_NAME}." >&2
  exit 1
fi

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  build-essential ca-certificates curl git gnupg jq libcap2-bin make \
  python3 python3-venv

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "${USER}"

sudo tee /etc/sysctl.d/99-orbital.conf >/dev/null <<'EOF'
vm.max_map_count=262144
fs.file-max=1048576
EOF
sudo sysctl --system >/dev/null

sudo tee /etc/security/limits.d/99-orbital.conf >/dev/null <<EOF
${USER} soft nofile 1048576
${USER} hard nofile 1048576
EOF

sudo install -d -m 0755 /sys/fs/bpf
if ! mountpoint -q /sys/fs/bpf; then
  sudo mount -t bpf bpf /sys/fs/bpf
fi
if ! grep -qE '^bpf[[:space:]]+/sys/fs/bpf[[:space:]]+bpf' /etc/fstab; then
  echo 'bpf /sys/fs/bpf bpf defaults 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

# Laptop Ollama is carried over an SSH reverse tunnel bound only to docker0.
sudo install -d -m 0755 /etc/ssh/sshd_config.d
echo 'GatewayPorts clientspecified' | \
  sudo tee /etc/ssh/sshd_config.d/60-orbital-gatewayports.conf >/dev/null
sudo sshd -t
sudo systemctl restart ssh

echo "Native host bootstrap complete. Reconnect to activate Docker group membership."
docker --version || true
sudo docker compose version
test -r /sys/kernel/btf/vmlinux
mountpoint /sys/fs/bpf
if command -v ollama >/dev/null; then
  echo "ERROR: Ollama must remain on the laptop." >&2
  exit 1
fi
