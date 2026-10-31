#!/usr/bin/env bash
# Run make inside the edhiphy build image.
#
#   DATA_DIR=/path/to/data ./run_docker.sh [make arguments]
#   BUILD_DIR=/tmp/edhiphy-test ./run_docker.sh CORPUS=test all
#
# Builds the image (cached) and runs it as the calling user with these bind
# mounts; nothing is copied into or out of the container:
#
#   repository              -> /work            read-only
#   $DATA_DIR/raw           -> /data/raw        read-only
#   $DATA_DIR/curated       -> /data/curated    read-only
#   $DATA_DIR/feedback      -> /data/feedback   read-only
#   $DATA_DIR/reference     -> /data/reference  read-only
#   $DATA_DIR/build         -> /data/build      read-write
#
# Without DATA_DIR (synthetic test corpus), BUILD_DIR is mounted at
# /data/build. Input directories that do not exist are not mounted.
set -euo pipefail

repo=$(cd "$(dirname "$0")" && pwd)
image=${EDHIPHY_IMAGE:-edhiphy-build:dev}

if [[ -n ${DATA_DIR:-} ]]; then
	build_dir=$DATA_DIR/build
else
	build_dir=${BUILD_DIR:?set DATA_DIR, or BUILD_DIR for the test corpus}
fi
mkdir -p "$build_dir"
build_dir=$(cd "$build_dir" && pwd)

docker build --quiet -t "$image" "$repo" >/dev/null

opts=(--rm --user "$(id -u):$(id -g)"
	--mount "type=bind,src=$repo,dst=/work,readonly"
	--mount "type=bind,src=$build_dir,dst=/data/build")
make_args=(BUILD_DIR=/data/build)
if [[ -n ${DATA_DIR:-} ]]; then
	for d in raw curated feedback reference; do
		if [[ -d $DATA_DIR/$d ]]; then
			opts+=(--mount "type=bind,src=$(cd "$DATA_DIR/$d" && pwd),dst=/data/$d,readonly")
		fi
	done
	make_args+=(DATA_DIR=/data)
fi

# Provenance for Build_Info (git is not installed in the image).
dirty=no
if [[ -n $(git -C "$repo" status --porcelain --untracked-files=no 2>/dev/null) ]]; then
	dirty=yes
fi
opts+=(-e "GIT_COMMIT=$(git -C "$repo" rev-parse HEAD 2>/dev/null || echo unknown)"
	-e "GIT_DIRTY=$dirty")
if [[ -n ${SOURCE_DATE_EPOCH:-} ]]; then
	opts+=(-e SOURCE_DATE_EPOCH)
fi
if [[ -t 0 && -t 1 ]]; then
	opts+=(-it)
fi

exec docker run "${opts[@]}" "$image" make "${make_args[@]}" "$@"
