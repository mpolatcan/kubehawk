class Kubeagle < Formula
  include Language::Python::Virtualenv

  desc "Analyze EKS clusters and Helm charts with an interactive TUI"
  homepage "https://github.com/mpolatcan/kubeagle"
  url "https://github.com/mpolatcan/kubeagle.git", branch: "main"
  version "main"
  license "MIT"

  depends_on "python@3.13"

  # Skip post-install relocation for pre-built native extensions (pydantic-core .so)
  skip_clean "libexec"

  # --- Native extension wheels (installed in post_install to avoid relocation errors) ---

  resource "orjson" do
    url "https://files.pythonhosted.org/packages/10/43/61a77040ce59f1569edf38f0b9faadc90c8cf7e9bec2e0df51d0132c6bb7/orjson-3.11.5-cp313-cp313-macosx_10_15_x86_64.macosx_11_0_arm64.macosx_10_15_universal2.whl", using: :nounzip
    sha256 "3b01799262081a4c47c035dd77c1301d40f568f77cc7ec1bb7db5d63b0a01629"
  end

  resource "ujson-arm" do
    url "https://files.pythonhosted.org/packages/5b/a4/f611f816eac3a581d8a4372f6967c3ed41eddbae4008d1d77f223f1a4e0a/ujson-5.11.0-cp313-cp313-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "a31c6b8004438e8c20fc55ac1c0e07dad42941db24176fe9acf2815971f8e752"
  end

  resource "ujson-intel" do
    url "https://files.pythonhosted.org/packages/1c/ec/2de9dd371d52c377abc05d2b725645326c4562fc87296a8907c7bcdf2db7/ujson-5.11.0-cp313-cp313-macosx_10_13_x86_64.whl", using: :nounzip
    sha256 "109f59885041b14ee9569bf0bb3f98579c3fa0652317b355669939e5fc5ede53"
  end

  resource "claude-agent-sdk" do
    url "https://files.pythonhosted.org/packages/1e/26/8890529d9bf2415836fff55bbec1860a1b676abe06bd99632d5c568f9b68/claude_agent_sdk-0.1.38-py3-none-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "77a4ba1a78bb16c67152c35692e7d070e7e09d311f95abdc02e913f762109910"
  end

  # --- Pure-Python sdist resources ---

  resource "annotated-doc" do
    url "https://files.pythonhosted.org/packages/57/ba/046ceea27344560984e26a590f90bc7f4a75b06701f653222458922b558c/annotated_doc-0.0.4.tar.gz"
    sha256 "fbcda96e87e9c92ad167c2e53839e57503ecfda18804ea28102353485033faa4"
  end

  resource "annotated-types" do
    url "https://files.pythonhosted.org/packages/ee/67/531ea369ba64dcff5ec9c3402f9f51bf748cec26dde048a2f973a4eea7f5/annotated_types-0.7.0.tar.gz"
    sha256 "aff07c09a53a08bc8cfccb9c85b05f1aa9a2a6f23728d790723543408344ce89"
  end

  resource "click" do
    url "https://files.pythonhosted.org/packages/3d/fa/656b739db8587d7b5dfa22e22ed02566950fbfbcdc20311993483657a5c0/click-8.3.1.tar.gz"
    sha256 "12ff4785d337a1bb490bb7e9c2b1ee5da3112e94a8622f26a6c77f5d2fc6842a"
  end

  resource "linkify-it-py" do
    url "https://files.pythonhosted.org/packages/2a/ae/bb56c6828e4797ba5a4821eec7c43b8bf40f69cda4d4f5f8c8a2810ec96a/linkify-it-py-2.0.3.tar.gz"
    sha256 "68cda27e162e9215c17d786649d1da0021a451bdc436ef9e0fa0ba5234b9b048"
  end

  resource "loguru" do
    url "https://files.pythonhosted.org/packages/3a/05/a1dae3dffd1116099471c643b8924f5aa6524411dc6c63fdae648c4f1aca/loguru-0.7.3.tar.gz"
    sha256 "19480589e77d47b8d85b2c827ad95d49bf31b0dcde16593892eb51dd18706eb6"
  end

  resource "markdown-it-py" do
    url "https://files.pythonhosted.org/packages/5b/f5/4ec618ed16cc4f8fb3b701563655a69816155e79e24a17b651541804721d/markdown_it_py-4.0.0.tar.gz"
    sha256 "cb0a2b4aa34f932c007117b194e945bd74e0ec24133ceb5bac59009cda1cb9f3"
  end

  resource "mdit-py-plugins" do
    url "https://files.pythonhosted.org/packages/b2/fd/a756d36c0bfba5f6e39a1cdbdbfdd448dc02692467d83816dff4592a1ebc/mdit_py_plugins-0.5.0.tar.gz"
    sha256 "f4918cb50119f50446560513a8e311d574ff6aaed72606ddae6d35716fe809c6"
  end

  resource "mdurl" do
    url "https://files.pythonhosted.org/packages/d6/54/cfe61301667036ec958cb99bd3efefba235e65cdeb9c84d24a8293ba1d90/mdurl-0.1.2.tar.gz"
    sha256 "bb413d29f5eea38f31dd4754dd7377d4465116fb207585f97bf925588687c1ba"
  end

  resource "platformdirs" do
    url "https://files.pythonhosted.org/packages/1b/04/fea538adf7dbbd6d186f551d595961e564a3b6715bdf276b477460858672/platformdirs-4.9.2.tar.gz"
    sha256 "9a33809944b9db043ad67ca0db94b14bf452cc6aeaac46a88ea55b26e2e9d291"
  end

  resource "plotext" do
    url "https://files.pythonhosted.org/packages/c9/d7/f75f397af966fe252d0d34ffd3cae765317fce2134f925f95e7d6725d1ce/plotext-5.3.2.tar.gz"
    sha256 "52d1e932e67c177bf357a3f0fe6ce14d1a96f7f7d5679d7b455b929df517068e"
  end

  resource "pydantic" do
    url "https://files.pythonhosted.org/packages/69/44/36f1a6e523abc58ae5f928898e4aca2e0ea509b5aa6f6f392a5d882be928/pydantic-2.12.5.tar.gz"
    sha256 "4d351024c75c0f085a9febbb665ce8c0c6ec5d30e903bdb6394b7ede26aebb49"
  end

  resource "pydantic-core-arm" do
    url "https://files.pythonhosted.org/packages/94/02/abfa0e0bda67faa65fef1c84971c7e45928e108fe24333c81f3bfe35d5f5/pydantic_core-2.41.5-cp313-cp313-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "112e305c3314f40c93998e567879e887a3160bb8689ef3d2c04b6cc62c33ac34"
  end

  resource "pydantic-core-intel" do
    url "https://files.pythonhosted.org/packages/87/06/8806241ff1f70d9939f9af039c6c35f2360cf16e93c2ca76f184e76b1564/pydantic_core-2.41.5-cp313-cp313-macosx_10_12_x86_64.whl", using: :nounzip
    sha256 "941103c9be18ac8daf7b7adca8228f8ed6bb7a1849020f643b3a14d15b1924d9"
  end

  resource "pygments" do
    url "https://files.pythonhosted.org/packages/b0/77/a5b8c569bf593b0140bde72ea885a803b82086995367bf2037de0159d924/pygments-2.19.2.tar.gz"
    sha256 "636cb2477cec7f8952536970bc533bc43743542f70392ae026374600add5b887"
  end

  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/05/8e/961c0007c59b8dd7729d542c61a4d537767a59645b82a0b521206e1e25c2/pyyaml-6.0.3.tar.gz"
    sha256 "d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f"
  end

  resource "rich" do
    url "https://files.pythonhosted.org/packages/b3/c6/f3b320c27991c46f43ee9d856302c70dc2d0fb2dba4842ff739d5f46b393/rich-14.3.3.tar.gz"
    sha256 "b8daa0b9e4eef54dd8cf7c86c03713f53241884e814f4e2f5fb342fe520f639b"
  end

  resource "shellingham" do
    url "https://files.pythonhosted.org/packages/58/15/8b3609fd3830ef7b27b655beb4b4e9c62313a4e8da8c676e142cc210d58e/shellingham-1.5.4.tar.gz"
    sha256 "8dbca0739d487e5bd35ab3ca4b36e11c4078f3a234bfce294b0a0291363404de"
  end

  resource "tree-sitter" do
    url "https://files.pythonhosted.org/packages/2e/39/8e3e89b1f0dae229e46a0e1973a95b62e76b9f6e05a788862a5064738514/tree-sitter-0.25.2.tar.gz"
    sha256 "fe43c158555da46723b28b52e058ad444195afd1db3ca7720c59a254544e9c20"
  end

  resource "tree-sitter-yaml" do
    url "https://files.pythonhosted.org/packages/05/8e/28c41cd1b84a1e77e18b7bb8db7e55f8bee0925bf878d40a4f8d6677e30c/tree_sitter_yaml-0.7.2.tar.gz"
    sha256 "756db4c09c9d9e97c81699e8f941cb8ce4e51104927f6090eefe638ee567d32c"
  end

  resource "textual" do
    url "https://files.pythonhosted.org/packages/f7/08/1e1f705825359590ddfaeda57653bd518c4ff7a96bb2c3239ba1b6fc4c51/textual-8.0.0.tar.gz"
    sha256 "ce48f83a3d686c0fac0e80bf9136e1f8851c653aa6a4502e43293a151df18809"
  end

  resource "textual-plotext" do
    url "https://files.pythonhosted.org/packages/9a/b0/e4e0f38df057db778252db0dd2c08522d7222b8537b6a0181d797b9044bd/textual_plotext-1.0.1.tar.gz"
    sha256 "836f53a3316756609e194129a35c2875638e7958c261f541e0a794f7c98011be"
  end

  resource "typer" do
    url "https://files.pythonhosted.org/packages/5a/b6/3e681d3b6bb22647509bdbfdd18055d5adc0dce5c5585359fa46ff805fdc/typer-0.24.0.tar.gz"
    sha256 "f9373dc4eff901350694f519f783c29b6d7a110fc0dcc11b1d7e353b85ca6504"
  end

  resource "typing-extensions" do
    url "https://files.pythonhosted.org/packages/72/94/1a15dd82efb362ac84269196e94cf00f187f7ed21c242792a923cdb1c61f/typing_extensions-4.15.0.tar.gz"
    sha256 "0cea48d173cc12fa28ecabc3b837ea3cf6f38c6d1136f85cbaaf598984861466"
  end

  resource "typing-inspection" do
    url "https://files.pythonhosted.org/packages/55/e3/70399cb7dd41c10ac53367ae42139cf4b1ca5f36bb3dc6c9d33acdb43655/typing_inspection-0.4.2.tar.gz"
    sha256 "ba561c48a67c5958007083d386c3295464928b01faa735ab8547c5692e87f464"
  end

  resource "uc-micro-py" do
    url "https://files.pythonhosted.org/packages/91/7a/146a99696aee0609e3712f2b44c6274566bc368dfe8375191278045186b8/uc-micro-py-1.0.3.tar.gz"
    sha256 "d321b92cff673ec58027c04015fcaa8bb1e005478643ff4a500882eaab88c48a"
  end

  def install
    venv = virtualenv_create(libexec, "python3.13")

    # Install pure-Python resources from sdist (skip native wheel resources)
    wheel_resources = %w[pydantic-core-arm pydantic-core-intel orjson ujson-arm ujson-intel claude-agent-sdk]
    sdist_resources = resources.reject { |r| wheel_resources.include?(r.name) }
    venv.pip_install sdist_resources
    venv.pip_install_and_link buildpath
  end

  def post_install
    pip = libexec/"bin/python"

    # Install native extensions from pre-built wheels after Homebrew's relocation step
    # to avoid dylib ID rewriting errors on .so extensions

    # pydantic-core (arch-specific)
    whl_resource = Hardware::CPU.arm? ? "pydantic-core-arm" : "pydantic-core-intel"
    resource(whl_resource).stage do
      whl = Dir["*.whl"].first
      system pip, "-m", "pip", "install", "--no-deps", "--no-compile", whl
    end

    # orjson (universal2 wheel covers both arm64 and x86_64)
    resource("orjson").stage do
      whl = Dir["*.whl"].first
      system pip, "-m", "pip", "install", "--no-deps", "--no-compile", whl
    end

    # ujson (arch-specific)
    ujson_resource = Hardware::CPU.arm? ? "ujson-arm" : "ujson-intel"
    resource(ujson_resource).stage do
      whl = Dir["*.whl"].first
      system pip, "-m", "pip", "install", "--no-deps", "--no-compile", whl
    end

    # claude-agent-sdk (ARM Mac only — no Intel Mac wheel is published for the SDK)
    # Transitive deps (anyio, mcp, httpx, etc.) are satisfied via --system-site-packages.
    if Hardware::CPU.arm?
      resource("claude-agent-sdk").stage do
        whl = Dir["*.whl"].first
        system pip, "-m", "pip", "install", "--no-deps", "--no-compile", whl
      end
    end
  end

  test do
    output = shell_output("#{bin}/kubeagle --version")
    assert_match "KubEagle", output
  end
end
