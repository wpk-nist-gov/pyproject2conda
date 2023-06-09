from pyproject2conda import parser
from textwrap import dedent


def test_match_p2c_comment():
    expected = "-c -d"
    for comment in [
        "#p2c: -c -d",
        "# p2c: -c -d",
        "  #p2c: -c -d",
        "# p2c: -c -d # some other thing",
        "# some other thing # p2c: -c -d # another thing",
    ]:
        match = parser._match_p2c_comment(comment)

        assert match == expected

    # check for skip
    for comment in [
        "##p2c: -c -d",
        "## p2c: -c -d",
        "  ##p2c: -c -d",
        "## p2c: -c -d # some other thing",
        "# some other thing ## p2c: -c -d # another thing",
    ]:
        match = parser._match_p2c_comment(comment)

        assert match is None


def test_parse_p2c():
    def get_expected(pip=False, skip=False, channel=None, package=None):
        if package is None:
            package = []
        return {
            "pip": pip,
            "skip": skip,
            "channel": channel,
            "package": package,
        }

    assert parser._parse_p2c("--pip") == get_expected(pip=True)
    assert parser._parse_p2c("-p") == get_expected(pip=True)

    assert parser._parse_p2c("--skip") == get_expected(skip=True)
    assert parser._parse_p2c("-s") == get_expected(skip=True)

    assert parser._parse_p2c("-s -c conda-forge") == get_expected(
        skip=True, channel="conda-forge"
    )

    assert parser._parse_p2c("athing>=0.3,<0.2 ") == get_expected(
        package=["athing>=0.3,<0.2"]
    )

    assert parser._parse_p2c("athing>=0.3,<0.2 bthing ") == get_expected(
        package=["athing>=0.3,<0.2", "bthing"]
    )

    assert parser._parse_p2c("'athing >= 0.3, <0.2' bthing ") == get_expected(
        package=["athing >= 0.3, <0.2", "bthing"]
    )


def test_complete():
    toml = dedent(
        """\
    [project]
    name = "hello"
    requires-python = ">=3.8,<3.11"
    dependencies = [
    "athing", # p2c: -p # a comment
    "bthing", # p2c: -s bthing-conda
    "cthing; python_version<'3.10'", # p2c: -c conda-forge
    ]

    [project.optional-dependencies]
    test = [
    "pandas",
    "pytest", # p2c: -c conda-forge
    ]
    dev-extras = [
    # p2c: -s additional-thing # this is an additional conda package
    "matplotlib", # p2c: -s conda-matplotlib
    ]
    dev = [
    "hello[test]",
    "hello[dev-extras]",
    ]
    dist-pypi = [
    "setuptools",
    "build", # p2c: -p
    ]


    [tool.pyproject2conda]
    channels = ['conda-forge']
    """
    )

    d = parser.PyProject2Conda.from_string(toml)

    expected = """\
channels:
  - conda-forge
dependencies:
  - bthing-conda
  - conda-forge::cthing
  - pip
  - pip:
      - athing
    """

    assert dedent(expected) == d.to_conda_yaml()

    # test -p option
    expected = """\
channels:
  - conda-forge
dependencies:
  - python>=3.8,<3.11
  - bthing-conda
  - conda-forge::cthing
  - pip
  - pip:
      - athing
    """
    assert dedent(expected) == d.to_conda_yaml(python_include="get")

    expected = """\
channels:
  - conda-forge
dependencies:
  - python=3.9
  - bthing-conda
  - conda-forge::cthing
  - pip
  - pip:
      - athing
    """
    assert dedent(expected) == d.to_conda_yaml(python_include="python=3.9")

    # test passing python_version
    expected = """\
channels:
  - conda-forge
dependencies:
  - python=3.10
  - bthing-conda
  - pip
  - pip:
      - athing
    """
    assert dedent(expected) == d.to_conda_yaml(
        python_include="python=3.10", python_version="3.10"
    )

    out = d.to_conda_yaml(channels="hello")

    expected = """\
channels:
  - hello
dependencies:
  - bthing-conda
  - conda-forge::cthing
  - pip
  - pip:
      - athing
    """

    assert dedent(expected) == out

    out = d.to_conda_yaml(extras="test")

    expected = """\
channels:
  - conda-forge
dependencies:
  - bthing-conda
  - conda-forge::cthing
  - pandas
  - conda-forge::pytest
  - pip
  - pip:
      - athing
    """

    assert dedent(expected) == out

    out = d.to_conda_yaml(extras="dist-pypi", include_base_dependencies=False)

    expected = """\
channels:
  - conda-forge
dependencies:
  - setuptools
  - pip
  - pip:
      - build
    """

    assert out == dedent(expected)

    expected = """\
channels:
  - conda-forge
dependencies:
  - bthing-conda
  - conda-forge::cthing
  - pandas
  - conda-forge::pytest
  - additional-thing
  - conda-matplotlib
  - pip
  - pip:
      - athing
    """

    assert dedent(expected) == d.to_conda_yaml("dev")
