#!/bin/sh
set -eu
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
dest="${XDG_DATA_HOME:-$HOME/.local/share}/PathOCR-app"
mkdir -p "$dest" "$HOME/.local/share/applications"
cp -R "$src/." "$dest/"
chmod +x "$dest/PathOCR"
cat > "$HOME/.local/share/applications/pathocr.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PathOCR
Comment=Local PDF to Markdown OCR
Exec="$dest/PathOCR"
Terminal=false
Categories=Office;
EOF
echo 'Installed. Open PathOCR from your applications menu.'
