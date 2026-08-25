#!/bin/bash
set -e

APP_NAME="log"
INSTALL_DIR="/opt/$APP_NAME"
SHARE_DIR="/usr/share/$APP_NAME"
GREETER_USER="greeter"
CURRENT_DIR="$(pwd)"

if [ "$EUID" -ne 0 ]; then
  echo "[-] Error: This installation script must be run with sudo."
  echo "    Usage: sudo ./install-update.sh"
  exit 1
fi

# 1. Pull latest code safely as the normal user
if [ -d "$CURRENT_DIR/.git" ]; then
  echo "[+] Checking for remote updates via Git..."
  if [ -n "$SUDO_USER" ]; then
    sudo -u "$SUDO_USER" git -C "$CURRENT_DIR" pull || true
  else
    git -C "$CURRENT_DIR" pull || true
  fi
fi

echo "[+] Starting installation/update of $APP_NAME..."

# 2. Ensure target directories exist
mkdir -p "$INSTALL_DIR"
mkdir -p "$SHARE_DIR/plugins"
mkdir -p "$SHARE_DIR/assets"

# 3. Copy core application files to /opt/log (excluding assets/plugins)
echo "[+] Deploying core application files to $INSTALL_DIR..."
for item in "$CURRENT_DIR"/*; do
    item_name=$(basename "$item")
    
    # Skip git repo, local virtual environments, and user content folders
    if [ "$item_name" = ".git" ] || [ "$item_name" = ".venv" ] || [ "$item_name" = "venv" ] || [ "$item_name" = "plugins" ] || [ "$item_name" = "assets" ]; then
        continue
    fi

    rm -rf "$INSTALL_DIR/$item_name"
    cp -r "$item" "$INSTALL_DIR/"
done

# Copy default assets/plugins to /usr/share/log without overwriting existing user files
if [ -d "$CURRENT_DIR/assets" ]; then
    cp -rn "$CURRENT_DIR/assets/"* "$SHARE_DIR/assets/" 2>/dev/null || true
fi
if [ -d "$CURRENT_DIR/plugins" ]; then
    cp -rn "$CURRENT_DIR/plugins/"* "$SHARE_DIR/plugins/" 2>/dev/null || true
fi

# 4. Ensure 'uv' is installed
if ! command -v uv &> /dev/null; then
    echo "[+] Installing uv for dependency management..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

UV_BIN="$(which uv 2>/dev/null || echo "${HOME}/.cargo/bin/uv")"

# 5. Build/refresh Python virtual environment in /opt/log/venv using system Python
echo "[+] Managing Python virtual environment in $INSTALL_DIR/venv..."
if [ ! -d "$INSTALL_DIR/venv" ]; then
    "$UV_BIN" venv --python /usr/bin/python3 "$INSTALL_DIR/venv"
fi

# 6. Install core project dependencies
echo "[+] Installing core application dependencies..."
if [ -f "$INSTALL_DIR/pyproject.toml" ]; then
    "$UV_BIN" pip install --python "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR"
elif [ -f "$INSTALL_DIR/requirements.txt" ]; then
    "$UV_BIN" pip install --python "$INSTALL_DIR/venv/bin/python" -r "$INSTALL_DIR/requirements.txt"
fi

# 7. Scan and install all plugin requirements from /usr/share/log/plugins/
echo "[+] Scanning for plugin requirements in $SHARE_DIR/plugins..."
find "$SHARE_DIR/plugins" -type f \( -name "*requirement*.txt" -o -name "requirements.txt" \) | while read -r req_file; do
    echo "[->] Installing plugin requirements from: $req_file"
    "$UV_BIN" pip install --python "$INSTALL_DIR/venv/bin/python" -r "$req_file"
done

# 8. Set global permissions (755 allows 'greeter' user to read & execute)
echo "[+] Setting correct system permissions..."
chown -R root:root "$INSTALL_DIR" "$SHARE_DIR"
chmod -R 755 "$INSTALL_DIR" "$SHARE_DIR"

# Ensure greeter user has hardware access
if id "$GREETER_USER" &>/dev/null; then
    usermod -aG audio,video,render,input "$GREETER_USER" 2>/dev/null || true
fi

echo "--------------------------------------------------------"
echo "[✔] Update complete! Application deployed to $INSTALL_DIR"
echo "--------------------------------------------------------"
