#!/bin/sh
# Sanitize a copied vault note's YAML frontmatter for Quartz.
#
# Hermes sometimes writes frontmatter keys in wikilink form (`[[created]]: ...`).
# Quartz's YAML parser rejects those keys (`nested arrays are not supported
# inside keys`), which aborts the whole build. This transforms ONLY the working
# copy under /quartz/content — the real vault is never touched.
#
# The wikilink brackets are stripped from the key (`[[created]]:` -> `created:`),
# which is the minimal, semantics-preserving fix. Nothing else is rewritten.

for f in "$@"; do
  awk '
    BEGIN { fm = 0; printed = 0 }
    printed { print; next }
    {
      if (fm == 0 && $0 ~ /^---[ \t]*$/) { fm = 1; print; next }
      if (fm == 1 && $0 ~ /^---[ \t]*$/) { fm = 2; print; next }
      if (fm == 1 && $0 ~ /^[ \t]*\[\[[^]]*\]\][ \t]*:/) {
        sub(/^([ \t]*)\[\[([^]]*)\]\]([ \t]*):/, "\\1\\2\\3:")
      }
      print
      if (fm == 2) printed = 1
    }
  ' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
done
