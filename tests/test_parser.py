# mypy: disable-error-code="no-untyped-def, no-untyped-call"
from __future__ import annotations

import locale
import tempfile
from textwrap import dedent

import pytest

# from pyproject2conda import parser
from pyproject2conda import requirements
from pyproject2conda.utils import get_in


def test_get_in() -> None:
    d = {"a": {"b": {"c": 3}}}

    assert get_in(["a", "b", "c"], d) == 3

    assert get_in(["a", "d"], d, "hello") == "hello"


def test_list_to_string() -> None:
    from pyproject2conda.utils import list_to_str

    assert list_to_str(["a", "b"], eol=True) == "a\nb\n"
    assert list_to_str(["a", "b"], eol=False) == "a\nb"
    assert list_to_str(None) == ""  # noqa: PLC1901


def test_match_p2c_comment() -> None:
    from pyproject2conda.overrides import _match_p2c_comment

    expected = "-c -d"
    for comment in [
        "#p2c: -c -d",
        "# p2c: -c -d",
        "  #p2c: -c -d",
        "# p2c: -c -d # some other thing",
        "# some other thing # p2c: -c -d # another thing",
    ]:
        match = _match_p2c_comment(comment)

        assert match == expected

    # check for skip
    for comment in [
        "##p2c: -c -d",
        "## p2c: -c -d",
        "  ##p2c: -c -d",
        "## p2c: -c -d # some other thing",
        "# some other thing ## p2c: -c -d # another thing",
    ]:
        match = _match_p2c_comment(comment)

        assert match is None


def test_parse_p2c() -> None:
    def get_expected(pip=False, skip=False, channel=None, packages=None):
        if packages is None:
            packages = []
        return {
            "pip": pip,
            "skip": skip,
            "channel": channel,
            "packages": packages,
        }

    from pyproject2conda.overrides import _parse_p2c

    assert _parse_p2c(None) is None

    assert _parse_p2c("--pip") == get_expected(pip=True)
    assert _parse_p2c("-p") == get_expected(pip=True)

    assert _parse_p2c("--skip") == get_expected(skip=True)
    assert _parse_p2c("-s") == get_expected(skip=True)

    assert _parse_p2c("-s -c conda-forge") == get_expected(
        skip=True, channel="conda-forge"
    )

    assert _parse_p2c("athing>=0.3,<0.2 ") == get_expected(
        packages=["athing>=0.3,<0.2"]
    )

    assert _parse_p2c("athing>=0.3,<0.2 bthing ") == get_expected(
        packages=["athing>=0.3,<0.2", "bthing"]
    )

    assert _parse_p2c("'athing >= 0.3, <0.2' bthing ") == get_expected(
        packages=["athing >= 0.3, <0.2", "bthing"]
    )


# def test_value_comment_pairs():
#     d: list[tuple[str | None, str | None]] = [(None, "# p2c: --pip")]

#     with pytest.raises(ValueError):
#         out = parser.value_comment_pairs_to_conda(d)

#     d = [("hello", "# p2c: there")]

#     out = parser.value_comment_pairs_to_conda(d)

#     assert out["dependencies"] == ["hello", "there"]


def test_header() -> None:
    from pyproject2conda.requirements import _create_header

    expected = dedent(
        """\
#
# This file is autogenerated by pyproject2conda.
# You should not manually edit this file.
# Instead edit the corresponding pyproject.toml file.
#"""
    )

    assert expected == _create_header()

    cmd = "hello"
    out = _create_header(cmd=cmd)

    header = dedent(
        f"""\
#
# This file is autogenerated by pyproject2conda
# with the following command:
#
#     $ {cmd}
#
# You should not manually edit this file.
# Instead edit the corresponding pyproject.toml file.
#"""
    )

    assert out == header


# def test_yaml_to_str():
#     d = {"dep": ["a", "b"]}

#     s = parser._yaml_to_string(d, add_final_eol=False)

#     expected = """\
#     dep:
#       - a
#       - b"""

#     assert s == dedent(expected)

#     s = parser._yaml_to_string(d, add_final_eol=True)

#     expected = """\
#     dep:
#       - a
#       - b
#     """

#     assert s == dedent(expected)


def test_optional_write() -> None:
    from pathlib import Path

    from pyproject2conda.requirements import _optional_write

    s = "hello"
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "tmp.txt"

        _optional_write(s, p)

        with Path(p).open(encoding=locale.getpreferredencoding(False)) as f:
            test = f.read()

        assert test == s


def test_output_to_yaml() -> None:
    from pyproject2conda.requirements import _conda_yaml

    with pytest.raises(ValueError):
        s = _conda_yaml()

    s = _conda_yaml(
        conda_deps=["a", "pip"],
        channels=["conda-forge"],
        pip_deps=["pip-thing"],
        name="hello",
    )

    expected = """\
name: hello
channels:
  - conda-forge
dependencies:
  - a
  - pip
  - pip:
      - pip-thing
    """

    assert s == dedent(expected)


def test_infer() -> None:
    toml = dedent(
        """\
    [project]
    name = "hello"
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
    channels = 'conda-forge'
    """
    )

    d = requirements.ParseDepends.from_string(toml)
    with pytest.raises(ValueError):
        d.to_conda_yaml(python_include="infer")


def test_channels() -> None:
    toml = dedent(
        """\
    [project]
    name = "hello"
    """
    )

    d = requirements.ParseDepends.from_string(toml)

    assert d.channels == []

    toml = dedent(
        """\
    [project]
    name = "hello"

    [tool.pyproject2conda]
    channels = 'conda-forge'
    """
    )

    d = requirements.ParseDepends.from_string(toml)

    assert d.channels == ["conda-forge"]


def test_pip_requirements() -> None:
    toml = dedent(
        """\
    [project]
    requires-python = ">=3.8,<3.11"
    dependencies = [
    "athing", # p2c: -p # a comment
    "bthing", # p2c: -s bthing-conda
    "cthing; python_version<'3.10'", # p2c: -c conda-forge
    ]
        """
    )

    expected = dedent(
        """\
    athing
    bthing
    cthing;python_version<"3.10"
    hello
    """
    )

    d = requirements.ParseDepends.from_string(toml)

    assert d.to_requirements(pip_deps="hello") == expected


def test_bad_comment_pip() -> None:
    toml = dedent(
        """\
    [project]
    requires-python = ">=3.8,<3.11"
    dependencies = [
    # p2c: -p # a comment
    "bthing", # p2c: -s bthing-conda
    "cthing; python_version<'3.10'", # p2c: -c conda-forge
    ]
        """
    )

    d = requirements.ParseDepends.from_string(toml)

    with pytest.raises(TypeError):
        assert d.to_conda_yaml()


def test_bad_comment_conda() -> None:
    toml = dedent(
        """\
    [project]
    requires-python = ">=3.8,<3.11"
    dependencies = [
    "athing",
    # p2c: -c hello
    ]
        """
    )

    d = requirements.ParseDepends.from_string(toml)

    with pytest.raises(TypeError):
        assert d.to_conda_yaml()


def test_to_conda_requirements_error() -> None:
    toml = dedent(
        """\
    [project]
    requires-python = ">=3.8,<3.11"
    dependencies = [
    "athing", # p2c: -p # a comment
    "bthing", # p2c: -s bthing-conda
    "cthing; python_version<'3.10'", # p2c: -c conda-forge
    ]
        """
    )

    d = requirements.ParseDepends.from_string(toml)

    with pytest.raises(ValueError):
        d.to_conda_requirements(channels=["hello", "there"], prepend_channel=True)


def test_package_name() -> None:
    toml = dedent(
        """\
    [project]
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
    d = requirements.ParseDepends.from_string(toml)
    with pytest.raises(ValueError):
        d.conda_and_pip_requirements("dev")


def test_conda_and_pip_simple() -> None:
    toml = dedent(
        """\
    [project]
    name = "hello"
    dependencies = [
    "a",
    # thing
    "b",
    ]
        """
    )

    d = requirements.ParseDepends.from_string(toml)

    conda_deps, pip_deps = d.conda_and_pip_requirements()

    assert conda_deps == ["a", "b"]

    assert pip_deps == []


@pytest.mark.parametrize(
    "toml",
    [
        # comment syntax
        dedent(
            """\
            [build-system]
            requires = ["setuptools>=61.2", "setuptools_scm[toml]>=8.0"]
            build-backend = "setuptools.build_meta"

            [project]
            name = "hello"
            requires-python = ">=3.8, <3.11"
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
        ),
        # Table syntax
        dedent(
            """\
            [build-system]
            requires = ["setuptools>=61.2", "setuptools_scm[toml]>=8.0"]
            build-backend = "setuptools.build_meta"

            [project]
            name = "hello"
            requires-python = ">=3.8, <3.11"
            dependencies = [
            "athing",
            "bthing",
            "cthing; python_version<'3.10'",
            ]

            [project.optional-dependencies]
            test = [
            "pandas",
            "pytest",
            ]
            dev-extras = [
            "matplotlib",
            ]
            dev = [
            "hello[test]",
            "hello[dev-extras]",
            ]
            dist-pypi = [
            "setuptools",
            "build",
            ]


            [tool.pyproject2conda]
            channels = ['conda-forge']

            [tool.pyproject2conda.dependencies]
            athing = {pip = true}
            bthing = {skip = true, packages = "bthing-conda"}
            cthing = {channel = "conda-forge"}
            pytest = {channel = "conda-forge"}
            matplotlib = {skip = true, packages = ["additional-thing", "conda-matplotlib"]}
            build = { channel = "pip" }
            """
        ),
    ],
)
def test_complete(toml) -> None:
    d = requirements.ParseDepends.from_string(toml)

    # test unknown extra
    with pytest.raises(ValueError):
        d.to_conda_yaml(extras="a-thing")

    # test list:
    assert d.extras == [
        "test",
        "dev-extras",
        "dev",
        "dist-pypi",
        "build-system.requires",
    ]

    # test build-system.requires
    expected = """\
    setuptools>=61.2
    setuptools_scm[toml]>=8.0
    """
    assert dedent(expected) == d.to_requirements(
        extras="build-system.requires", include_base=False
    )

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
    assert dedent(expected) == d.to_conda_yaml(python_include="infer")

    # with remove spaces:
    expected = """\
channels:
  - conda-forge
dependencies:
  - python>=3.8, <3.11
  - bthing-conda
  - conda-forge::cthing
  - pip
  - pip:
      - athing
    """
    assert dedent(expected) == d.to_conda_yaml(
        python_include="infer", remove_whitespace=False
    )

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

    out = d.to_conda_yaml(extras="test", sort=False)

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

    out = d.to_conda_yaml(extras="test", sort=True)

    expected = """\
channels:
  - conda-forge
dependencies:
  - bthing-conda
  - conda-forge::cthing
  - conda-forge::pytest
  - pandas
  - pip
  - pip:
      - athing
    """

    assert dedent(expected) == out

    out = d.to_conda_yaml(extras="dist-pypi", include_base=False)

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

    assert dedent(expected) == d.to_conda_yaml("dev", sort=False)

    expected = """\
channels:
  - conda-forge
dependencies:
  - additional-thing
  - bthing-conda
  - conda-forge::cthing
  - conda-forge::pytest
  - conda-matplotlib
  - pandas
  - pip
  - pip:
      - athing
    """

    assert dedent(expected) == d.to_conda_yaml("dev")

    # Test deps/reqs
    expected = """\
channels:
  - conda-forge
dependencies:
  - bthing-conda
  - conda-forge::cthing
  - dep
  - pip
  - pip:
      - athing
      - req
    """

    assert dedent(expected) == d.to_conda_yaml(
        conda_deps="dep;python_version<'3.10'", pip_deps=["req"]
    )

    expected = """\
channels:
  - conda-forge
dependencies:
  - python=3.10
  - bthing-conda
  - pip
  - pip:
      - athing
      - req;python_version<"3.10"
    """
    assert dedent(expected) == d.to_conda_yaml(
        conda_deps=["dep;python_version<'3.10'"],
        pip_deps=["req;python_version<'3.10'"],
        python_include="python=3.10",
        python_version="3.10",
    )


def test_missing_dependencies() -> None:
    toml = dedent(
        """\
    [project]
    name = "hello"
    requires-python = ">=3.8,<3.11"
    dependencies = []

    [project.optional-dependencies]
    test = [
    "pandas",
    "pytest", # p2c: -c conda-forge
    "pytest-accept", # p2c: -p
    ]
    dev-extras = [
    # p2c: -s additional-thing # this is an additional conda package
    "matplotlib", # p2c: -s conda-matplotlib
    ]
    dev = [
    "hello[test]",
    "hello[dev-extras]",
    ]

    [tool.pyproject2conda]
    channels = ['conda-forge']
    """
    )

    d = requirements.ParseDepends.from_string(toml)

    expected = """\
channels:
  - conda-forge
dependencies:
  - conda-forge::pytest
  - pandas
  - pip
  - pip:
      - pytest-accept
    """

    assert dedent(expected) == d.to_conda_yaml(
        extras="test",
        include_base=False,
    )

    toml = dedent(
        """\
    [project]
    name = "hello"
    requires-python = ">=3.8,<3.11"

    [project.optional-dependencies]
    test = [
    "pandas",
    "pytest", # p2c: -c conda-forge
    "pytest-accept", # p2c: -p
    ]
    dev-extras = [
    # p2c: -s additional-thing # this is an additional conda package
    "matplotlib", # p2c: -s conda-matplotlib
    ]
    dev = [
    "hello[test]",
    "hello[dev-extras]",
    ]

    [tool.pyproject2conda]
    channels = ['conda-forge']
    """
    )

    d = requirements.ParseDepends.from_string(toml)

    assert dedent(expected) == d.to_conda_yaml(
        extras="test",
        include_base=False,
    )

    assert dedent(expected) == d.to_conda_yaml(
        extras="test",
        include_base=True,
    )

    # check output has no dependencies:
    for attr in ["to_conda_yaml", "to_requirements"]:
        f = getattr(d, attr)
        with pytest.raises(ValueError):
            f()

        assert f(allow_empty=True) == "No dependencies for this environment\n"


def test_clean_conda() -> None:
    toml = dedent(
        """\
    [project]
    name = "hello"
    requires-python = ">=3.8,<3.11"

    [project.optional-dependencies]
    test = [
    "pandas",
    "pytest", # p2c: -c conda-forge
    "pytest-accept", # p2c: -p
    ]
    dev-extras = [
    # p2c: -s additional-thing # this is an additional conda package
    "matplotlib", # p2c: -s conda-forge::conda-matplotlib
    ]
    dev = [
    "hello[test]",
    "hello[dev-extras]",
    ]

    [tool.pyproject2conda]
    channels = ['conda-forge']
    """
    )

    expected = """\
channels:
  - conda-forge
dependencies:
  - additional-thing
  - conda-forge::conda-matplotlib
    """

    d = requirements.ParseDepends.from_string(toml)

    assert dedent(expected) == d.to_conda_yaml(
        extras="dev-extras",
        include_base=False,
    )


def test_no_optional_deps() -> None:
    toml = dedent(
        """\
    [project]
    name = "hello"
    requires-python = ">=3.8,<3.11"
    dependencies = [
    "athing >0.5", # p2c: -p # a comment
    "bthing > 1.0", # p2c: -s 'bthing-conda > 2.0'
    "cthing; python_version < '3.10'", # p2c: -c conda-forge
    ]

    [tool.pyproject2conda]
    channels = ['conda-forge']
    """
    )

    expected = """\
channels:
  - conda-forge
dependencies:
  - python>=3.8,<3.11
  - bthing-conda>2.0
  - conda-forge::cthing
  - pip
  - pip:
      - athing>0.5
    """

    d = requirements.ParseDepends.from_string(toml)

    assert d.optional_dependencies == {}

    assert dedent(expected) == d.to_conda_yaml(python_include="infer")


@pytest.mark.parametrize(
    "toml",
    [
        dedent(
            """\
            [project]
            name = "hello"
            requires-python = ">=3.8, <3.11"
            dependencies = [
            "athing >0.5", # p2c: -p # a comment
            "bthing > 1.0", # p2c: -s 'bthing-conda > 2.0'
            "cthing; python_version < '3.10'", # p2c: -c conda-forge
            ]


            [tool.pyproject2conda]
            channels = ['conda-forge']
            """
        ),
        dedent(
            """\
            [project]
            name = "hello"
            requires-python = ">=3.8, <3.11"
            dependencies = [
            "athing >0.5", # p2c: -p
            "bthing > 1.0",
            "cthing; python_version < '3.10'",
            ]


            [tool.pyproject2conda]
            channels = ['conda-forge']

            [tool.pyproject2conda.dependencies]
            # this will be ignored, since have option above
            athing = {channel = "conda-forge"}
            bthing = {skip = true, packages = "bthing-conda > 2.0"}
            cthing = {channel = "conda-forge"}
            """
        ),
    ],
)
def test_spaces(toml) -> None:
    d = requirements.ParseDepends.from_string(toml)

    expected = """\
channels:
  - conda-forge
dependencies:
  - python>=3.8, <3.11
  - bthing-conda>2.0
  - conda-forge::cthing
  - pip
  - pip:
      - athing>0.5
    """
    assert dedent(expected) == d.to_conda_yaml(
        python_include="infer", remove_whitespace=False
    )

    expected = """\
channels:
  - conda-forge
dependencies:
  - python>=3.8,<3.11
  - bthing-conda>2.0
  - conda-forge::cthing
  - pip
  - pip:
      - athing>0.5
    """
    assert dedent(expected) == d.to_conda_yaml(
        python_include="infer", remove_whitespace=True
    )

    expected = """\
    athing>0.5
    bthing>1.0
    cthing; python_version < "3.10"
    """

    assert dedent(expected) == d.to_requirements(remove_whitespace=False)

    expected = """\
    athing>0.5
    bthing>1.0
    cthing;python_version<"3.10"
    """

    assert dedent(expected) == d.to_requirements(remove_whitespace=True)


def test_include_pip() -> None:
    toml = dedent(
        """\
        [build-system]
        requires = ["setuptools>=61.2", "setuptools_scm[toml]>=8.0"]
        build-backend = "setuptools.build_meta"

        [project]
        name = "hello"
        requires-python = ">=3.8, <3.11"
        dependencies = [
        "athing",
        ]

        [project.optional-dependencies]
        test = [
        "xthing",
        ]
        """
    )

    expected = """\
    dependencies:
      - athing
      - xthing
      - pip
    """

    d = requirements.ParseDepends.from_string(toml)

    assert dedent(expected) == d.to_conda_yaml(extras="test", conda_deps="pip")
