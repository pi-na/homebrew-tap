class ClaudeSessions < Formula
  include Language::Python::Shebang

  desc "Browse and resume Claude Code sessions"
  homepage "https://github.com/pi-na/homebrew-tap"
  url "https://github.com/pi-na/homebrew-tap/archive/refs/tags/v0.1.1.tar.gz"
  sha256 "e25e33c7c56c03c269b5960d3bf603019cc9284b6d5a7324ca8076985077426f"
  license "MIT"

  depends_on :macos
  depends_on "python@3.13"

  def install
    rewrite_shebang detected_python_shebang, "claude-sessions.py"
    bin.install "claude-sessions.py" => "claude-sessions"
  end

  test do
    assert_match "claude-sessions", shell_output("#{bin}/claude-sessions --help")
  end
end
