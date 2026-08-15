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
    
    if [ "$item_name" = ".git" ]; then
        continue
    fi

    if ([ "$item_name" = "plugins" ] || [ "$item_name" = "assets" ]) && [ -d "$INSTALL_DIR/$item_name" ]; then
        echo "[~] Preserving existing '$item_name' directory..."
        continue
    fi

    rm -rf "$INSTALL_DIR/$item_name"
    cp -r "$item" "$INSTALL_DIR/"
done

mkdir -p "$INSTALL_DIR/plugins"
mkdir -p "$INSTALL_DIR/assets"

# 4. Ensure 'uv' is installed on the system (required for git-based dependencies)
if ! command -v uv &> /dev/null; then
    echo "[+] Installing uv for dependency management..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# Locate uv binary (defaults to root's cargo bin when run with sudo)
UV_BIN="${HOME}/.cargo/bin/uv"
if [ ! -f "$UV_BIN" ] && command -v uv &> /dev/null; then
    UV_BIN="uv"
fi

# 5. Set up or refresh Python virtual environment
echo "[+] Managing Python virtual environment..."
if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi

# 6. Install project and its Git sources using uv
echo "[+] Installing project and dependencies via uv..."
"$UV_BIN" pip install --python "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR"

# 7. Secure permissions
echo "[+] Setting correct permissions..."
chown -R root:root "$INSTALL_DIR"
chmod -R 755 "$INSTALL_DIR"

echo "--------------------------------------------------------"
echo "[✔] Update complete successfully with uv sources!"
echo "--------------------------------------------------------"
