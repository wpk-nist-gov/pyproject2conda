"""
Parsing (:mod:`pyproject2conda.parser`)
=======================================

Main parser to turn pyproject.toml -> environment.yaml
"""
from __future__ import annotations

import argparse
import re
import shlex
from functools import lru_cache
from pathlib import Path
from typing import Any, Generator, Mapping, Optional, Sequence, TypeVar, Union, cast

import tomlkit
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from ruamel.yaml import YAML

# -- typing ----------------------------------------------------------------------------

Tstr_opt = Optional[str]
Tstr_seq_opt = Optional[Union[str, Sequence[str]]]


# --- Default parser -------------------------------------------------------------------


@lru_cache
def _default_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parser searches for comments '# p2c: [OPTIONS]"
    )

    parser.add_argument(
        "-c",
        "--channel",
        type=str,
        help="Channel to add to the pyproject requirement",
    )
    parser.add_argument(
        "-p",
        "--pip",
        action="store_true",
        help="If specified, install dependency on pyproject dependency (on this line) with pip",
    )
    parser.add_argument(
        "-s",
        "--skip",
        action="store_true",
        help="If specified skip pyproject dependency on this line",
    )

    parser.add_argument("package", nargs="*")

    return parser


# taken from https://github.com/conda/conda-lock/blob/main/conda_lock/common.py
def get_in(
    keys: Sequence[Any], nested_dict: Mapping[Any, Any], default: Any = None
) -> Any:
    """
    >>> foo = {'a': {'b': {'c': 1}}}
    >>> get_in(['a', 'b'], foo)
    {'c': 1}

    """
    import operator
    from functools import reduce

    try:
        return reduce(operator.getitem, keys, nested_dict)
    except (KeyError, IndexError, TypeError):
        return default


def _unique_list(values):
    """
    Return only unique values in list.
    Unlike using set(values), this preserves order.
    """
    output = []
    for v in values:
        if v not in output:
            output.append(v)
    return output


def _list_to_str(values, eol=True):
    if values:
        output = "\n".join(values)
        if eol:
            output += "\n"
    else:
        output = ""

    return output


def _iter_value_comment_pairs(
    array: tomlkit.items.Array,
) -> Generator[tuple[Tstr_opt, Tstr_opt], None, None]:
    """Extract value and comments from array"""
    for v in array._value:
        if v.value is not None and not isinstance(v.value, tomlkit.items.Null):
            value = str(v.value)  # .as_string()
        else:
            value = None
        if v.comment:
            comment = v.comment.as_string()
        else:
            comment = None
        if value is None and comment is None:
            continue
        yield (value, comment)


def _matches_package_name(
    dep: Tstr_opt,
    package_name: str,
) -> list[str] | None:
    """
    Check if `dep` matches pattern {package_name}[extra,..]

    If it does, return extras, else return None
    """

    if not dep:
        return None

    pattern = rf"{package_name}\[(.*?)\]"
    match = re.match(pattern, dep)

    if match:
        extras = match.group(1).split(",")
    else:
        extras = None
    return extras


def get_value_comment_pairs(
    package_name: str,
    deps: tomlkit.items.Array,
    extras: Tstr_seq_opt = None,
    opts: tomlkit.items.Table | None = None,
    include_base_dependencies: bool = True,
) -> list[tuple[Tstr_opt, Tstr_opt]]:
    """Recursively build dependency, comment pairs from deps and extras."""
    if include_base_dependencies:
        out = list(_iter_value_comment_pairs(deps))
    else:
        out = []

    if extras is None:
        return out
    else:
        assert opts is not None

    if isinstance(extras, str):
        extras = [extras]

    for extra in extras:
        for value, comment in _iter_value_comment_pairs(
            cast(tomlkit.items.Array, opts[extra])
        ):
            if new_extras := _matches_package_name(value, package_name):
                out.extend(
                    get_value_comment_pairs(
                        package_name=package_name,
                        extras=new_extras,
                        deps=deps,
                        opts=opts,
                        include_base_dependencies=False,
                    )
                )
            else:
                out.append((value, comment))

    return out


def _pyproject_to_value_comment_pairs(
    data: tomlkit.toml_document.TOMLDocument,
    extras: Tstr_seq_opt = None,
    unique: bool = True,
    include_base_dependencies: bool = True,
):
    package_name = cast(str, get_in(["project", "name"], data))

    deps = cast(tomlkit.items.Array, get_in(["project", "dependencies"], data))

    value_comment_list = get_value_comment_pairs(
        package_name=package_name,
        extras=extras,
        deps=deps,
        opts=get_in(["project", "optional-dependencies"], data),
        include_base_dependencies=include_base_dependencies,
    )

    if unique:
        value_comment_list = _unique_list(value_comment_list)

    return value_comment_list


def _match_p2c_comment(comment: Tstr_opt) -> Tstr_opt:
    if not comment or not (match := re.match(r".*?#\s*p2c:\s*([^\#]*)", comment)):
        return None
    elif re.match(r".*?##\s*p2c:", comment):
        # This checks for double ##.  If found, ignore line
        return None
    else:
        return match.group(1).strip()


def _parse_p2c(match: Tstr_opt) -> dict[str, Any] | None:
    """Parse match from _match_p2c_comment"""

    if match:
        return vars(_default_parser().parse_args(shlex.split(match)))
    else:
        return None


def parse_p2c_comment(comment: Tstr_opt) -> dict[str, Any] | None:
    if match := _match_p2c_comment(comment):
        return _parse_p2c(match)
    else:
        return None


def _limit_deps_by_python_version(
    deps: list[str], python_version: Tstr_opt = None
) -> list[str]:
    if python_version:
        version = Version(python_version)
    else:
        version = None

    matcher = re.compile(
        r"(?P<dep>.*?);\s*python_version\s*(?P<token>[<=>~]*)\s*[\'|\"](?P<version>.*?)[\'|\"]"
    )

    output = []
    for dep in deps:
        if match := matcher.match(dep):
            if not version or version in SpecifierSet(
                match["token"] + match["version"]
            ):
                output.append(match["dep"])
        else:
            output.append(dep)
    return output


def value_comment_pairs_to_conda(
    value_comment_list: list[tuple[Tstr_opt, Tstr_opt]],
) -> dict[str, Any]:
    """Convert raw value/comment pairs to install lines"""

    conda_deps: list[Tstr_opt] = []
    pip_deps: list[Tstr_opt] = []

    def _check_value(value):
        if not value:
            raise ValueError("trying to add value that does not exist")

    for value, comment in value_comment_list:
        if comment and (parsed := parse_p2c_comment(comment)):
            if parsed["pip"]:
                _check_value(value)
                pip_deps.append(value)
            elif not parsed["skip"]:
                _check_value(value)

                if parsed["channel"]:
                    conda_deps.append("{}::{}".format(parsed["channel"], value))
                else:
                    conda_deps.append(value)

            conda_deps.extend(parsed["package"])
        elif value:
            conda_deps.append(value)

    return {"dependencies": conda_deps, "pip": pip_deps}


def pyproject_to_conda_lists(
    data: tomlkit.toml_document.TOMLDocument,
    extras: Tstr_seq_opt = None,
    channels: Tstr_seq_opt = None,
    python_include: Tstr_opt = None,
    python_version: Tstr_opt = None,
    include_base_dependencies: bool = True,
) -> dict[str, Any]:
    if python_include == "get":
        python_include = (
            "python" + get_in(["project", "requires-python"], data).unwrap()
        )

    if channels is None:
        channels_doc = get_in(["tool", "pyproject2conda", "channels"], data, None)
        if channels_doc:
            channels = channels_doc.unwrap()
    if isinstance(channels, str):
        channels = [channels]

    value_comment_list = _pyproject_to_value_comment_pairs(
        data=data,
        extras=extras,
        include_base_dependencies=include_base_dependencies,
    )

    output = value_comment_pairs_to_conda(
        value_comment_list,
    )

    if python_include:
        output["dependencies"].insert(0, python_include)
    if channels:
        output["channels"] = channels

    # limit python version/remove python_verions <=> part
    output["dependencies"] = _limit_deps_by_python_version(
        output["dependencies"], python_version
    )

    return output


def pyproject_to_conda(
    data: tomlkit.toml_document.TOMLDocument,
    extras: Tstr_seq_opt = None,
    channels: Tstr_seq_opt = None,
    name: Tstr_opt = None,
    python_include: Tstr_opt = None,
    stream: str | Path | None = None,
    python_version: Tstr_opt = None,
    include_base_dependencies: bool = True,
    header_cmd: Tstr_opt = None,
):
    output = pyproject_to_conda_lists(
        data=data,
        extras=extras,
        channels=channels,
        python_include=python_include,
        python_version=python_version,
        include_base_dependencies=include_base_dependencies,
    )
    return _output_to_yaml(**output, name=name, stream=stream, header_cmd=header_cmd)


def _create_header(cmd=None):
    from textwrap import dedent

    if cmd:
        header = dedent(
            f"""
        This file is autogenerated by pyproject2conda
        with the following command:

            $ {cmd}

        You should not manually edit this file.
        Instead edit the corresponding pyproject.toml file.
        """
        )
    else:
        header = dedent(
            """
        This file is autogenerated by pyrpoject2conda.
        You should not manually edit this file.
        Instead edit the corresponding pyproject.toml file.
        """
        )

    # prepend '# '
    lines = []
    for line in header.split("\n"):
        if len(line.strip()) == 0:
            lines.append("#")
        else:
            lines.append("# " + line)
    header = "\n".join(lines)
    # header = "\n".join(["# " + line for line in header.split("\n")])
    return header


def _add_header(string, header_cmd):
    if header_cmd is not None:
        return _create_header(header_cmd) + "\n" + string
    else:
        return string


def _yaml_to_string(data, yaml=None, add_final_eol=False, header_cmd=None) -> str:
    import io

    if yaml is None:
        yaml = YAML()
        yaml.indent(mapping=2, sequence=4, offset=2)

    buf = io.BytesIO()
    yaml.dump(data, buf)

    val = buf.getvalue()

    if not add_final_eol:
        val = val[:-1]
    return _add_header(val.decode("utf-8"), header_cmd)


def _optional_write(string, stream, mode="w"):
    if stream is None:
        return
    if isinstance(stream, (str, Path)):
        with open(stream, mode) as f:
            f.write(string)
    else:
        f.write(string)


def _output_to_yaml(
    dependencies: list[str] | None,
    channels: list[str] | None = None,
    pip: list[str] | None = None,
    name: Tstr_opt = None,
    stream: str | Path | None = None,
    header_cmd: str | None = None,
):
    data: dict[str, Any] = {}
    if name:
        data["name"] = name

    if channels:
        data["channels"] = channels

    data["dependencies"] = []
    if dependencies:
        data["dependencies"].extend(dependencies)
    if pip:
        data["dependencies"].append("pip")
        data["dependencies"].append({"pip": pip})

    # return data
    s = _yaml_to_string(data, add_final_eol=True, header_cmd=header_cmd)
    _optional_write(s, stream)

    return s


T = TypeVar("T", bound="PyProject2Conda")


class PyProject2Conda:
    """Wrapper class to transform pyproject.toml -> environment.yaml"""

    def __init__(
        self,
        data: tomlkit.toml_document.TOMLDocument,
        name: Tstr_opt = None,
        channels: Tstr_seq_opt = None,
        python_include: Tstr_opt = None,
    ) -> None:
        self.data = data
        self.name = name
        self.channels = channels
        self.python_include = python_include

    def to_conda_yaml(
        self,
        extras: Tstr_seq_opt = None,
        name: Tstr_opt = None,
        channels: Tstr_seq_opt = None,
        python_include: Tstr_opt = None,
        stream: str | Path | None = None,
        python_version: Tstr_opt = None,
        include_base_dependencies: bool = True,
        header_cmd: str | None = None,
    ):
        self._check_extras(extras)

        return pyproject_to_conda(
            data=self.data,
            extras=extras,
            name=name or self.name,
            channels=channels or self.channels,
            python_include=python_include or self.python_include,
            stream=stream,
            python_version=python_version,
            include_base_dependencies=include_base_dependencies,
            header_cmd=header_cmd,
        )

    def to_conda_lists(
        self,
        extras: Tstr_seq_opt = None,
        channels: Tstr_seq_opt = None,
        python_include: Tstr_opt = None,
        python_version: Tstr_opt = None,
        include_base_dependencies: bool = True,
    ) -> dict[str, Any]:
        self._check_extras(extras)

        return pyproject_to_conda_lists(
            data=self.data,
            extras=extras,
            channels=channels or self.channels,
            python_include=python_include or self.python_include,
            python_version=python_version,
            include_base_dependencies=include_base_dependencies,
        )

    def to_requirement_list(
        self,
        extras: Tstr_seq_opt = None,
        include_base_dependencies: bool = True,
    ) -> list[str]:
        self._check_extras(extras)

        values = _pyproject_to_value_comment_pairs(
            data=self.data,
            extras=extras,
            include_base_dependencies=include_base_dependencies,
        )
        return [x for x, y in values if x is not None]

    def to_requirements(
        self,
        extras: Tstr_opt = None,
        include_base_dependencies: bool = True,
        header_cmd: str | None = None,
        stream: str | Path | None = None,
    ):
        """Create requirements.txt like file with pip dependencies."""

        self._check_extras(extras)

        reqs = self.to_requirement_list(
            extras=extras, include_base_dependencies=include_base_dependencies
        )

        s = _add_header(_list_to_str(reqs), header_cmd)
        _optional_write(s, stream)
        return s

    def to_conda_requirements(
        self,
        extras: Tstr_opt = None,
        channels: Tstr_seq_opt = None,
        python_include: Tstr_opt = None,
        python_version: Tstr_opt = None,
        prepend_channel: bool = False,
        stream_conda: str | Path | None = None,
        stream_pip: str | Path | None = None,
        include_base_dependencies: bool = True,
        header_cmd: Tstr_opt = None,
    ):
        output = self.to_conda_lists(
            extras=extras,
            channels=channels,
            python_include=python_include,
            python_version=python_version,
            include_base_dependencies=include_base_dependencies,
        )

        deps = output.get("dependencies", None)
        reqs = output.get("pip", None)

        channels = output.get("channels", None)
        if channels and prepend_channel:
            assert len(channels) == 1
            channel = channels[0]
            # add in channel if none exists
            if deps:
                deps = [dep if "::" in dep else f"{channel}::{dep}" for dep in deps]

        deps_str = _add_header(_list_to_str(deps), header_cmd)
        reqs_str = _add_header(_list_to_str(reqs), header_cmd)

        if stream_conda and deps_str:
            _optional_write(deps_str, stream_conda)

        if stream_pip and reqs_str:
            _optional_write(reqs_str, stream_pip)

        return deps_str, reqs_str

    def _check_extras(self, extras):
        def _do_test(sent, available):
            if isinstance(sent, str):
                sent = [sent]
            for s in sent:
                if s not in available:
                    raise ValueError(f"{s} not in {available}")

        if extras:
            _do_test(extras, self.list_extras())

    def _get_opts(self, *keys):
        opts = get_in(keys, self.data, None)
        if opts:
            return list(opts.keys())
        else:
            return []

    def list_extras(self):
        return self._get_opts("project", "optional-dependencies")

    @classmethod
    def from_string(
        cls: type[T],
        toml_string: str,
        name: Tstr_opt = None,
        channels: Tstr_seq_opt = None,
        python_include: Tstr_opt = None,
    ) -> T:
        data = tomlkit.parse(toml_string)
        return cls(
            data=data, name=name, channels=channels, python_include=python_include
        )

    @classmethod
    def from_path(
        cls: type[T],
        path: str | Path,
        name: Tstr_opt = None,
        channels: Tstr_seq_opt = None,
        python_include: Tstr_opt = None,
    ) -> T:
        path = Path(path)

        if not path.exists():
            raise ValueError(f"{path} does not exist")

        with open(path, "rb") as f:
            data = tomlkit.load(f)
        return cls(
            data=data, name=name, channels=channels, python_include=python_include
        )


def _list_to_stream(values, stream=None):
    value = "\n".join(values)
    if isinstance(stream, (str, Path)):
        with open(stream, "w") as f:
            f.write(value)

    elif stream is None:
        return value

    else:
        stream.write(value)
