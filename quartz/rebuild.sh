#!/bin/sh
# Sync the Obsidian vault into Quartz content, then build the static site.
# Runs at container start and on every `POST /rebuild`.
#
# Quartz rmdir's its output directory, which fails if that path is a Docker
# mount point — so we build into a local dir (/quartz/.build) and then rsync
# the result onto the OUTPUT_DIR volume shared with Caddy.

set -e

echo "[quartz] syncing vault: ${VAULT_DIR} -> ${CONTENT_DIR}"
mkdir -p "${CONTENT_DIR}"
rsync -a --delete --exclude='.obsidian/' --exclude='.git/' --exclude='.trash/' \
  "${VAULT_DIR}/" "${CONTENT_DIR}/"

echo "[quartz] sanitizing frontmatter keys in the copy"
find "${CONTENT_DIR}" -name '*.md' -print0 | xargs -0 ./sanitize.sh

echo "[quartz] ensuring a home note exists"
if [ ! -f "${CONTENT_DIR}/index.md" ]; then
  cp ./index.template.md "${CONTENT_DIR}/index.md"
  echo "[quartz] wrote generated home note ${CONTENT_DIR}/index.md"
fi

echo "[quartz] installing plugins from config lockfile"
npx quartz plugin install --from-config >/dev/null 2>&1 || true

echo "[quartz] baking baseUrl=${BASE_URL} into config"
sed -i "s|__BASE_URL__|${BASE_URL}|g" quartz.config.yaml

echo "[quartz] building site from ${CONTENT_DIR}"
rm -rf /quartz/.build
npx quartz build --directory "${CONTENT_DIR}" --output /quartz/.build

echo "[quartz] publishing build -> ${OUTPUT_DIR}"
# Wipe the output volume's CONTENTS first (cannot rm the mountpoint itself —
# "Resource busy") so stale case-collided folders from prior builds
# (e.g. both 00-Journal and 00-journal) cannot linger after a rename/rsync.
find "${OUTPUT_DIR}" -mindepth 1 -delete
mkdir -p "${OUTPUT_DIR}"
rsync -a /quartz/.build/ "${OUTPUT_DIR}/"

echo "[quartz] build complete"
