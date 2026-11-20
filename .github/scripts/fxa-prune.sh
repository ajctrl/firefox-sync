#!/bin/sh
# Appended to the mono build script. Its Dockerfile copies /fxa into the runtime image next.
set -eu
cd /fxa
settings=packages/fxa-content-server/dist/settings
source_build=packages/fxa-settings/build

# This fork serves settings/prod. If upstream changes how the assets are laid out,
# leave them for the normal build and integration tests.
if [ -s "$settings/prod/index.html" ] &&
   [ "$(realpath "$settings/prod")" = "/fxa/$settings/prod" ] &&
   [ -z "$(find "$settings/prod" -type l -print -quit)" ]; then
    if [ -d "$source_build" ]; then
        if [ "$(realpath "$source_build")" = "/fxa/$source_build" ] &&
           diff -qr --no-dereference "$source_build" "$settings" >/dev/null; then
            rm -rf -- "$source_build"
        else
            echo "Keeping $source_build because it is not a separate, identical settings tree" >&2
        fi
    fi
    rm -rf -- "$settings/dev" "$settings/stage"
    rm -f -- "$settings/prod/stats.json" "$settings/prod/bundle-report.html"
else
    echo "Keeping all settings assets because the production layout changed" >&2
fi

# The payments UI has already been compiled. The services this stack runs need
# neither the payments build outputs nor Next.js's native Linux SWC compiler.
for output in apps/payments/next/build dist/apps/payments/api node_modules/@next/swc-linux-*; do
    if [ -d "$output" ] && [ "$(realpath "$output")" = "/fxa/$output" ]; then
        rm -rf -- "$output"
    fi
done

# l10n:prime has recorded the translation revision in git-head.txt.
l10n_git=external/l10n/.git
if [ -d "$l10n_git" ] && [ -f "$l10n_git/HEAD" ] &&
   [ "$(realpath "$l10n_git")" = "/fxa/$l10n_git" ]; then
    du -sk -- "$l10n_git"
    rm -rf -- "$l10n_git"
fi

rm -rf -- .nx .venv

# The settings webpack config uses this directory for webpack, Babel, ESLint
# and TypeScript. The admin panel also enables babel-loader's disk cache.
for cache in packages/fxa-settings/node_modules/.cache \
             packages/fxa-admin-panel/node_modules/.cache/babel-loader \
             node_modules/.cache/babel-loader; do
    if [ -d "$cache" ] && [ "$(realpath "$cache")" = "/fxa/$cache" ]; then
        du -sk -- "$cache"
        rm -rf -- "$cache"
    fi
done

# Yarn's install-state.gz is an optimization used by subsequent Yarn commands.
cache=.yarn/install-state.gz
if [ -f "$cache" ] && [ "$(realpath "$cache")" = "/fxa/$cache" ]; then
    du -k -- "$cache"
    rm -f -- "$cache"
fi

# TypeScript and ESLint also write metadata beside project sources and outputs.
for tree in apps libs packages dist; do
    [ -d "$tree" ] || continue
    find "$tree" -name node_modules -prune -o \
        -type f \( -name '*.tsbuildinfo' -o -name .eslintcache \) \
        -printf '%k\t%p\n' -exec rm -f -- {} +
done
