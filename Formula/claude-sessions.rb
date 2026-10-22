class ClaudeSessions < Formula
  include Language::Python::Shebang

  desc "Browse and resume Claude Code sessions"
  homepage "https://github.com/pi-na/homebrew-tap"
  url "https://github.com/pi-na/homebrew-tap/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "3fa4f4ac9a2cef9bda664a331ddecab415c6440e42f591cc61c91432ab50da53"
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
