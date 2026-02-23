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

  # tree-sitter core (arch-specific C extension)
  resource "tree-sitter-arm" do
    url "https://files.pythonhosted.org/packages/4e/9c/a278b15e6b263e86c5e301c82a60923fa7c59d44f78d7a110a89a413e640/tree_sitter-0.25.2-cp313-cp313-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "f5ddcd3e291a749b62521f71fc953f66f5fd9743973fd6dd962b092773569601"
  end

  resource "tree-sitter-intel" do
    url "https://files.pythonhosted.org/packages/8c/67/67492014ce32729b63d7ef318a19f9cfedd855d677de5773476caf771e96/tree_sitter-0.25.2-cp313-cp313-macosx_10_13_x86_64.whl", using: :nounzip
    sha256 "0628671f0de69bb279558ef6b640bcfc97864fe0026d840f872728a86cd6b6cd"
  end

  # tree-sitter language grammars — required by textual[syntax] for TextArea highlighting
  resource "tree-sitter-bash-arm" do
    url "https://files.pythonhosted.org/packages/23/bb/2d2cfbb1f89aaeb1ec892624f069d92d058d06bb66f16b9ec9fb5873ab60/tree_sitter_bash-0.25.1-cp310-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "f4a34a6504c7c5b2a9b8c5c4065531dea19ca2c35026e706cf2eeeebe2c92512"
  end

  resource "tree-sitter-bash-intel" do
    url "https://files.pythonhosted.org/packages/30/8e/37e7364d9c9c58da89e05c510671d8c45818afd7b31c6939ab72f8dc6c04/tree_sitter_bash-0.25.1-cp310-abi3-macosx_10_9_x86_64.whl", using: :nounzip
    sha256 "0e6235f59e366d220dde7d830196bed597d01e853e44d8ccd1a82c5dd2500acf"
  end

  resource "tree-sitter-css-arm" do
    url "https://files.pythonhosted.org/packages/4d/28/ebcbcbba812d3e407f2f393747330eb8843e0c69d159024e33460b622aab/tree_sitter_css-0.25.0-cp310-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "5a2a9c875037ef5f9da57697fb8075086476d42a49d25a88dcca60dfc09bd092"
  end

  resource "tree-sitter-css-intel" do
    url "https://files.pythonhosted.org/packages/25/a9/69e556f15ca774638bd79005369213dfbd41995bf032ce81cf3ffe086b8a/tree_sitter_css-0.25.0-cp310-abi3-macosx_10_9_x86_64.whl", using: :nounzip
    sha256 "ddce6f84eeb0bb2877b4587b07bffb0753040c44d811ed9ab2af978c313beda8"
  end

  resource "tree-sitter-go-arm" do
    url "https://files.pythonhosted.org/packages/32/16/dd4cb124b35e99239ab3624225da07d4cb8da4d8564ed81d03fcb3a6ba9f/tree_sitter_go-0.25.0-cp310-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "503b81a2b4c31e302869a1de3a352ad0912ccab3df9ac9950197b0a9ceeabd8f"
  end

  resource "tree-sitter-go-intel" do
    url "https://files.pythonhosted.org/packages/ca/aa/0984707acc2b9bb461fe4a41e7e0fc5b2b1e245c32820f0c83b3c602957c/tree_sitter_go-0.25.0-cp310-abi3-macosx_10_9_x86_64.whl", using: :nounzip
    sha256 "b852993063a3429a443e7bd0aa376dd7dd329d595819fabf56ac4cf9d7257b54"
  end

  resource "tree-sitter-html-arm" do
    url "https://files.pythonhosted.org/packages/bd/17/827c315deb156bb8cac541da800c4bd62878f50a28b7498fbb722bddd225/tree_sitter_html-0.23.2-cp39-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "3d0a83dd6cd1c7d4bcf6287b5145c92140f0194f8516f329ae8b9e952fbfa8ff"
  end

  resource "tree-sitter-html-intel" do
    url "https://files.pythonhosted.org/packages/fb/27/b846852b567601c4df765bcb4636085a3260e9f03ae21e0ef2e7c7f957fc/tree_sitter_html-0.23.2-cp39-abi3-macosx_10_9_x86_64.whl", using: :nounzip
    sha256 "9e1641d5edf5568a246c6c47b947ed524b5bf944664e6473b21d4ae568e28ee9"
  end

  resource "tree-sitter-java-arm" do
    url "https://files.pythonhosted.org/packages/57/ef/6406b444e2a93bc72a04e802f4107e9ecf04b8de4a5528830726d210599c/tree_sitter_java-0.23.5-cp39-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "24acd59c4720dedad80d548fe4237e43ef2b7a4e94c8549b0ca6e4c4d7bf6e69"
  end

  resource "tree-sitter-java-intel" do
    url "https://files.pythonhosted.org/packages/67/21/b3399780b440e1567a11d384d0ebb1aea9b642d0d98becf30fa55c0e3a3b/tree_sitter_java-0.23.5-cp39-abi3-macosx_10_9_x86_64.whl", using: :nounzip
    sha256 "355ce0308672d6f7013ec913dee4a0613666f4cda9044a7824240d17f38209df"
  end

  resource "tree-sitter-javascript-arm" do
    url "https://files.pythonhosted.org/packages/b1/8f/6b4b2bc90d8ab3955856ce852cc9d1e82c81d7ab9646385f0e75ffd5b5d3/tree_sitter_javascript-0.25.0-cp310-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "8264a996b8845cfce06965152a013b5d9cbb7d199bc3503e12b5682e62bb1de1"
  end

  resource "tree-sitter-javascript-intel" do
    url "https://files.pythonhosted.org/packages/2c/df/5106ac250cd03661ebc3cc75da6b3d9f6800a3606393a0122eca58038104/tree_sitter_javascript-0.25.0-cp310-abi3-macosx_10_9_x86_64.whl", using: :nounzip
    sha256 "b70f887fb269d6e58c349d683f59fa647140c410cfe2bee44a883b20ec92e3dc"
  end

  resource "tree-sitter-json-arm" do
    url "https://files.pythonhosted.org/packages/5c/31/102c15948d97b135611d6a995c97a3933c0e9745f25737723977f58e142c/tree_sitter_json-0.24.8-cp39-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "62b4c45b561db31436a81a3f037f71ec29049f4fc9bf5269b6ec3ebaaa35a1cd"
  end

  resource "tree-sitter-json-intel" do
    url "https://files.pythonhosted.org/packages/42/41/84866232980fb3cf0cff46f5af2dbb9bfa3324b32614c6a9af3d08926b72/tree_sitter_json-0.24.8-cp39-abi3-macosx_10_9_x86_64.whl", using: :nounzip
    sha256 "59ac06c6db1877d0e2076bce54a5fddcdd2fc38ca778905662e80fa9ffcea2ab"
  end

  resource "tree-sitter-markdown-arm" do
    url "https://files.pythonhosted.org/packages/6d/9b/65eb5e6a8d7791174644854437d35849d9b4e4ed034d54d2c78810eaf1a6/tree_sitter_markdown-0.5.1-cp39-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "1ec4cc5d7b0d188bad22247501ab13663bb1bf1a60c2c020a22877fabce8daa9"
  end

  resource "tree-sitter-markdown-intel" do
    url "https://files.pythonhosted.org/packages/77/73/b5f88217a526f61080ddd71d554cff6a01ea23fffa584ad9de41ee8d1fe5/tree_sitter_markdown-0.5.1-cp39-abi3-macosx_10_9_x86_64.whl", using: :nounzip
    sha256 "f00ce3f48f127377983859fcb93caf0693cbc7970f8c41f1e2bd21e4d56bdfd8"
  end

  resource "tree-sitter-python-arm" do
    url "https://files.pythonhosted.org/packages/e6/1d/60d8c2a0cc63d6ec4ba4e99ce61b802d2e39ef9db799bdf2a8f932a6cd4b/tree_sitter_python-0.25.0-cp310-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "480c21dbd995b7fe44813e741d71fed10ba695e7caab627fb034e3828469d762"
  end

  resource "tree-sitter-python-intel" do
    url "https://files.pythonhosted.org/packages/cf/64/a4e503c78a4eb3ac46d8e72a29c1b1237fa85238d8e972b063e0751f5a94/tree_sitter_python-0.25.0-cp310-abi3-macosx_10_9_x86_64.whl", using: :nounzip
    sha256 "14a79a47ddef72f987d5a2c122d148a812169d7484ff5c75a3db9609d419f361"
  end

  resource "tree-sitter-regex-arm" do
    url "https://files.pythonhosted.org/packages/71/06/6b4f995f61952572a94bcfce12d43fc580226551fab9dd0aac4e94465f38/tree_sitter_regex-0.25.0-cp310-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "df5713649b89c5758649398053c306c41565f22a6f267cb5ec25596504bcf012"
  end

  resource "tree-sitter-regex-intel" do
    url "https://files.pythonhosted.org/packages/2b/b4/12e9ba02bab4ce13d1875f6585c3f2a5816233104d1507ea118950a4f7eb/tree_sitter_regex-0.25.0-cp310-abi3-macosx_10_9_x86_64.whl", using: :nounzip
    sha256 "3fa11bbd76b29ac8ca2dbf85ad082f9b18ae6352251d805eb2d4191e1706a9d5"
  end

  resource "tree-sitter-rust-arm" do
    url "https://files.pythonhosted.org/packages/bf/00/4c400fe94eb3cb141b008b489d582dcd8b41e4168aca5dd8746c47a2b1bc/tree_sitter_rust-0.24.0-cp39-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "a0a1a2694117a0e86e156b28ee7def810ec94e52402069bf805be22d43e3c1a1"
  end

  resource "tree-sitter-rust-intel" do
    url "https://files.pythonhosted.org/packages/3c/29/0594a6b135d2475d1bb8478029dad127b87856eeb13b23ce55984dd22bb4/tree_sitter_rust-0.24.0-cp39-abi3-macosx_10_9_x86_64.whl", using: :nounzip
    sha256 "7ea455443f5ab245afd8c5ce63a8ae38da455ef27437b459ce3618a9d4ec4f9a"
  end

  resource "tree-sitter-sql-arm" do
    url "https://files.pythonhosted.org/packages/05/45/b2bd5f9919ea15c4ae90a156999101ebd4caa4036babe54efaf9d3e77d55/tree_sitter_sql-0.3.11-cp310-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "a33cd6880ab2debef036f80365c32becb740ec79946805598488732b6c515fff"
  end

  resource "tree-sitter-sql-intel" do
    url "https://files.pythonhosted.org/packages/32/68/bb80073915dfe1b38935451bc0d65528666c126b2d5878e7140ef9bf9f8a/tree_sitter_sql-0.3.11-cp310-abi3-macosx_10_9_x86_64.whl", using: :nounzip
    sha256 "cf1b0c401756940bf47544ad7c4cc97373fc0dac118f821820953e7015a115e3"
  end

  resource "tree-sitter-toml-arm" do
    url "https://files.pythonhosted.org/packages/92/20/ac8a20805339105fe0bbb6beaa99dbbd1159647760ddd786142364e0b7f2/tree_sitter_toml-0.7.0-cp39-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "18be09538e9775cddc0290392c4e2739de2201260af361473ca60b5c21f7bd22"
  end

  resource "tree-sitter-toml-intel" do
    url "https://files.pythonhosted.org/packages/ad/4d/1e00a5cd8dba09e340b25aa60a3eaeae584ff5bc5d93b0777169d6741ee5/tree_sitter_toml-0.7.0-cp39-abi3-macosx_10_9_x86_64.whl", using: :nounzip
    sha256 "b9ae5c3e7c5b6bb05299dd73452ceafa7fa0687d5af3012332afa7757653b676"
  end

  resource "tree-sitter-xml-arm" do
    url "https://files.pythonhosted.org/packages/75/f5/31013d04c4e3b9a55e90168cc222a601c84235ba4953a5a06b5cdf8353c4/tree_sitter_xml-0.7.0-cp39-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "0674fdf4cc386e4d323cb287d3b072663de0f20a9e9af5d5e09821aae56a9e5c"
  end

  resource "tree-sitter-xml-intel" do
    url "https://files.pythonhosted.org/packages/36/1d/6b8974c493973c0c9df2bbf220a1f0a96fa785da81a5a13461faafd1441c/tree_sitter_xml-0.7.0-cp39-abi3-macosx_10_9_x86_64.whl", using: :nounzip
    sha256 "cc3e516d4c1e0860fb22172c172148debb825ba638971bc48bad15b22e5b0bae"
  end

  resource "tree-sitter-yaml-arm" do
    url "https://files.pythonhosted.org/packages/18/0d/15a5add06b3932b5e4ce5f5e8e179197097decfe82a0ef000952c8b98216/tree_sitter_yaml-0.7.2-cp310-abi3-macosx_11_0_arm64.whl", using: :nounzip
    sha256 "0807b7966e23ddf7dddc4545216e28b5a58cdadedcecca86b8d8c74271a07870"
  end

  resource "tree-sitter-yaml-intel" do
    url "https://files.pythonhosted.org/packages/38/29/c0b8dbff302c49ff4284666ffb6f2f21145006843bb4c3a9a85d0ec0b7ae/tree_sitter_yaml-0.7.2-cp310-abi3-macosx_10_9_x86_64.whl", using: :nounzip
    sha256 "7e269ddcfcab8edb14fbb1f1d34eed1e1e26888f78f94eedfe7cc98c60f8bc9f"
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
    wheel_resources = %w[
      pydantic-core-arm pydantic-core-intel orjson ujson-arm ujson-intel claude-agent-sdk
      tree-sitter-arm tree-sitter-intel
      tree-sitter-bash-arm tree-sitter-bash-intel
      tree-sitter-css-arm tree-sitter-css-intel
      tree-sitter-go-arm tree-sitter-go-intel
      tree-sitter-html-arm tree-sitter-html-intel
      tree-sitter-java-arm tree-sitter-java-intel
      tree-sitter-javascript-arm tree-sitter-javascript-intel
      tree-sitter-json-arm tree-sitter-json-intel
      tree-sitter-markdown-arm tree-sitter-markdown-intel
      tree-sitter-python-arm tree-sitter-python-intel
      tree-sitter-regex-arm tree-sitter-regex-intel
      tree-sitter-rust-arm tree-sitter-rust-intel
      tree-sitter-sql-arm tree-sitter-sql-intel
      tree-sitter-toml-arm tree-sitter-toml-intel
      tree-sitter-xml-arm tree-sitter-xml-intel
      tree-sitter-yaml-arm tree-sitter-yaml-intel
    ]
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

    # tree-sitter core (arch-specific — C extension for syntax highlighting)
    ts_resource = Hardware::CPU.arm? ? "tree-sitter-arm" : "tree-sitter-intel"
    resource(ts_resource).stage do
      whl = Dir["*.whl"].first
      system pip, "-m", "pip", "install", "--no-deps", "--no-compile", whl
    end

    # tree-sitter language grammars — required by textual[syntax] for TextArea highlighting.
    # Textual does NOT bundle grammar .so files; it imports individual tree_sitter_<lang>
    # packages at runtime via importlib.import_module().
    ts_lang_packages = %w[bash css go html java javascript json markdown python regex rust sql toml xml yaml]
    ts_lang_packages.each do |lang|
      res_name = Hardware::CPU.arm? ? "tree-sitter-#{lang}-arm" : "tree-sitter-#{lang}-intel"
      resource(res_name).stage do
        whl = Dir["*.whl"].first
        system pip, "-m", "pip", "install", "--no-deps", "--no-compile", whl
      end
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
