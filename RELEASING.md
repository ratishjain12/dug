# Releasing dug

Step-by-step checklist for every release. Complete the one-time setup below once, then follow the per-release section for each new version.

---

## One-time setup

These steps only need to be done once, before the very first release.

### 1. PyPI account + token

1. Create an account at [pypi.org](https://pypi.org) if you don't have one
2. Go to **Account Settings → API tokens → Add API token**
   - Scope: **Entire account** (for the first publish; switch to project-scoped after `dug-cli` exists)
   - Copy the token — you won't see it again
3. In the **dug** GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `PYPI_TOKEN`
   - Value: the token you copied

### 2. Homebrew tap repo

1. Create a new **public** GitHub repo: `ratishjain12/homebrew-dug`
2. In that repo, create the file `Formula/dug-cli.rb` with this initial content:

```ruby
class DugCli < Formula
  desc "Dig into any bug with full codebase context"
  homepage "https://github.com/ratishjain12/dug"
  version "0.1.0"

  on_macos do
    if Hardware::CPU.arm?
      url "https://github.com/ratishjain12/dug/releases/download/v#{version}/dug-macos-arm64"
      sha256 "PLACEHOLDER"
    else
      url "https://github.com/ratishjain12/dug/releases/download/v#{version}/dug-macos-amd64"
      sha256 "PLACEHOLDER"
    end
  end

  def install
    bin.install Dir["dug*"].first => "dug"
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/dug --version")
  end
end
```

The `update-homebrew.yml` workflow will replace the PLACEHOLDERs and version automatically on each release.

3. Create a **fine-grained Personal Access Token** at GitHub → Settings → Developer settings → Fine-grained tokens
   - Repository access: **Only `ratishjain12/homebrew-dug`**
   - Permissions: **Contents → Read and write**
   - Copy the token

4. In the **dug** GitHub repo secrets, add:
   - Name: `HOMEBREW_TAP_TOKEN`
   - Value: the PAT you just created

### 3. Scoop bucket repo

1. Create a new **public** GitHub repo: `ratishjain12/scoop-dug`
2. Create the file `bucket/dug-cli.json`:

```json
{
  "version": "0.1.0",
  "description": "Dig into any bug with full codebase context",
  "homepage": "https://github.com/ratishjain12/dug",
  "license": "MIT",
  "architecture": {
    "64bit": {
      "url": "https://github.com/ratishjain12/dug/releases/download/v0.1.0/dug-windows-amd64.exe",
      "hash": "REPLACE_AFTER_RELEASE",
      "bin": "dug-windows-amd64.exe"
    }
  },
  "checkver": {
    "github": "https://github.com/ratishjain12/dug"
  }
}
```

Update the `hash` field after the first release (see per-release step 5 below).

---

## Per-release checklist

Follow these steps for every new version (`v0.1.0`, `v0.2.0`, etc.).

### 1. Prep the code

- [ ] All changes merged to `main`
- [ ] Bump `version` in `pyproject.toml`
- [ ] Commit the version bump: `git commit -m "chore: bump version to v0.x.y"`
- [ ] Push to `main`: `git push origin main`

### 2. Tag and push

```sh
git tag v0.x.y
git push origin v0.x.y
```

This triggers the release workflow in GitHub Actions.

### 3. Watch GitHub Actions (takes ~8 minutes)

Go to `https://github.com/ratishjain12/dug/actions` and watch:

| Job | What it does | Expect |
|---|---|---|
| `Publish to PyPI` | Builds wheel + sdist, uploads to PyPI | green ✓ |
| `Build binary — macos-arm64` | PyInstaller build for Apple Silicon | green ✓ |
| `Build binary — macos-amd64` | PyInstaller build for Intel Mac | green ✓ |
| `Build binary — linux-amd64` | PyInstaller build for Linux | green ✓ |
| `Build binary — windows-amd64` | PyInstaller build for Windows | green ✓ |
| `Create GitHub Release` | Attaches all artifacts, generates release notes | green ✓ |
| `Update Homebrew tap` | Patches `homebrew-dug/Formula/dug-cli.rb` | green ✓ |

### 4. Scoop (manual — ~2 minutes)

The Scoop manifest is updated manually after the release assets are live:

1. Go to the GitHub Release: `https://github.com/ratishjain12/dug/releases/tag/v0.x.y`
2. Click `dug-windows-amd64.exe` → copy the download URL
3. Download the file locally and compute its SHA256:
   ```sh
   # macOS / Linux
   shasum -a 256 dug-windows-amd64.exe

   # Windows (PowerShell)
   Get-FileHash dug-windows-amd64.exe -Algorithm SHA256
   ```
4. Edit `bucket/dug-cli.json` in `ratishjain12/scoop-dug`:
   - Update `version`
   - Update `url` with the new release download URL
   - Update `hash` with the SHA256
5. Commit and push — Scoop users pick it up on their next `scoop update`

### 5. Smoke test (verify all install paths work)

```sh
# pipx
pipx install "dug-cli==0.x.y"
dug --version

# Homebrew (macOS)
brew update
brew upgrade dug-cli
dug --version

# curl installer
curl -fsSL https://raw.githubusercontent.com/ratishjain12/dug/main/install.sh | sh
dug --version

# Direct binary (Linux)
wget https://github.com/ratishjain12/dug/releases/download/v0.x.y/dug-linux-amd64
chmod +x dug-linux-amd64
./dug-linux-amd64 --version
```

### 6. Announce (optional)

- Post to relevant communities (HN, Reddit r/programming, Discord servers)
- Update any external links pointing to docs or install instructions

---

## Troubleshooting

**PyPI publish fails with "403 Forbidden"**
→ The `PYPI_TOKEN` secret is wrong or expired. Regenerate it at pypi.org and update the secret.

**Homebrew update job fails with "Permission denied"**
→ The `HOMEBREW_TAP_TOKEN` PAT expired or lacks write access to `homebrew-dug`. Regenerate and update the secret.

**Binary build fails on Windows**
→ Check the PyInstaller step in the Actions log. Common cause: a dependency import that PyInstaller can't resolve. Add `--hidden-import=<module>` to the build command in `release.yml`.

**`uv publish` says package name already taken**
→ The package name `dug-cli` may already exist on PyPI. Check pypi.org and rename in `pyproject.toml` if needed.
