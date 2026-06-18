#!/bin/bash
set -euo pipefail

app_name="${1:?app name is required}"
old_version="${2:?old version is required}"
new_version="${3:-}"

if [[ -z "$new_version" ]]; then
    echo "No parsed image version for $app_name, skipping directory rename."
    exit 0
fi

# Renovate may pin Docker images as tag@sha256:digest. 1Panel version
# directories should follow the tag only; floating latest images should use
# the latest directory too.
new_version="${new_version%%@*}"
trimmed_version="${new_version#v}"

if [[ -z "$trimmed_version" || "$trimmed_version" == "$old_version" ]]; then
    echo "Version directory already matches $app_name:$old_version, skipping rename."
    exit 0
fi

source_dir="apps/$app_name/$old_version"
target_dir="apps/$app_name/$trimmed_version"

if [[ ! -d "$source_dir" ]]; then
    echo "Source version directory does not exist: $source_dir"
    exit 1
fi

if [[ -e "$target_dir" ]]; then
    echo "Target version directory already exists: $target_dir"
    exit 1
fi

echo "Renaming $source_dir to $target_dir"
mv "$source_dir" "$target_dir"
