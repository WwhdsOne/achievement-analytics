#!/usr/bin/env bash
# Production and local rehearsal share this installer. Server needs only shell,
# tar, sha256sum (or shasum), cp, ln and mv; no Python/Go/source checkout.
set -euo pipefail
action="$1"; content="$2"; input="$3"; legacy="${4:-}"
hash_file() {
  if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d ' ' -f 1
  else shasum -a 256 "$1" | cut -d ' ' -f 1; fi
}
valid_object() { [ ! -L "$1" ] && [ -f "$1" ] && [ "$(hash_file "$1")" = "$2" ]; }
# Inspect only a manifest-named file inside the explicit root. Resolve its parent
# to reject directory symlinks escaping that root; current may resolve to releases/.
safe_source() {
  local root="$1" name="$2" sha="$3" base parent candidate
  [ -d "$root" ] || return 1
  base="$(cd "$root" && pwd -P)"
  candidate="$base/$name"
  parent="$(cd "$(dirname "$candidate")" 2>/dev/null && pwd -P)" || return 1
  case "$parent" in "$base"|"$base"/*) ;; *) return 1 ;; esac
  valid_object "$candidate" "$sha" || return 1
  printf '%s\n' "$candidate"
}
reuse_source() {
  local name="$1" sha="$2"
  safe_source "$content" "current/$name" "$sha" && return 0
  [ -n "$legacy" ] && safe_source "$legacy" "$name" "$sha"
}
validate_manifest() {
  # Paths are generated locally and deliberately limited to portable filenames.
  awk -F '\t' 'NF != 3 || length($1) != 64 || $1 ~ /[^a-f0-9]/ || $2 ~ /[^0-9]/ || $3 !~ /^[A-Za-z0-9_.\/-]+$/ || $3 ~ /(^|\/)\.\.?($|\/)/ || $3 ~ /^\// {bad=1} END {exit bad}' "$1"
  [ -s "$1" ]
}
if [ "$action" = plan ]; then
  validate_manifest "$input"
  while IFS=$'\t' read -r sha size name; do
    # An intact stored object is enough to reconstruct any release/path locally.
    # Hash actual bytes: stale manifests cannot hide a corrupted hardlinked inode.
    if ! valid_object "$content/objects/$sha" "$sha" && ! reuse_source "$name" "$sha" >/dev/null; then
      printf 'MISSING %s\n' "$sha"
    fi
  done < "$input"
  echo CONTENT_PLAN_OK
elif [ "$action" = install ]; then
  mkdir -p "$content/objects" "$content/releases"
  # Atomic mkdir serializes switch/install; interrupted installs release via trap.
  lock="$content/.install-lock"
  mkdir "$lock" || { echo 'Content installer already running; retry after it finishes' >&2; exit 1; }
  work=""
  trap 'if [ -n "$work" ]; then rm -rf "$work"; fi; rmdir "$lock"' EXIT
  work="$(mktemp -d "$content/.incoming.XXXXXX")"
  tar -xzf "$input" -C "$work"
  validate_manifest "$work/manifest.tsv"
  version="$(hash_file "$work/manifest.tsv")"
  release="$content/releases/${version}-$(basename "$work")"
  mkdir "$work/release"
  while IFS=$'\t' read -r sha size name; do
    object="$content/objects/$sha"
    if [ -f "$work/objects/$sha" ]; then
      valid_object "$work/objects/$sha" "$sha" || { echo "Invalid object $sha" >&2; exit 1; }
      # Never overwrite a hardlinked inode: existing versions stay untouched.
      mv -f "$work/objects/$sha" "$object"
    fi
    if ! valid_object "$object" "$sha"; then
      if source="$(reuse_source "$name" "$sha")"; then
        # A mutable legacy file must never share its inode with frozen versions.
        # Verify the copied bytes again in case the source changed since planning.
        cp "$source" "$work/seed-$sha"
        valid_object "$work/seed-$sha" "$sha" || { echo "Source changed while copying $name; rerun sync" >&2; exit 1; }
        mv -f "$work/seed-$sha" "$object"
      fi
    fi
    valid_object "$object" "$sha" || { echo "Missing/corrupt object $sha; rerun sync" >&2; exit 1; }
    mkdir -p "$work/release/$(dirname "$name")"
    ln "$object" "$work/release/$name"
  done < "$work/manifest.tsv"
  cp "$work/manifest.tsv" "$work/release/.manifest.tsv"
  mv "$work/release" "$release"
  ln -s "releases/$(basename "$release")" "$work/current"
  # GNU mv -T is not present on macOS; Python-free rename via mv -h there.
  if [ "$(uname -s)" = Darwin ]; then mv -fh "$work/current" "$content/current"
  else mv -fT "$work/current" "$content/current"; fi
  echo "Content active: $(basename "$release") (previous releases retained)"
else
  echo "Usage: $0 plan CONTENT_ROOT MANIFEST [LEGACY_ROOT] | install CONTENT_ROOT DELTA_TAR [LEGACY_ROOT]" >&2
  exit 2
fi
