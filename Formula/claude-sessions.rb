class ClaudeSessions < Formula
  include Language::Python::Shebang

  desc "Browse and resume Claude Code sessions"
  homepage "https://github.com/pi-na/homebrew-tap"
  url "https://github.com/pi-na/homebrew-tap/archive/refs/tags/v0.1.2.tar.gz"
  sha256 "b017bd4cddb858fb99441577c55e092cc4319cc99ae9e397442ed7e8ad0de1c7"
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
