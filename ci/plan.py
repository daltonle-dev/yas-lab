#!/usr/bin/env python3
"""Decide which YAS images need building (decision D5: build only what changed).

For every image:
  inputs = its own folder
         + every module of this repo it depends on (read from pom.xml, recursively)
         + the root pom.xml                                   (Java services only)
  tag    = first 10 chars of the last commit that touched any of the inputs
  action = "skip" if <registry>/yas/<image>:<tag> already exists in ECR, else "build"

Output, one line per image:  <image> <dir> <kind> <tag> <action> <inputs,...>

Why tag by "last commit touching the inputs" and not by HEAD:
  - change cart/        -> only cart gets a new tag -> only cart is built
  - change common-library/ -> every service using it gets a new tag
  - new session, no code change -> every tag already in ECR -> nothing built
  Nothing has to remember the previous build (Jenkins is recreated every session).

Usage: python3 ci/plan.py          (env: AWS_REGION, FORCE_ALL=true to rebuild everything)
"""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROUP = "com.yas"
NS = {"m": "http://maven.apache.org/POM/4.0.0"}

# image name in ECR (yas/<image>)   folder            kind
IMAGES = [
    ("backoffice-bff",    "backoffice-bff", "java"),
    ("storefront-bff",    "storefront-bff", "java"),
    ("media",             "media",          "java"),
    ("product",           "product",        "java"),
    ("customer",          "customer",       "java"),
    ("cart",              "cart",           "java"),
    ("rating",            "rating",         "java"),
    ("order",             "order",          "java"),
    ("payment",           "payment",        "java"),
    ("location",          "location",       "java"),
    ("inventory",         "inventory",      "java"),
    ("promotion",         "promotion",      "java"),
    ("tax",               "tax",            "java"),
    ("sampledata",        "sampledata",     "java"),
    ("search",            "search",         "java"),
    ("backoffice-nextjs", "backoffice",     "node"),
    ("storefront-nextjs", "storefront",     "node"),
]


def module_deps(module, seen=None):
    """Modules of this repo that `module` depends on, recursively (from its pom.xml)."""
    seen = set() if seen is None else seen
    pom = ET.parse(os.path.join(ROOT, module, "pom.xml")).getroot()
    for dep in pom.findall("m:dependencies/m:dependency", NS):
        group = dep.findtext("m:groupId", default="", namespaces=NS)
        artifact = dep.findtext("m:artifactId", default="", namespaces=NS)
        if group == GROUP and artifact not in seen and os.path.isfile(os.path.join(ROOT, artifact, "pom.xml")):
            seen.add(artifact)
            module_deps(artifact, seen)
    return seen


def run(*cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def main():
    region = os.environ.get("AWS_REGION", "ap-south-1")
    force = os.environ.get("FORCE_ALL", "false").lower() == "true"

    for image, folder, kind in IMAGES:
        inputs = [folder]
        if kind == "java":
            inputs += sorted(module_deps(folder)) + ["pom.xml"]

        log = run("git", "log", "-1", "--format=%H", "--", *inputs)
        if log.returncode != 0 or not log.stdout.strip():
            sys.exit(f"cannot compute tag for {image}: {log.stderr.strip() or 'no commit touches its inputs'}")
        tag = log.stdout.strip()[:10]

        exists = run("aws", "ecr", "describe-images", "--region", region,
                     "--repository-name", f"yas/{image}",
                     "--image-ids", f"imageTag={tag}").returncode == 0
        action = "build" if force or not exists else "skip"
        print(image, folder, kind, tag, action, ",".join(inputs))


if __name__ == "__main__":
    main()
