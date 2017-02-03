import argparse
import os
import tarfile
import tempfile
import subprocess
import sys

import jinja2
import requests

import cargodeps

API_URL = "https://crates.io/api/v1/"
TEMPLATE = """# Generated by rust2rpm
%bcond_without check

%global crate {{ md.name }}

Name:           rust-%{crate}
Version:        {{ md.version }}
Release:        1%{?dist}
Summary:        # FIXME

License:        # FIXME
URL:            https://crates.io/crates/{{ md.name }}
Source0:        https://crates.io/api/v1/crates/%{crate}/%{version}/download#/%{crate}-%{version}.crate

ExclusiveArch:  %{rust_arches}

BuildRequires:  rust
BuildRequires:  cargo
{% for req in md.build_requires %}
BuildRequires:  {{ req }}
{% endfor %}
{% for con in md.build_conflicts %}
BuildConflicts: {{ con }}
{% endfor %}
{% if md.test_requires|length > 0 %}
%if %{with check}
{% for req in md.test_requires %}
BuildRequires:  {{ req }}
{% endfor %}
{% for con in md.test_conflicts %}
BuildConflicts: {{ con }}
{% endfor %}
%endif
{% endif %}

%description
%{summary}.

%package        devel
Summary:        %{summary}
BuildArch:      noarch
{% if target == "epel-7" %}
{% for prv in md.provides %}
Provides:       {{ prv }}
{% endfor %}
{% for req in md.requires %}
Requires:       {{ req }}
{% endfor %}
{% for con in md.conflicts %}
Conflicts:      {{ con }}
{% endfor %}
{% endif %}

%description    devel
%{summary}.

%prep
%autosetup -n %{crate}-%{version}
%cargo_prep

%install
%cargo_install_crate %{crate}-%{version}

%if %{with check}
%check
%cargo_test
%endif

%files devel
%license # FIXME
%{cargo_registry}/%{crate}-%{version}/

%changelog
"""
JINJA_ENV = jinja2.Environment(undefined=jinja2.StrictUndefined,
                               trim_blocks=True, lstrip_blocks=True)


def run_depgen(*params):
    cmd = [sys.executable, cargodeps.__file__, *params]
    out = subprocess.check_output(cmd, universal_newlines=True)
    return out.split("\n")[:-1]

if __name__ == "__main__":
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

    cratef = "{}-{}.crate".format(args.crate, args.version)
    if not os.path.isfile(cratef):
        url = requests.compat.urljoin(API_URL, "crates/{}/{}/download#".format(args.crate, args.version))
        req = requests.get(url, stream=True)
        req.raise_for_status()
        with open(cratef, "wb") as f:
            # FIXME: should we use req.iter_content() and specify custom chunk size?
            for chunk in req:
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

        metadata = cargodeps.Metadata.from_file(toml)

    template = JINJA_ENV.from_string(TEMPLATE)
    print(template.render(target=args.target, md=metadata))
