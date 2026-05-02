#!/usr/bin/env python3
"""
Cartography analysis jobs expect EC2SecurityGroup (instance view) nodes to expose `name`.
Instance sync only supplies GroupId — map `name` to the same field so QueryBuilder stops warning.
"""
import glob
import sys

TARGET_SUBSTR = 'groupid: PropertyRef = PropertyRef("GroupId", extra_index=True)'


def find_file() -> str:
    globs = [
        "/usr/local/lib/python*/site-packages/cartography/models/aws/ec2/securitygroup_instance.py",
        "/var/cartography/.local/share/uv/tools/cartography/lib/python*/site-packages/cartography/models/aws/ec2/securitygroup_instance.py",
    ]
    for pattern in globs:
        for path in glob.glob(pattern):
            return path
    raise FileNotFoundError("securitygroup_instance.py not found under known site-packages paths")


def main() -> int:
    path = find_file()
    with open(path, "r") as f:
        lines = f.read().splitlines()

    if any('name: PropertyRef = PropertyRef("GroupId")' in line for line in lines):
        print("EC2SecurityGroup name patch already applied", file=sys.stderr)
        return 0

    out: list[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and TARGET_SUBSTR in line:
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f'{indent}name: PropertyRef = PropertyRef("GroupId")')
            inserted = True

    if not inserted:
        print(
            "Could not find groupid PropertyRef line in securitygroup_instance.py (Cartography version drift).",
            file=sys.stderr,
        )
        return 1

    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")
    print(f"Applied EC2SecurityGroupInstance name patch -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
