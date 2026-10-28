#!/bin/bash
# Build an offline install bundle for TRex hosts (which often lack pip, venv
# and internet access). Run on a dev machine that has the backend venv.
#
#   deploy/make-bundle.sh [python-version] [arch]
#
# python-version must match `python3 --version` on the target (default 3.12),
# because some dependencies ship compiled wheels. arch defaults to x86_64.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PYVER=${1:-3.12}
ARCH=${2:-x86_64}
PIP=${PIP:-$ROOT/backend/.venv/bin/pip}

VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('$ROOT/backend/pyproject.toml', 'rb'))['project']['version'])")
NAME=trex-gui-$VERSION-py$PYVER-$ARCH
WORK=$(mktemp -d)
STAGE=$WORK/$NAME
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$STAGE/wheels" "$STAGE/backend" "$STAGE/frontend" "$ROOT/dist"

echo "==> building frontend"
(cd "$ROOT/frontend" && npm run build --silent)

echo "==> downloading wheels for python $PYVER / $ARCH"
python3 -c "import tomllib; print('\n'.join(tomllib.load(open('$ROOT/backend/pyproject.toml', 'rb'))['project']['dependencies']))" \
    > "$STAGE/requirements.txt"
"$PIP" download -q -d "$STAGE/wheels" --only-binary=:all: \
    --platform "manylinux2014_$ARCH" --python-version "$PYVER" \
    pip -r "$STAGE/requirements.txt"

echo "==> staging files"
cp -r "$ROOT/backend/trex_gui" "$STAGE/backend/"
find "$STAGE/backend" -name __pycache__ -prune -exec rm -rf {} +
cp -r "$ROOT/frontend/dist" "$STAGE/frontend/"
cp "$ROOT/config.example.yaml" "$ROOT/deploy/install.sh" "$ROOT/deploy/trex-gui.service.in" "$ROOT/LICENSE" "$ROOT/NOTICE" "$STAGE/"
mkdir -p "$STAGE/docs" && cp "$ROOT/docs/"*.md "$STAGE/docs/"
echo "$PYVER" > "$STAGE/PYTHON_VERSION"
echo "$VERSION" > "$STAGE/VERSION"

tar czf "$ROOT/dist/$NAME.tar.gz" -C "$WORK" "$NAME"
echo "==> $ROOT/dist/$NAME.tar.gz ($(du -h "$ROOT/dist/$NAME.tar.gz" | cut -f1))"
