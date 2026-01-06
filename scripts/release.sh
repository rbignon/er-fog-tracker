#!/bin/bash
# Release script for er-fog-tracker
# Updates version in all components, creates commit and tag

set -e

VERSION=$1

if [ -z "$VERSION" ]; then
    echo "Usage: ./scripts/release.sh <version>"
    echo "Example: ./scripts/release.sh 0.2.0"
    exit 1
fi

# Validate semver format
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Version must be in semver format (e.g., 0.2.0)"
    exit 1
fi

echo "Updating version to $VERSION..."

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# 1. Update server/pyproject.toml
echo "  - server/pyproject.toml"
sed -i "s/^version = \".*\"/version = \"$VERSION\"/" "$ROOT_DIR/server/pyproject.toml"

# 2. Update server/fogtracker/__init__.py
echo "  - server/fogtracker/__init__.py"
sed -i "s/^__version__ = \".*\"/__version__ = \"$VERSION\"/" "$ROOT_DIR/server/fogtracker/__init__.py"

# 3. Update mod/Cargo.toml (only first occurrence = package version)
echo "  - mod/Cargo.toml"
sed -i "0,/^version = /s/^version = \".*\"/version = \"$VERSION\"/" "$ROOT_DIR/mod/Cargo.toml"

# 4. Regenerate mod/Cargo.lock to match updated Cargo.toml
echo "  - mod/Cargo.lock"
cargo update --manifest-path "$ROOT_DIR/mod/Cargo.toml" --workspace

# 5. Update web/js/version.js
echo "  - web/js/version.js"
cat > "$ROOT_DIR/web/js/version.js" << EOF
/**
 * Application version constant.
 * Updated by scripts/release.sh during release process.
 */
export const VERSION = '$VERSION';
EOF

echo ""
echo "Version updated to $VERSION in all files."
echo ""

# 6. Git commit and tag
echo "Creating git commit and tag..."
git -C "$ROOT_DIR" add \
    server/pyproject.toml \
    server/fogtracker/__init__.py \
    mod/Cargo.toml \
    mod/Cargo.lock \
    web/js/version.js \
    CHANGELOG.md

git -C "$ROOT_DIR" commit -m "release: v$VERSION"
git -C "$ROOT_DIR" tag "v$VERSION"

echo ""
echo "Done! Version updated to $VERSION"
echo ""
echo "To publish the release:"
echo "  git push && git push --tags"
