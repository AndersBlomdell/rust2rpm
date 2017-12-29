import argparse
from datetime import datetime, timezone
import difflib
import os
import shutil
import tarfile
import tempfile
import time
import subprocess

import jinja2
import requests
import tqdm

from . import Metadata

DEFAULT_EDITOR = "vi"
XDG_CACHE_HOME = os.getenv("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
CACHEDIR = os.path.join(XDG_CACHE_HOME, "rust2rpm")
API_URL = "https://crates.io/api/v1/"
JINJA_ENV = jinja2.Environment(loader=jinja2.ChoiceLoader([
                               jinja2.FileSystemLoader(['/']),
                               jinja2.PackageLoader('rust2rpm', 'templates'), ]),
                               trim_blocks=True, lstrip_blocks=True)

def detect_distro():
    with open("/etc/os-release") as os_release_file:
        os_release_dict = {}
        for line in os_release_file:
            key, value = line.rstrip().split('=')
            os_release_dict[key] = value.strip('"')
    return os_release_dict

def get_default_target():
    distro_release = detect_distro()
    distro_family = distro_release.get("ID_LIKE")
    distro_id = distro_release.get("ID")
    if distro_family is None:
        distro_family = ""
    # Order matters here!
    if distro_id == "mageia" or ("mageia" in distro_family):
        return "mageia"
    elif distro_id == "fedora" or ("fedora" in distro_family):
        return "fedora"
    elif "suse" in distro_family:
        return "opensuse"
    else:
        return "plain"

def detect_editor():
    terminal = os.getenv("TERM")
    terminal_is_dumb = terminal is None or terminal == "dumb"
    editor = None
    if not terminal_is_dumb:
        editor = os.getenv("VISUAL")
    if editor is None:
        editor = os.getenv("EDITOR")
    if editor is None:
        if terminal_is_dumb:
            raise Exception("Terminal is dumb, but EDITOR unset")
        else:
            editor = DEFAULT_EDITOR
    return editor

def detect_packager():
    rpmdev_packager = shutil.which("rpmdev-packager")
    if rpmdev_packager is not None:
        return subprocess.check_output(rpmdev_packager, universal_newlines=True).strip()

    git = shutil.which("git")
    if git is not None:
        name = subprocess.check_output([git, "config", "user.name"], universal_newlines=True).strip()
        email = subprocess.check_output([git, "config", "user.email"], universal_newlines=True).strip()
        return "{} <{}>".format(name, email)

    return None

def file_mtime(path):
    t = datetime.fromtimestamp(os.stat(path).st_mtime, timezone.utc)
    return t.astimezone().isoformat()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-", "--stdout", action="store_true",
                        help="Print spec and patches into stdout")
    parser.add_argument("-t", "--target", action="store",
                        choices=("plain", "fedora", "mageia", "opensuse"), default=get_default_target(),
                        help="Distribution target")
    parser.add_argument("-p", "--patch", action="store_true",
                        help="Do initial patching of Cargo.toml")
    parser.add_argument("crate", help="crates.io name")
    parser.add_argument("version", nargs="?", help="crates.io version")
    args = parser.parse_args()

    if args.patch:
        editor = detect_editor()

    if args.version is None:
        # Now we need to get latest version
        url = requests.compat.urljoin(API_URL, "crates/{}/versions".format(args.crate))
        req = requests.get(url)
        req.raise_for_status()
        versions = req.json()["versions"]
        args.version = next(version["num"] for version in versions if not version["yanked"])

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

    with tempfile.TemporaryDirectory() as tmpdir:
        target_dir = "{}/".format(tmpdir)
        with tarfile.open(cratef, "r") as archive:
            for n in archive.getnames():
                if not os.path.abspath(os.path.join(target_dir, n)).startswith(target_dir):
                    raise Exception("Unsafe filenames!")
            archive.extractall(target_dir)
        toml_relpath = "{}-{}/Cargo.toml".format(args.crate, args.version)
        toml = "{}/{}".format(tmpdir, toml_relpath)
        assert os.path.isfile(toml)

        if args.patch:
            mtime_before = file_mtime(toml)
            with open(toml, "r") as fobj:
                toml_before = fobj.readlines()
            subprocess.check_call([editor, toml])
            mtime_after = file_mtime(toml)
            with open(toml, "r") as fobj:
                toml_after = fobj.readlines()
            diff = list(difflib.unified_diff(toml_before, toml_after,
                                             fromfile=toml_relpath, tofile=toml_relpath,
                                             fromfiledate=mtime_before, tofiledate=mtime_after))

        metadata = Metadata.from_file(toml)

    template = JINJA_ENV.get_template("main.spec")

    if args.patch and len(diff) > 0:
        patch_file = "{}-{}-fix-metadata.diff".format(args.crate, args.version)
    else:
        patch_file = None

    kwargs = {}
    kwargs["target"] = args.target
    bins = [tgt for tgt in metadata.targets if tgt.kind == "bin"]
    libs = [tgt for tgt in metadata.targets if tgt.kind in ("lib", "rlib", "proc-macro")]
    is_bin = len(bins) > 0
    is_lib = len(libs) > 0
    if is_bin:
        kwargs["include_main"] = True
        kwargs["bins"] = bins
    elif is_lib:
        kwargs["include_main"] = False
    else:
        raise ValueError("No bins and no libs")
    kwargs["include_devel"] = is_lib

    if args.target in ("fedora", "mageia", "opensuse"):
        kwargs["include_build_requires"] = True
        kwargs["include_provides"] = False
        kwargs["include_requires"] = False
    elif args.target == "plain":
        kwargs["include_build_requires"] = True
        kwargs["include_provides"] = True
        kwargs["include_requires"] = True
    else:
        assert False, "Unknown target {!r}".format(args.target)

    if args.target == "mageia":
        kwargs["pkg_release"] = "%mkrel 1"
        kwargs["rust_group"] = "Development/Rust"
    elif args.target == "opensuse":
        kwargs["spec_copyright_year"] = time.strftime("%Y")
        kwargs["pkg_release"] = "0"
        kwargs["rust_group"] = "Development/Libraries/Rust"
    else:
        kwargs["pkg_release"] = "1%{?dist}"

    if args.target == "opensuse":
        kwargs["date"] = time.strftime("%a %b %d %T %Z %Y")
    else:
        kwargs["date"] = time.strftime("%a %b %d %Y")
    kwargs["packager"] = detect_packager()

    spec_file = "rust-{}.spec".format(args.crate)
    spec_contents = template.render(md=metadata, patch_file=patch_file, **kwargs)
    if args.stdout:
        print("# {}".format(spec_file))
        print(spec_contents)
        if patch_file is not None:
            print("# {}".format(patch_file))
            print("".join(diff), end="")
    else:
        with open(spec_file, "w") as fobj:
            fobj.write(spec_contents)
            fobj.write("\n")
        if patch_file is not None:
            with open(patch_file, "w") as fobj:
                fobj.writelines(diff)

if __name__ == "__main__":
    main()
