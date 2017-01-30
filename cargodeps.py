#!/usr/bin/python
from __future__ import print_function
from __future__ import unicode_literals

import argparse
import json
import subprocess
import sys

import semantic_version as semver

REQ_TO_CON = {">": "<=",
              "<": ">=",
              ">=": "<",
              "<=": ">"}

def get_metadata(path):
    # --no-deps is to disable recursive scanning of deps
    metadata = subprocess.check_output(["cargo", "metadata", "--no-deps",
                                        "--manifest-path={}".format(path)])
    return json.loads(metadata)["packages"][0]

def parse_req(s):
    if "*" in s:
        raise NotImplementedError("https://github.com/rbarrois/python-semanticversion/issues/51")
    spec = semver.Spec(s.replace(" ", ""))
    specs = spec.specs
    if len(specs) == 1:
        req = specs[0]
        if req.kind in (req.KIND_CARET, req.KIND_TILDE):
            ver = req.spec
            lower = semver.Version.coerce(str(ver))
            if req.kind == req.KIND_CARET:
                if ver.major == 0:
                    if ver.minor is not None:
                        if ver.patch is None or ver.minor != 0:
                            upper = ver.next_minor()
                        else:
                            upper = ver.next_patch()
                    else:
                        upper = ver.next_major()
                else:
                  upper = ver.next_major()
            elif req.kind == req.KIND_TILDE:
                if ver.minor is None:
                    upper = ver.next_major()
                else:
                    upper = ver.next_minor()
            else:
                assert False
            return (semver.Spec(">={}".format(lower)).specs[0],
                    semver.Spec("<{}".format(upper)).specs[0])
        else:
            return (req, None)
    elif len(specs) == 2:
        return (specs[0], specs[1])
    else:
        # it's something uber-complicated
        raise NotImplementedError("More than two ranges are unsupported, probably something is wrong with metadata")
    assert False

def print_dep(name, spec, kind="=", feature=None):
    f_part = "/{}".format(feature) if feature is not None else ""
    print("crate({}{}) {} {}".format(name, f_part, kind.replace("==", "="), spec))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-P", "--provides", action="store_true", help="Print Provides")
    group.add_argument("-R", "--requires", action="store_true", help="Print Requires")
    group.add_argument("-C", "--conflicts", action="store_true", help="Print Conflicts")
    parser.add_argument("file", nargs="*", help="Path(s) to Cargo.toml")
    args = parser.parse_args()

    files = args.file or sys.stdin.readlines()

    for f in files:
        f = f.rstrip()
        md = get_metadata(f)
        if args.provides:
            print_dep(md["name"], md["version"])
            for feature in md["features"]:
                print_dep(md["name"], md["version"], feature=feature)
        if args.requires or args.conflicts:
            for dep in md["dependencies"]:
                if dep["kind"] is not None:
                    # kind: build -> build dependencies
                    # kind: dev   -> test dependencies
                    continue
                req, con = parse_req(dep["req"])
                assert req is not None
                for feature in dep["features"] or [None]:
                    if args.requires:
                        print_dep(dep["name"], req.spec, req.kind, feature=feature)
                    if args.conflicts and con is not None:
                        print_dep(dep["name"], con.spec, REQ_TO_CON[con.kind], feature=feature)