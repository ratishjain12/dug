# This file lives in a separate repo: github.com/ratishjain12/homebrew-dug
# Create that repo and put this file at: Formula/dug-cli.rb
#
# Users install with:
#   brew tap ratishjain12/dug
#   brew install dug-cli

class DugCli < Formula
  desc "Dig into any bug with full codebase context — zero LLM calls"
  homepage "https://github.com/ratishjain12/dug"
  version "0.1.0"

  on_macos do
    on_arm do
      url "https://github.com/ratishjain12/dug/releases/download/v#{version}/dug-macos-arm64"
      sha256 "REPLACE_WITH_ARM64_SHA256"
    end
    on_intel do
      url "https://github.com/ratishjain12/dug/releases/download/v#{version}/dug-macos-amd64"
      sha256 "REPLACE_WITH_AMD64_SHA256"
    end
  end

  def install
    bin.install Dir["dug-macos-*"].first => "dug"
  end

  test do
    system "#{bin}/dug", "--help"
  end
end
