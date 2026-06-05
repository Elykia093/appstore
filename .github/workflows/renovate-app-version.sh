#!/bin/bash
# This script copies the version from docker-compose.yml to config.json.

# app_name=$1
# old_version=$2

# # find all docker-compose files under apps/$app_name (there should be only one)
# docker_compose_files=$(find apps/$app_name/$old_version -name docker-compose.yml)

# for docker_compose_file in $docker_compose_files
# do
# 	# Assuming that the app version will be from the first docker image
# 	first_service=$(yq '.services | keys | .[0]' $docker_compose_file)

# 	image=$(yq .services.$first_service.image $docker_compose_file)

# 	# Only apply changes if the format is <image>:<version>
# 	if [[ "$image" == *":"* ]]; then
# 	  version=$(cut -d ":" -f2- <<< "$image")

# 	  # Trim the "v" prefix
# 	  trimmed_version=${version/#"v"}

#       mv apps/$app_name/$old_version apps/$app_name/$trimmed_version
#     fi
# done

app_name=$1
old_version=$2
new_version=$3

# Trim the "v" prefix if present
trimmed_version=${new_version/#"v"}

echo "Renaming apps/$app_name/$old_version to apps/$app_name/$trimmed_version"
mv "apps/$app_name/$old_version" "apps/$app_name/$trimmed_version"

