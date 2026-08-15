#!/bin/bash
set -e

APP_NAME="log"
INSTALL_DIR="/opt/$APP_NAME"
CURRENT_DIR="$(pwd)"

if [ "$EUID" -ne 0 ]; then
  echo "[-] Error: This installation script must be run with sudo."
  echo "    Usage: sudo ./install.sh"
  exit 1
fi

# 1. Pull latest code safely as the normal user
if [ -d "$CURRENT_DIR/.git" ]; then
  echo "[+] Checking for remote updates via Git..."
  if [ -n "$SUDO_USER" ]; then
    sudo -u "$SUDO_USER" git -C "$CURRENT_DIR" pull
  else
    git -C "$CURRENT_DIR" pull
  fi
fi

echo "[+] Starting installation/update of $APP_NAME..."

# 2. Create target directory if it doesn't exist
mkdir -p "$INSTALL_DIR"

# 3. Copy files selectively to preserve plugins and assets
echo "[+] Updating core application files..."
for item in "$CURRENT_DIR"/*; do
    item_name=$(basename "$item")
    
    # Skip copying git files
    if [ "$item_name" = ".git" ]; then
        continue
    fi

    # If the folder is 'plugins' or 'assets' and already exists in /opt/, DO NOT overwrite it
    if ([ "$item_name" = "plugins" ] || [ "$item_name" = "assets" ]) && [ -d "$INSTALL_DIR/$item_name" ]; then
        echo "[~] Preserving existing '$item_name' directory..."
        continue
    fi

    # Otherwise, copy/update the file or folder
    rm -rf "$INSTALL_DIR/$item_name"
    cp -r "$item" "$INSTALL_DIR/"
done

# 4. Ensure plugins and assets folders exist (even if they weren't in the git repo)
mkdir -p "$INSTALL_DIR/plugins"
mkdir -p "$INSTALL_DIR/assets"

# 5. Set up or refresh Python virtual environment
echo "[+] Managing Python virtual environment..."
if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip

if [ -f "$INSTALL_DIR/pyproject.toml" ]; then
    "$INSTALL_DIR/venv/bin/pip" install "$INSTALL_DIR"
elif [ -f "$INSTALL_DIR/requirements.txt" ]; then
    "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
fi

# 6. Secure permissions
echo "[+] Setting correct permissions..."
chown -R root:root "$INSTALL_DIR"
chmod -R 755 "$INSTALL_DIR"

echo "--------------------------------------------------------"
echo "[✔] Update complete! Your plugins and assets are safe."
echo "--------------------------------------------------------"
