{% include target ~ "-header.spec.inc" ignore missing %}
# Generated by rust2rpm
%bcond_without check
{% if not include_main %}
%global debug_package %{nil}
{% endif %}

%global crate {{ md.name }}

Name:           rust-%{crate}
Version:        {{ md.version }}
Release:        {{ pkg_release }}
{% if md.description is none %}
Summary:        # FIXME
{% else %}
{% set description_lines = md.description.split("\n") %}
Summary:        {{ description_lines|join(" ")|trim }}
{% endif %}
{% if rust_group is defined %}
Group:          {{ rust_group }}
{% endif %}

License:        {{ md.license|default("# FIXME") }}
URL:            https://crates.io/crates/{{ md.name }}
Source0:        https://crates.io/api/v1/crates/%{crate}/%{version}/download#/%{crate}-%{version}.crate
{% if patch_file is not none %}
{% if target == "opensuse" %}
# PATCH-FIX-OPENSUSE {{ patch_file }} -- Initial patched metadata
{% else %}
# Initial patched metadata
{% endif %}
Patch0:         {{ patch_file }}
{% endif %}

ExclusiveArch:  %{rust_arches}

BuildRequires:  rust-packaging
{% if include_build_requires %}
{% if md.requires|length > 0 %}
# [dependencies]
{% for req in md.requires|sort(attribute="name") %}
BuildRequires:  {{ req }}
{% endfor %}
{% endif %}
{% if md.build_requires|length > 0 %}
# [build-dependencies]
{% for req in md.build_requires|sort(attribute="name") %}
BuildRequires:  {{ req }}
{% endfor %}
{% endif %}
{% if md.test_requires|length > 0 %}
%if %{with check}
# [dev-dependencies]
{% for req in md.test_requires|sort(attribute="name") %}
BuildRequires:  {{ req }}
{% endfor %}
%endif
{% endif %}
{% endif %}

%description
%{summary}.

{% if include_main %}
%package     -n %{crate}
Summary:        %{summary}
{% if rust_group is defined %}
Group:          # FIXME
{% endif %}

%description -n %{crate}
%{summary}.

{% endif %}
{% if include_devel %}
%package        devel
Summary:        %{summary}
{% if rust_group is defined %}
Group:          {{ rust_group }}
{% endif %}
BuildArch:      noarch
{% if include_provides %}
{% for prv in md.provides %}
Provides:       {{ prv }}
{% endfor %}
{% endif %}
{% if include_requires %}
Requires:       cargo
{% if md.requires|length > 0 %}
# [dependencies]
{% for req in md.requires|sort(attribute="name") %}
Requires:       {{ req }}
{% endfor %}
{% endif %}
{% if md.build_requires|length > 0 %}
# [build-dependencies]
{% for req in md.build_requires|sort(attribute="name") %}
Requires:       {{ req }}
{% endfor %}
{% endif %}
{% endif %}

%description    devel
{% if md.description is none %}
%{summary}.
{% else %}
{{ md.description|wordwrap|trim }}
{% endif %}

This package contains library source intended for building other packages
which use %{crate} from crates.io.

{% endif %}
%prep
%autosetup -n %{crate}-%{version} -p1
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
%files       -n %{crate}
{% if md.license_file is not none %}
%license {{ md.license_file }}
{% endif %}
{% for bin in bins %}
%{_bindir}/{{ bin.name }}
{% endfor %}

{% endif %}
{% if include_devel %}
%files          devel
{% if md.license_file is not none %}
%license {{ md.license_file }}
{% endif %}
%{cargo_registry}/%{crate}-%{version}/

{% endif %}
%changelog
{% include target ~ "-changelog.spec.inc" %}
