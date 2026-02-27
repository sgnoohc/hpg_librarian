#!/bin/bash
# deploy_pages.sh - Deploy dashboard and data to GitHub Pages (gh-pages branch)
# Uses a git worktree to update gh-pages without touching the main working tree.

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

WORKTREE_DIR="/tmp/librarian-gh-pages-$$"

# Clean up on exit
cleanup() { git worktree remove --force "$WORKTREE_DIR" 2>/dev/null || rm -rf "$WORKTREE_DIR"; }
trap cleanup EXIT

# Fetch latest gh-pages
git fetch origin gh-pages 2>/dev/null || true

# Create worktree for gh-pages branch
git worktree add "$WORKTREE_DIR" gh-pages 2>/dev/null || {
    git worktree add --orphan -b gh-pages "$WORKTREE_DIR" 2>/dev/null || {
        # Fallback: create orphan branch manually
        git worktree add --detach "$WORKTREE_DIR"
        cd "$WORKTREE_DIR"
        git checkout --orphan gh-pages
        git rm -rf . 2>/dev/null || true
        cd "$DIR"
    }
}

# Copy dashboard and data files
cp "$DIR/dashboard/index.html" "$WORKTREE_DIR/"
cp "$DIR/data_avery.json" "$WORKTREE_DIR/" 2>/dev/null || true
cp "$DIR/data_avery-b.json" "$WORKTREE_DIR/" 2>/dev/null || true

# Commit and push
cd "$WORKTREE_DIR"
git add -A
if ! git diff --cached --quiet; then
    git commit -m "Update dashboard data $(date '+%Y-%m-%d %H:%M')"
    git push origin gh-pages
else
    echo "No changes to deploy"
fi
