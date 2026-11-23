#!/bin/sh
# Build-time staging for the pinned 9.2.0 -> 26.1.0 EnergyPlus transition
# bundle.  The Dockerfile verifies the official release archives before
# invoking this script.  Keep the destination flat: model_upgrade discovers
# these files via EPLUS_TRANSITION_DIR at runtime and never downloads them.
set -eu

if [ "$#" -ne 3 ]; then
    echo "usage: $0 DESTINATION UPDATER_25_1 UPDATER_26_1" >&2
    exit 2
fi

destination=$1
updater_25_1=$2
updater_26_1=$3

for directory in "$updater_25_1" "$updater_26_1"; do
    if [ ! -d "$directory" ]; then
        echo "IDFVersionUpdater directory is missing: $directory" >&2
        exit 1
    fi
done

mkdir -p "$destination"

stage_file() {
    source_file=$1
    destination_file=$2
    mode=$3
    if [ ! -s "$source_file" ]; then
        echo "required transition asset is missing: $source_file" >&2
        exit 1
    fi
    install -m "$mode" "$source_file" "$destination_file"
}

# The first eleven hops come from 25.1.0.  The last two deliberately come
# from the default 26.1.0 engine bundle, so schemas and executables agree.
while read -r source_version target_version source_bundle; do
    [ -n "$source_version" ] || continue
    if [ "$source_bundle" = "25" ]; then
        updater=$updater_25_1
    else
        updater=$updater_26_1
    fi

    stage_file \
        "$updater/Transition-V${source_version}-to-V${target_version}" \
        "$destination/Transition-V${source_version}-to-V${target_version}" \
        755
    stage_file \
        "$updater/V${source_version}-Energy+.idd" \
        "$destination/V${source_version}-Energy+.idd" \
        644
    stage_file \
        "$updater/V${target_version}-Energy+.idd" \
        "$destination/V${target_version}-Energy+.idd" \
        644
    stage_file \
        "$updater/Report Variables ${source_version} to ${target_version}.csv" \
        "$destination/Report Variables ${source_version} to ${target_version}.csv" \
        644
done <<'HOPS'
9-2-0 9-3-0 25
9-3-0 9-4-0 25
9-4-0 9-5-0 25
9-5-0 9-6-0 25
9-6-0 22-1-0 25
22-1-0 22-2-0 25
22-2-0 23-1-0 25
23-1-0 23-2-0 25
23-2-0 24-1-0 25
24-1-0 24-2-0 25
24-2-0 25-1-0 25
25-1-0 25-2-0 26
25-2-0 26-1-0 26
HOPS
