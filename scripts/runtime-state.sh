#!/usr/bin/env bash

# Prepare a launcher-owned runtime directory for coordination files and logs.
# The fixed /tmp filenames used previously could be pre-created as symlinks.
studio_prepare_runtime_dir() {
    local runtime_base
    umask 077
    runtime_base="${STUDIO_STATE_DIR:-${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/claude-code-studio-${UID:-$(id -u)}}"

    case "$runtime_base" in
        /*) ;;
        *) echo "ERROR: STUDIO_STATE_DIR must be an absolute path." >&2; return 1 ;;
    esac
    if [ -L "$runtime_base" ]; then
        echo "ERROR: refusing symlink Studio runtime directory: $runtime_base" >&2
        return 1
    fi
    if [ -e "$runtime_base" ] && { [ ! -d "$runtime_base" ] || [ ! -O "$runtime_base" ]; }; then
        echo "ERROR: Studio runtime path is not an owned directory: $runtime_base" >&2
        return 1
    fi

    mkdir -p "$runtime_base"
    if [ -L "$runtime_base" ] || [ ! -d "$runtime_base" ] || [ ! -O "$runtime_base" ]; then
        echo "ERROR: failed to create an owned Studio runtime directory: $runtime_base" >&2
        return 1
    fi
    chmod 700 "$runtime_base"
    STUDIO_RUNTIME_DIR="$runtime_base"
    export STUDIO_RUNTIME_DIR
}
