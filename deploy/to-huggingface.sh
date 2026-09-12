#!/usr/bin/env bash
# Publish this app as a Hugging Face Space. You upload ~16 MB of source;
# HF builds the image on their machines and pulls the ~2 GB of dependencies
# and models over their own network. Nothing large crosses your connection.
#
#   deploy/to-huggingface.sh <your-hf-username>/<space-name>
#
# One-time: create the Space at https://huggingface.co/new-space
#           choose SDK = Docker, then run this.
set -eu
cd "$(dirname "$0")/.."

SPACE="${1:-}"
[ -n "$SPACE" ] || { echo "usage: deploy/to-huggingface.sh <user>/<space>"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "· cloning the Space"
git clone "https://huggingface.co/spaces/$SPACE" "$WORK/space" 2>/dev/null \
  || { echo "  could not clone — create the Space first (SDK: Docker)"; exit 1; }

echo "· staging source (no data/, no .venv, no .pgdata)"
for p in app scripts .streamlit streamlit_app.py; do
  cp -r "$p" "$WORK/space/"
done
mkdir -p "$WORK/space/docker"
cp docker/requirements-cloud.txt docker/entrypoint-cloud.sh "$WORK/space/docker/"

# Spaces requires a root Dockerfile and a README with YAML frontmatter.
cp docker/Dockerfile.cloud "$WORK/space/Dockerfile"
cp deploy/huggingface-README.md "$WORK/space/README.md"

cat > "$WORK/space/.gitignore" <<'GI'
.venv/
.pgdata/
__pycache__/
data/
*.log
.env
GI

cd "$WORK/space"
git add -A
if git diff --cached --quiet; then
  echo "· nothing changed"
  exit 0
fi
git commit -q -m "deploy $(date -u +%Y-%m-%dT%H:%MZ)"
echo "· pushing $(git diff --cached --stat HEAD~1 2>/dev/null | tail -1)"
git push

cat <<DONE

· pushed. HF is building now — watch it at:
    https://huggingface.co/spaces/$SPACE

  Before it can answer, set these in Settings → Variables and secrets:
    DATABASE_URL        (secret)   postgresql://…  from Supabase
    ANTHROPIC_API_KEY   (secret)   sk-ant-…
    LLM_PROVIDER        (variable) anthropic
    LLM_MODEL           (variable) claude-opus-5
    PORT                (variable) 7860

  Groq will NOT work on Spaces — datacenter IPs are blocked at its edge.
DONE
