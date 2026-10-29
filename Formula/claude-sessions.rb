class ClaudeSessions < Formula
  include Language::Python::Shebang

  desc "Browse and resume Claude Code sessions"
  homepage "https://github.com/pi-na/homebrew-tap"
  url "https://github.com/pi-na/homebrew-tap/archive/refs/tags/v0.1.3.tar.gz"
  sha256 "3e12ef54dbd1263fe5d70e7ecbb86c246c67a79c3a26f80204e7a2b4df489024"
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
