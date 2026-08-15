#!/bin/bash
# Exit immediately if a command exits with a non-zero status
set -e

# Configuration variables
APP_NAME="log"
INSTALL_DIR="/opt/$APP_NAME"
CURRENT_DIR="$(pwd)"

# 1. Ensure the script is run with sudo/root privileges
if [ "$EUID" -ne 0 ]; then
  echo "[-] Error: This installation script must be run with sudo."
  echo "    Usage: sudo ./install.sh"
  exit 1
fi

# 2. If this is a git repository, pull the latest changes first
# Using $SUDO_USER ensures git runs as your normal user, preventing .git permission issues
if [ -d "$CURRENT_DIR/.git" ]; then
  echo "[+] Checking for remote updates via Git..."
  if [ -n "$SUDO_USER" ]; then
    sudo -u "$SUDO_USER" git -C "$CURRENT_DIR" pull
  else
    git -C "$CURRENT_DIR" pull
  fi
fi

echo "[+] Starting installation of $APP_NAME..."

# 3. Create the system-wide installation directory
mkdir -p "$INSTALL_DIR"

# 4. Copy project files from the cloned location to /opt/
echo "[+] Copying project files to $INSTALL_DIR..."
cp -r "$CURRENT_DIR"/* "$INSTALL_DIR/"

# 5. Create an isolated Python virtual environment inside /opt
echo "[+] Setting up Python virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip

# 6. Install project dependencies
if [ -f "$INSTALL_DIR/pyproject.toml" ]; then
    echo "[+] Installing project via pyproject.toml..."
    "$INSTALL_DIR/venv/bin/pip" install "$INSTALL_DIR"
elif [ -f "$INSTALL_DIR/requirements.txt" ]; then
    echo "[+] Installing dependencies from requirements.txt..."
    "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
else
    echo "[!] Warning: No pyproject.toml or requirements.txt found. Skipping dependency installation."
fi

# 7. Secure file ownership and permissions for the system greeter user
echo "[+] Setting correct permissions..."
chown -R root:root "$INSTALL_DIR"
chmod -R 755 "$INSTALL_DIR"

echo "--------------------------------------------------------"
echo "[✔] Update and installation completed successfully!"
echo "[+] Your app is now updated and installed at: $INSTALL_DIR"
echo "--------------------------------------------------------"
