#!/bin/sh
set -eu

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

read_version() {
    sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -n 1
}

validate_version() {
    printf '%s\n' "$1" \
        | grep -Eq '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$' \
        || fail "version must be MAJOR.MINOR.PATCH"
}

version_is_greater() {
    awk -v current="$1" -v target="$2" 'BEGIN {
        split(current, c, "."); split(target, t, ".")
        for (i = 1; i <= 3; i++) {
            if (t[i] > c[i]) exit 0
            if (t[i] < c[i]) exit 1
        }
        exit 1
    }'
}

update_metadata() {
    current="$1"
    target="$2"
    release_date="$(date +%Y-%m-%d)"
    temporary="${TMPDIR:-/tmp}/vps-metrics-release-$$"
    mkdir -p "$temporary"

    grep -qx '## \[Unreleased\]' CHANGELOG.md \
        || fail "CHANGELOG.md must contain an exact ## [Unreleased] heading"
    ! grep -Eq "^## \[$target\] - " CHANGELOG.md \
        || fail "CHANGELOG.md already contains release $target"

    awk -v current="$current" -v target="$target" '
        !done && $0 == "version = \"" current "\"" {
            print "version = \"" target "\""
            done = 1
            next
        }
        { print }
        END { if (!done) exit 1 }
    ' pyproject.toml > "$temporary/pyproject.toml" \
        || fail "could not update pyproject.toml"

    awk -v target="$target" -v release_date="$release_date" '
        !done && $0 == "## [Unreleased]" {
            print
            print ""
            print "## [" target "] - " release_date
            done = 1
            next
        }
        { print }
        END { if (!done) exit 1 }
    ' CHANGELOG.md > "$temporary/CHANGELOG.md" \
        || fail "could not update CHANGELOG.md"

    cp "$temporary/pyproject.toml" pyproject.toml
    cp "$temporary/CHANGELOG.md" CHANGELOG.md
}

[ "$#" -eq 0 ] || fail "make release does not accept arguments"

temporary="${TMPDIR:-/tmp}/vps-metrics-release-$$"
trap 'rm -rf "$temporary"' EXIT HUP INT TERM

branch="$(git branch --show-current)"
[ "$branch" = "main" ] || fail "release must run from main, not $branch"
[ -z "$(git status --porcelain)" ] || fail "commit or remove local changes before releasing"

git fetch origin main --tags
git merge-base --is-ancestor origin/main HEAD \
    || fail "local main is behind or diverged from origin/main"

current="$(read_version)"
[ -n "$current" ] || fail "could not read version from pyproject.toml"
printf 'Current version: %s\n' "$current"
printf 'Release version (MAJOR.MINOR.PATCH): '
read -r target
[ -n "$target" ] || fail "release version is required"
validate_version "$target"
version_is_greater "$current" "$target" \
    || fail "release version must be greater than current version $current"

current_major="${current%%.*}"
target_major="${target%%.*}"
if [ "$target_major" -gt "$current_major" ]; then
    printf 'Major version bump detected: %s -> %s\n' "$current" "$target" >&2
    printf 'Type MAJOR to confirm: '
    read -r confirmation
    [ "$confirmation" = "MAJOR" ] || fail "major version bump not confirmed"
fi

tag="v$target"
! git rev-parse --verify "refs/tags/$tag" >/dev/null 2>&1 \
    || fail "tag $tag already exists"

make check
update_metadata "$current" "$target"
make check

git add pyproject.toml CHANGELOG.md
git diff --cached --quiet && fail "release produced no metadata changes"
git commit -m "build: release v$target"
git tag -a "$tag" -m "Release $target"

printf 'Prepared %s\n' "$tag"
printf 'Run: make release-push\n'
