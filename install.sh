#!/usr/bin/env bash
#
# hae-pulse — install the plugin into a host's runtime location.
#
# Both hosts load the plugin from a fixed directory and reach the shared data
# layer through a *relative path inside this repo*, so this repo has to exist on
# each machine that runs a build. Run this on each machine that owns a clone:
#
#   ./install.sh omarchy   # link omarchy/hyc.hae-pulse into ~/.config/omarchy/plugins
#   ./install.sh macos     # point SwiftBar's plugin directory at macos/plugins
#
# The script is idempotent: re-running it leaves an already-correct setup alone.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ID="hyc.hae-pulse"
TARGET="${1:-}"

# Backups must live outside any directory the host scans for plugins. Omarchy
# loads every entry under plugins/, so a `<name>.bak.<ts>` directory left there
# is picked up as a second plugin with the same manifest id.
BACKUP_ROOT="${XDG_STATE_HOME:-$HOME/.local/state}/hae-pulse/backups"

info() { printf '  %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

link() {
  # link <source> <destination> — symlink swap, never touching the host dir
  local source="$1" dest="$2"
  if [ -L "$dest" ]; then
    if [ "$(readlink "$dest")" = "$source" ]; then
      info "already linked: $dest"
      return 0
    fi
    info "relinking $dest (was -> $(readlink "$dest"))"
    rm "$dest"
  elif [ -e "$dest" ]; then
    mkdir -p "$BACKUP_ROOT"
    local bak="$BACKUP_ROOT/$(basename "$dest").$(date +%Y%m%d%H%M%S)"
    info "real directory in the way, backing up -> $bak"
    mv "$dest" "$bak"
  fi
  ln -s "$source" "$dest"
  info "linked $dest -> $source"
}

install_omarchy() {
  local src="$REPO/omarchy/$PLUGIN_ID"
  local plugins="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins"

  [ -d "$src" ] || die "not found: $src"
  [ -f "$src/collector.py" ] || die "shared symlink missing: $src/collector.py"
  [ -f "$src/manifest.json" ] || die "not found: $src/manifest.json"

  mkdir -p "$plugins"
  link "$src" "$plugins/$PLUGIN_ID"

  # An older revision of this script put backups next to the plugin, where the
  # host happily loads them as a second plugin sharing one manifest id.
  local stale
  stale="$(find "$plugins" -maxdepth 1 -name "$PLUGIN_ID.bak.*" 2>/dev/null || true)"
  if [ -n "$stale" ]; then
    info "WARNING: stale backup(s) inside the plugin directory:"
    printf '    %s\n' $stale
    info "move them out — e.g.  mv <path> $BACKUP_ROOT/"
  fi

  # Prove the shared data layer resolves from the installed location, not just
  # from inside the repo — a wrong-depth symlink still looks fine in git.
  local resolved
  resolved="$(cd "$plugins/$PLUGIN_ID" && python3 -c 'import os,sys;print(os.path.realpath("collector.py"))')"
  [ -f "$resolved" ] || die "collector.py does not resolve from the installed path"
  info "collector.py resolves to $resolved"

  info "restart the shell/Omarchy session to pick up the widget"
}

install_macos() {
  local dir="$REPO/macos/plugins"
  local plugin="$dir/$PLUGIN_ID.10m.py"

  [ -f "$plugin" ] || die "not found: $plugin"
  chmod +x "$plugin"
  info "made executable: $plugin"

  command -v defaults >/dev/null || die "macOS only"
  defaults write com.ameba.SwiftBar PluginDirectory -string "$dir"
  info "SwiftBar PluginDirectory -> $dir"

  # Keep SwiftBar's own status item out of the menu bar even when the plugin
  # errors or is disabled. See README, "隐藏 SwiftBar 自身".
  defaults write com.ameba.SwiftBar StealthMode -bool YES
  info "SwiftBar StealthMode -> YES"

  if [ -d /Applications/SwiftBar.app ]; then
    killall SwiftBar 2>/dev/null || true
    sleep 1
    open -a /Applications/SwiftBar.app
    info "SwiftBar restarted (a restart is required to load a renamed plugin)"
  else
    info "SwiftBar.app not found in /Applications — install it, then re-run"
  fi
}

case "$TARGET" in
  omarchy) install_omarchy ;;
  macos)   install_macos ;;
  all)     install_omarchy; install_macos ;;
  *)
    cat >&2 <<EOF
usage: ./install.sh <omarchy|macos|all>

  omarchy  link omarchy/hyc.hae-pulse into ~/.config/omarchy/plugins
  macos    point SwiftBar at macos/plugins and restart it
  all      both (only meaningful on a machine that runs both)

Run this on each machine that has its own clone of this repo — the wiring uses
paths relative to <repo>, so it must be evaluated per machine.
EOF
    exit 2
    ;;
esac
