import argparse
import os
import tarfile
import tempfile
import subprocess
import sys

import jinja2
import jinja2.ext
import jinja2.exceptions
import requests
import tqdm

from . import Metadata

# See: http://jinja.pocoo.org/docs/latest/extensions/#example-extension
class RaiseExtension(jinja2.ext.Extension):
    # a set of names that trigger the extension.
    tags = set(["raise"])

    def parse(self, parser):
        # the first token is the token that started the tag.  In our case
        # we only listen to ``'raise'`` so this will be a name token with
        # `raise` as value.  We get the line number so that we can give
        # that line number to the nodes we create by hand.
        lineno = next(parser.stream).lineno

        # Extract the message from the template
        message_node = parser.parse_expression()

        return jinja2.nodes.CallBlock(
            self.call_method("_raise", [message_node], lineno=lineno),
            [], [], [], lineno=lineno)

    def _raise(self, msg, caller):
        raise jinja2.exceptions.TemplateRuntimeError(msg)

XDG_CACHE_HOME = os.getenv("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
CACHEDIR = os.path.join(XDG_CACHE_HOME, "rust2rpm")
API_URL = "https://crates.io/api/v1/"
TEMPLATE = """# Generated by rust2rpm
{% set bins = md.targets|selectattr("kind", "equalto", "bin")|list() %}
{% set libs = md.targets|selectattr("kind", "equalto", "lib")|list() %}
{% set is_bin = bins|length > 0 %}
{% set is_lib = libs|length > 0 %}
{% if is_bin and not is_lib %}
  {% set include_debug = True %}
  {% set name = "%{crate}" %}
  {% set include_main = True %}
  {% set name_devel = None %}
{% elif is_lib and not is_bin %}
  {% set include_debug = False %}
  {% set name = "rust-%{crate}" %}
  {% set include_main = False %}
  {% set name_devel = "   devel" %}
{% elif is_bin and is_lib %}
  {% set include_debug = True %}
  {% set name = "%{crate}" %}
  {% set include_main = True %}
  {% set name_devel = "-n rust-%{crate}-devel" %}
{% else %}
  {% raise "No bins and no libs" %}
{% endif %}
%bcond_without check
{% if not include_debug %}
%global debug_package %{nil}
{% endif %}

%global crate {{ md.name }}

Name:           {{ name }}
Version:        {{ md.version }}
Release:        1%{?dist}
{% if md.description is none %}
Summary:        # FIXME
{% else %}
{% set description_lines = md.description.split("\n") %}
Summary:        {{ description_lines|join(" ")|trim }}
{% endif %}

License:        {{ md.license|default("# FIXME") }}
URL:            https://crates.io/crates/{{ md.name }}
Source0:        https://crates.io/api/v1/crates/%{crate}/%{version}/download#/%{crate}-%{version}.crate

ExclusiveArch:  %{rust_arches}

BuildRequires:  rust
BuildRequires:  cargo
{% for req in md.build_requires|sort(attribute="name") %}
BuildRequires:  {{ req }}
{% endfor %}
{% for con in md.build_conflicts|sort(attribute="name") %}
BuildConflicts: {{ con }}
{% endfor %}
{% if md.test_requires|length > 0 %}
%if %{with check}
{% for req in md.test_requires|sort(attribute="name") %}
BuildRequires:  {{ req }}
{% endfor %}
{% for con in md.test_conflicts|sort(attribute="name") %}
BuildConflicts: {{ con }}
{% endfor %}
%endif
{% endif %}

%description
%{summary}.

{% if name_devel is not none %}
%package     {{ name_devel }}
Summary:        %{summary}
BuildArch:      noarch
{% if target == "epel-7" %}
{% for prv in md.provides %}
Provides:       {{ prv }}
{% endfor %}
{% for req in md.requires|sort(attribute="name") %}
Requires:       {{ req }}
{% endfor %}
{% for con in md.conflicts|sort(attribute="name") %}
Conflicts:      {{ con }}
{% endfor %}
{% endif %}

%description {{ name_devel }}
{% if md.description is none %}
%{summary}.
{% else %}
{{ md.description|wordwrap|trim }}
{% endif %}

This package contains library source intended for building other packages
which use %{crate} from crates.io.

{% endif %}
%prep
%autosetup -n %{crate}-%{version}
%cargo_prep

%build
%cargo_build

%install
%cargo_install

%if %{with check}
%check
%cargo_test
%endif

{% if include_main %}
%files
{% for bin in bins %}
%{_bindir}/{{ bin.name }}
{% endfor %}

{% endif %}
{% if name_devel is not none %}
%files       {{ name_devel }}
{% if md.license_file is not none %}
%license {{ md.license_file }}
{% endif %}
%{cargo_registry}/%{crate}-%{version}/

{% endif %}
%changelog
"""
JINJA_ENV = jinja2.Environment(undefined=jinja2.StrictUndefined,
                               extensions=[RaiseExtension],
                               trim_blocks=True, lstrip_blocks=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--target", choices=("epel-7", "fedora-26"), required=True,
                        help="Distribution target")
    parser.add_argument("crate", help="crates.io name")
    parser.add_argument("version", nargs="?", help="crates.io version")
    args = parser.parse_args()

    if args.version is None:
        # Now we need to get latest version
        url = requests.compat.urljoin(API_URL, "crates/{}/versions".format(args.crate))
        req = requests.get(url)
        req.raise_for_status()
        args.version = req.json()["versions"][0]["num"]

    if not os.path.isdir(CACHEDIR):
        os.mkdir(CACHEDIR)
    cratef_base = "{}-{}.crate".format(args.crate, args.version)
    cratef = os.path.join(CACHEDIR, cratef_base)
    if not os.path.isfile(cratef):
        url = requests.compat.urljoin(API_URL, "crates/{}/{}/download#".format(args.crate, args.version))
        req = requests.get(url, stream=True)
        req.raise_for_status()
        total = int(req.headers["Content-Length"])
        with open(cratef, "wb") as f:
            for chunk in tqdm.tqdm(req.iter_content(), "Downloading {}".format(cratef_base),
                                   total=total, unit="B", unit_scale=True):
                f.write(chunk)

    files = []
    with tempfile.TemporaryDirectory() as tmpdir:
        target_dir = "{}/".format(tmpdir)
        with tarfile.open(cratef, "r") as archive:
            for n in archive.getnames():
                if not os.path.abspath(os.path.join(target_dir, n)).startswith(target_dir):
                    raise Exception("Unsafe filenames!")
            archive.extractall(target_dir)
        toml = "{}/{}-{}/Cargo.toml".format(tmpdir, args.crate, args.version)
        assert os.path.isfile(toml)

        metadata = Metadata.from_file(toml)

    template = JINJA_ENV.from_string(TEMPLATE)
    print(template.render(target=args.target, md=metadata))

if __name__ == "__main__":
    main()