#!/usr/bin/env python3
"""Non-generative preflight for a linux-utilities checkpoint-000 smoke test on vessel.

Checks the host controller, Docker/Colima, the pinned Linux images, Aider, the
local native Ollama API and the checkpoint-000 inputs. It never invokes model
inference, never starts Aider generation, never installs or pulls anything,
never builds images and never changes a Docker context. Default preflight starts
only trusted probes. Opt-in vessel-built validation also runs existing isolated
infrastructure controls, never generates candidate implementations or invokes
Aider/Ollama.

Exit status: 0 every essential check passed, 1 an essential check failed,
2 usage error. Kept parseable by old interpreters (no 3.10+ syntax) so that a
too-old `python3` is reported rather than crashing.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["GIT_OPTIONAL_LOCKS"] = "0"

try:
    from urllib.parse import urlsplit
    from urllib.request import Request, urlopen
except ImportError:  # pragma: no cover - Python 2 is not supported at all
    raise SystemExit("python3 is required")

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DEFAULT_LOCK = ROOT / "docker/linux-utilities/lock-amd64.json"
DEFAULT_SELECTORS = tuple(language + "-" + utility
                          for language in ("c", "rust", "py")
                          for utility in ("cp", "mv", "mkdir", "sort"))
EXPECTED_AIDER = "aider 0.86.2"  # recorded by every formal lineages.json
# Store-independent identity of the validated AMD64 images: sha256 over the
# newline-joined RootFS diff_ids, captured 2026-11-02 from the Windows/WSL
# Docker Desktop engine that produced docker/linux-utilities/lock-amd64.json.
# Image IDs differ between containerd and classic image stores; diff_ids do not.
AMD64_ROOTFS = {
    "sha256:02cf23e5c3273ff2969f25010e79346dfbd98ae51499e04996ba802d49f99ad7":
        "ff790e63980a26a4c1d44347409e93a8ca09eb547a726dcbaf9ac3b2f8efd0d2",
    "sha256:39f8094edc3cf9548d5e9ce794d01b721da55e424bb45b2da4f86cd189d9577d":
        "dbb5331078b136310afafff80409501b7e1e654bcba005a3756d84de645c5c23",
    "python:3.12.8-bookworm@sha256:68ca65265c466f4b64f8ddab669e13bcba8d4ba77ec4c26658d36f2b9d1b1cad":
        "dc822d6f18925e67679a064b947db22cd8a67fc78d93e186a32426c6d6707416",
}
# Controller modules that must import under the `python3` named by manifests.
CONTROLLER_MODULES = (
    "docker_benchmark", "heldout_judge", "stage_test_bundle", "lineage_plan",
    "checkpoint_boundary_gate", "aider_settings", "aider_output", "prompt_render",
    "repair_prompt", "lineage_state", "temperature_value", "capture_candidate",
    "invocation_observations", "python_candidate", "linux_utilities_catalog",
)

RESULTS = []
MODEL_IDENTITIES = {}
IMAGE_IDENTITIES = {}
IMAGE_KEYS = ("oracle_image", "compiler_image", "rust_compiler_image")
VALIDATION_LOG = None
# Platform manifests observed by resolving the ORIGINAL immutable lock refs.
# A manifest commits to the complete OCI config blob and ordered layer blobs.
# These are NOT configuration digests or portable classic-store image IDs.
AMD64_MANIFESTS = {
    "oracle_image": "sha256:42a38e1ed65aa195d65c6563c54187a07dad361158129278fd3b2dfe5a783528",
    "compiler_image": "sha256:90b5639c188a54aa4252028b19d6f1134e43a13d0947ba463bae09a5b6776804",
    "rust_compiler_image": "sha256:9c040eb21f2e7bdd9d913d50ee39cc382622a4b7f6d615531dbb7bc562129514",
}


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def stable_environment(environment):
    """Boot IDs are observations; every other environment field remains binding."""
    result = dict(environment)
    if isinstance(result.get("emulation"), dict):
        result["emulation"] = {k: v for k, v in result["emulation"].items() if k != "boot_id"}
    return result


def stable_binding(binding):
    return dict(binding, environment=stable_environment(binding["environment"]))


def approval_scope(args, binding):
    scope = getattr(args, "approval_scope", "diagnostic-only")
    if scope not in ("diagnostic-only", "formal-vessel-8g"):
        raise ValueError("unsupported approval scope")
    if scope == "formal-vessel-8g" and binding["execution_profile"] != {
            "mode": "vessel-8g", "rlimit_as_bytes": 8 * 1024**3}:
        raise ValueError("formal Vessel approval requires the fixed vessel-8g condition")
    return scope


def external_path(path):
    resolved = Path(path).resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        raise ValueError("diagnostic output and temporary paths must be outside the repository")
    return resolved


def record(check, status, detail, fix=None):
    RESULTS.append({"check": check, "status": status, "detail": detail, "fix": fix})
    print("[%s] %s: %s" % (status, check, detail))
    if fix and status == "FAIL":
        print("       fix: %s" % fix)


def run(argv, timeout=60, env=None, cwd=None):
    """Return (returncode, stdout, stderr); never raises for a missing tool."""
    try:
        done = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, env=env, cwd=cwd or str(ROOT))
        if VALIDATION_LOG is not None:
            with VALIDATION_LOG.open("a", encoding="utf-8") as log:
                log.write(json.dumps({"argv": argv, "returncode": done.returncode}) + "\n")
                log.write(done.stdout.decode("utf-8", "replace") + done.stderr.decode("utf-8", "replace") + "\n")
        return (done.returncode, done.stdout.decode("utf-8", "replace").strip(),
                done.stderr.decode("utf-8", "replace").strip())
    except OSError as error:
        return (127, "", "cannot execute %s: %s" % (argv[0], error))
    except subprocess.TimeoutExpired:
        return (124, "", "timed out after %ss: %s" % (timeout, " ".join(argv)))


def http_json(url, payload=None, timeout=10):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def check_git(allow_dirty):
    code, head, err = run(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
    if code != 0:
        record("git revision", "FAIL", err or "not a git checkout", "run from a clone of agentic_cyber")
        return
    _, branch, _ = run(["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"])
    _, upstream, _ = run(["git", "-C", str(ROOT), "rev-parse", "@{u}"])
    record("git revision", "INFO", "%s on %s (upstream %s)" % (head, branch, upstream or "unknown"))
    dirty_code, dirty, dirty_err = run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"])
    untracked_code, untracked, untracked_err = run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=normal"])
    if dirty_code or untracked_code:
        record("git working tree", "FAIL", "cannot establish status: " + (dirty_err or untracked_err))
        return
    if dirty:
        record("git working tree", "INFO" if allow_dirty else "FAIL",
               "tracked modifications:\n" + dirty, "commit/stash locally or `git checkout -- <file>` after review")
    else:
        extra = len([line for line in untracked.splitlines() if line.startswith("??")])
        record("git working tree", "PASS", "no tracked modifications (%d untracked entries)" % extra)


def check_host():
    machine = platform.machine()
    record("host", "INFO", "%s %s %s, python %s" % (platform.system(), platform.release(), machine,
                                                     platform.python_version()))
    if platform.system() == "Darwin":
        code, translated, _ = run(["sysctl", "-n", "sysctl.proc_translated"])
        if code == 0 and translated.strip() == "1":
            record("host arch", "FAIL", "this shell runs under Rosetta (x86_64 translation)",
                   "open a native arm64 terminal (arch -arm64 /bin/bash)")
        else:
            record("host arch", "PASS", "native %s process" % machine)


def check_python_and_bash():
    python3 = shutil.which("python3")
    python_bin = os.environ.get("PYTHON_BIN") or python3
    resolved = os.path.realpath(python_bin) if python_bin and os.path.exists(python_bin) else python_bin
    if not python3:
        record("python3", "FAIL", "python3 is not on PATH",
               "manifest commands invoke bare python3; put the controller interpreter first on PATH")
        return
    if os.path.realpath(python3) != os.path.realpath(shutil.which(python_bin) or python_bin):
        record("python3/PYTHON_BIN", "FAIL", "python3=%s but PYTHON_BIN=%s" % (python3, resolved),
               "export PYTHON_BIN=\"$(command -v python3)\" or put that interpreter first on PATH")
    probe = ("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); import %s; print(sys.version.split()[0])"
             % (str(SCRIPTS), str(ROOT / "tests"), ", ".join(CONTROLLER_MODULES)))
    code, out, err = run([python3, "-B", "-c", probe])
    if code != 0:
        record("python3 controller imports", "FAIL", "%s cannot import controller modules: %s"
               % (python3, err.splitlines()[-1] if err else code),
               "use a Python 3.10+ interpreter (e.g. Homebrew python3 or ac_venv) first on PATH")
    else:
        record("python3 controller imports", "PASS", "%s (Python %s)" % (python3, out))
    code, out, _ = run(["bash", "--version"])
    record("bash", "PASS" if code == 0 else "FAIL", out.splitlines()[0] if out else "bash missing")
    for script in ("run_experiment.sh", "run_lineage_experiment.sh", "vessel_smoke_stage.sh"):
        code, _, err = run(["bash", "-n", str(SCRIPTS / script)])
        record("bash -n " + script, "PASS" if code == 0 else "FAIL", err or "parses")


def check_timeout():
    tool = shutil.which("timeout") or shutil.which("gtimeout")
    if not tool:
        record("timeout", "FAIL", "neither timeout nor gtimeout on PATH (run_experiment.sh would run unbounded)",
               "brew install coreutils (gtimeout), or: mkdir -p ~/.local/bin && ln -sf \"$PWD/scripts/timeout.py\" ~/.local/bin/timeout")
        return
    start = time.time()
    code, _, err = run([tool, "--signal=TERM", "--kill-after=1", "1", "sleep", "5"], timeout=15)
    elapsed = time.time() - start
    if code == 124 and 0.8 <= elapsed < 4:
        record("timeout", "PASS", "%s enforced --signal=TERM --kill-after (exit 124 after %.1fs)" % (tool, elapsed))
    else:
        record("timeout", "FAIL", "%s returned %s after %.1fs: %s" % (tool, code, elapsed, err),
               "install GNU coreutils timeout (brew install coreutils)")


def check_aider(expected):
    aider = os.environ.get("AIDER_BIN", "aider")
    path = shutil.which(aider)
    if not path:
        record("aider", "FAIL", "%s not found on PATH" % aider,
               "python3 -m pip install aider-install && aider-install, then pin aider-chat==0.86.2")
        return
    code, out, err = run([path, "--version"], timeout=120)
    version = (out or err).splitlines()[0] if (out or err) else ""
    if code != 0 or version != expected:
        record("aider", "FAIL", "%s reports %r (expected %r)" % (path, version, expected),
               "install the recorded version: uv tool install --force aider-chat==0.86.2 (or pipx/aider-install equivalent)")
    else:
        record("aider", "PASS", "%s: %s" % (path, version))


def check_docker(lock_platform):
    if not shutil.which("docker"):
        record("docker cli", "FAIL", "docker not on PATH", "start Docker Desktop and enable its CLI on PATH")
        return False
    if shutil.which("colima"):
        code, out, err = run(["colima", "status"], timeout=30)
        record("colima", "INFO" if code == 0 else "WARN", (out + "\n" + err).strip() or "status %s" % code)
    # Docker CLI precedence: DOCKER_CONTEXT > DOCKER_HOST > current context.
    context = os.environ.get("DOCKER_CONTEXT", "")
    host = os.environ.get("DOCKER_HOST", "")
    if context or not host:
        if not context:
            code, context, err = run(["docker", "context", "show"], timeout=20)
            if code or not context:
                record("docker endpoint", "FAIL", "cannot resolve current Docker context")
                return False
        code, endpoint, err = run(["docker", "context", "inspect", context,
                                   "--format", "{{.Endpoints.docker.Host}}"], timeout=20)
        if code:
            record("docker endpoint", "FAIL", "cannot inspect effective Docker context")
            return False
    else:
        endpoint = host
    parts = urlsplit(endpoint)
    if (parts.scheme != "unix" or parts.netloc or not parts.path.startswith("/")
            or parts.query or parts.fragment):
        record("docker endpoint", "FAIL", "local Unix-socket Docker/Colima endpoint required; remote endpoints rejected")
        return False
    record("docker endpoint", "PASS", "context=%s endpoint=%s (DOCKER_CONTEXT takes precedence over DOCKER_HOST)"
           % (context or "DOCKER_HOST", endpoint))
    code, out, err = run(["docker", "info", "--format", "{{json .}}"], timeout=60)
    if code != 0:
        record("docker daemon", "FAIL", err or "unreachable",
               "start Docker Desktop, or fix DOCKER_HOST/context; preflight changes neither")
        return False
    info = json.loads(out)
    store = dict(info.get("DriverStatus") or []).get("driver-type", "classic (" + str(info.get("Driver")) + ")")
    record("docker daemon", "PASS" if info.get("OSType") == "linux" else "FAIL",
           "server %s, %s/%s, %s, image store %s, %s CPUs, %.1f GiB" % (
               info.get("ServerVersion"), info.get("OSType"), info.get("Architecture"),
               info.get("OperatingSystem"), store, info.get("NCPU", 0), info.get("MemTotal", 0) / 2.0 ** 30))
    return info.get("OSType") == "linux"


def inspect_image(ref, lock_platform):
    """Require platform-aware metadata; never interpret an index Id as config Id."""
    code, out, err = run(["docker", "image", "inspect", "--platform", lock_platform, ref], timeout=30)
    if code:
        raise ValueError("platform-aware inspect failed for %s: %s" % (ref, err[-300:]))
    data = json.loads(out)[0]
    descriptor = data.get("Descriptor") or {}
    if descriptor.get("mediaType") not in ("application/vnd.oci.image.manifest.v1+json",
                                           "application/vnd.docker.distribution.manifest.v2+json"):
        raise ValueError("platform manifest descriptor unavailable; classic-store config-ID mapping is not verified")
    return data


def image_identity(data):
    layers = data.get("RootFS", {}).get("Layers")
    if (not isinstance(layers, list) or not layers
            or any(not isinstance(x, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", x) for x in layers)
            or not isinstance(data.get("Config"), dict) or not data["Config"]):
        raise ValueError("missing image configuration or filesystem identity")
    descriptor = data.get("Descriptor") or {}
    platform_data = {"os": data.get("Os"), "architecture": data.get("Architecture"),
                     "variant": data.get("Variant", "")}
    declared = descriptor.get("platform") or {}
    if (platform_data != {"os": "linux", "architecture": "amd64", "variant": ""}
            or declared.get("os") != "linux" or declared.get("architecture") != "amd64"
            or declared.get("variant", "")):
        raise ValueError("image must be the validated linux/amd64 platform")
    return {"platform": platform_data, "manifest_digest": descriptor.get("digest"),
            # This is an inspect-config fingerprint, NOT an OCI config-blob digest.
            # The immutable manifest above authenticates the full OCI config blob.
            "runtime_config_sha256": canonical_sha(data["Config"]),
            "rootfs_layers": layers,
            "rootfs_sha256": hashlib.sha256("\n".join(layers).encode()).hexdigest()}


def check_images(config, lock_path, evidence=None, capture=False):
    """Only original refs or their authenticated platform manifests are accepted.

    Config-ID-only transfers fail closed: no layer-only fallback, no new image
    identities inferred from a new lock. An alternate lock may change ONLY the
    three execution refs to their original platform manifests.
    """
    IMAGE_IDENTITIES.clear()
    try:
        baseline = json.loads(DEFAULT_LOCK.read_text())
        if config.get("platform") != "linux/amd64":
            raise ValueError("vessel diagnostics require the existing AMD64 benchmark")
        if {k: v for k, v in config.items() if k not in IMAGE_KEYS} != {
                k: v for k, v in baseline.items() if k not in IMAGE_KEYS}:
            raise ValueError("alternate lock changed benchmark fields other than execution image refs")
        if capture and config != baseline:
            raise ValueError("capture requires the original validated lock and original image refs")
        if not capture and (not isinstance(evidence, dict) or evidence.get("schema_version") != 1
                            or evidence.get("baseline_lock_sha256") != canonical_sha(baseline)):
            raise ValueError("matching source-host image evidence is required (VESSEL_IMAGE_EVIDENCE)")
        for key in IMAGE_KEYS:
            ref = config[key]
            expected_manifest = AMD64_MANIFESTS[key]
            if ref not in (baseline[key], expected_manifest):
                raise ValueError("%s: unverified transfer reference (config-ID-only stores are unsupported)" % key)
            identity = image_identity(inspect_image(ref, config["platform"]))
            if identity["manifest_digest"] != expected_manifest:
                raise ValueError("%s: platform manifest differs from the original pinned image" % key)
            if identity["rootfs_sha256"] != AMD64_ROOTFS[baseline[key]]:
                raise ValueError("%s: filesystem differs from the validated image" % key)
            if not capture:
                source = evidence.get("images", {}).get(key, {})
                if source.get("original_ref") != baseline[key] or source.get("identity") != identity:
                    raise ValueError("%s: source configuration/platform/filesystem evidence mismatch" % key)
            IMAGE_IDENTITIES[key] = {"original_ref": baseline[key], "execution_ref": ref, "identity": identity}
            record("image " + key, "PASS", "%s manifest=%s config-fingerprint=%s rootfs=%s" % (
                ref, expected_manifest, identity["runtime_config_sha256"], identity["rootfs_sha256"]))
        return True
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        record("image provenance", "FAIL", str(error))
        return False


def check_architecture_probe(config):
    name = "vessel-arch-" + uuid.uuid4().hex
    try:
        code, out, err = run(["docker", "run", "--rm", "--name", name, "--pull", "never",
                              "--platform", config["platform"], "--network", "none", "--read-only",
                              "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                              "--cpus", "1", "--memory", "768m", "--pids-limit", "64",
                              "--user", "1000:1000", config["oracle_image"], "uname", "-m"], timeout=180)
        record("container architecture", "PASS" if code == 0 and out == "x86_64" else "FAIL",
               "expected x86_64: rc=%s out=%r err=%s; jailed emulation validation is still required"
               % (code, out, err[-300:]))
    finally:
        code, _, err = run(["docker", "rm", "-fv", name], timeout=20)
        if code and "No such container" not in err:
            record("architecture probe cleanup", "FAIL", "could not confirm removal of " + name)


# Separate trust domain: these records authenticate a local rebuild, never the
# Windows manifests. Keep image_identity/check_images above strict and unchanged.
VALIDATION_MAX_AGE = 24 * 60 * 60
DOCKERFILES = ("docker/linux-utilities/Dockerfile", "docker/linux-utilities/Rust.Dockerfile")


def required_run(argv):
    code, out, err = run(argv, timeout=180)
    if code:
        raise ValueError("command failed: %s\n%s" % (" ".join(argv), err))
    return out


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new_json(path, value):
    with external_path(path).open("x", encoding="utf-8") as output:
        output.write(json.dumps(value, indent=2) + "\n")


def vessel_environment():
    if sys.flags.optimize or os.environ.get("PYTHONOPTIMIZE", "0") not in ("", "0"):
        raise ValueError("Python assertion checks must be enabled for validation")
    if required_run(["git", "status", "--porcelain", "--untracked-files=no"]):
        raise ValueError("vessel-built validation requires a clean tracked checkout")
    info = json.loads(required_run(["docker", "info", "--format", "{{json .}}"]))
    context = required_run(["docker", "context", "show"])
    return {
        "revision": required_run(["git", "rev-parse", "HEAD"]),
        "dockerfiles": {p: file_sha(ROOT / p) for p in DOCKERFILES},
        "host": [platform.system(), platform.release(), platform.machine()],
        "docker": {k: info.get(k) for k in ("ID", "ServerVersion", "OSType", "Architecture",
                    "KernelVersion", "OperatingSystem", "Driver", "DriverStatus", "NCPU", "MemTotal",
                    "SecurityOptions", "DockerRootDir")},
        "docker_version": json.loads(required_run(["docker", "version", "--format", "{{json .}}"])),
        "buildx": required_run(["docker", "buildx", "version"]),
        "context": json.loads(required_run(["docker", "context", "inspect", context])),
        "endpoint_overrides": {k: os.environ.get(k, "") for k in ("DOCKER_HOST", "DOCKER_CONTEXT")},
        "emulation": emulation_identity(),
    }


def rebuilt_identity(data):
    # Docker sometimes omits Descriptor.platform. Only this opt-in path permits
    # absence; conflicting metadata is still rejected by the original checker.
    normalized = dict(data, Descriptor=dict(data.get("Descriptor") or {}))
    if "platform" not in normalized["Descriptor"]:
        normalized["Descriptor"]["platform"] = {
            "os": data.get("Os"), "architecture": data.get("Architecture"),
            "variant": data.get("Variant", "")}
    identity = image_identity(normalized)
    for digest in (data.get("Id"), identity["manifest_digest"]):
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("missing Docker ID or platform manifest digest")
    identity["docker_id"] = data["Id"]  # may be an index; never called a config digest
    return identity


def probe_reference(ref, command=None, mounts=()):
    name = "vessel-ref-" + uuid.uuid4().hex
    try:
        out = required_run(["docker", "run", "--rm", "--name", name, "--pull", "never",
                            "--platform", "linux/amd64", "--network", "none", "--read-only",
                            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                            "--cpus", "1", "--memory", "768m", "--pids-limit", "64",
                            "--user", "1000:1000"] + list(mounts) + [ref] + (command or ["uname", "-m"]))
        if command is None and out != "x86_64":
            raise ValueError("immutable execution reference did not execute as x86_64")
        return out
    finally:
        code, _, err = run(["docker", "rm", "-fv", name], timeout=20)
        if code and "No such container" not in err:
            raise ValueError("could not confirm probe cleanup: " + name)


def emulation_identity():
    # These read-only mounts refer to the Docker VM, not the macOS controller.
    # No socket, privileges or candidate code are admitted to this trusted probe.
    import docker_benchmark
    ref = docker_benchmark.settings()["compiler_image"]
    script = ("import json,pathlib; p=pathlib.Path('/binfmt'); "
              "print(json.dumps(dict(boot_id=pathlib.Path('/boot-id').read_text(), "
              "registrations={f.name:f.read_text() for f in sorted(p.iterdir()) "
              "if f.name != 'register'}),sort_keys=True))")
    identity = json.loads(probe_reference(ref, ["python3", "-I", "-c", script], [
        "--mount", "type=bind,src=/proc/sys/fs/binfmt_misc,dst=/binfmt,readonly",
        "--mount", "type=bind,src=/proc/sys/kernel/random/boot_id,dst=/boot-id,readonly"]))
    interpreters = {}
    for registration in identity["registrations"].values():
        for line in registration.splitlines():
            if line.startswith("interpreter "):
                path = line[len("interpreter "):]
                if not path.startswith("/") or any(c in path for c in ",\n\r"):
                    raise ValueError("unsupported binfmt interpreter path")
                interpreters[path] = probe_reference(ref, ["python3", "-I", "-c",
                    "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('/emulator').read_bytes()).hexdigest())"],
                    ["--mount", "type=bind,src=" + path + ",dst=/emulator,readonly"])
    identity["interpreter_sha256"] = interpreters
    return identity


def git_dockerfile_hashes(revision):
    required_run(["git", "cat-file", "-e", revision + "^{commit}"])
    hashes = {}
    for name in DOCKERFILES:
        # Hash raw Git blob bytes: run() strips whitespace and cannot be used here.
        result = subprocess.run(["git", "show", revision + ":" + name], cwd=str(ROOT),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if result.returncode:
            raise ValueError("cannot read build-revision Dockerfile: " + name)
        hashes[name] = hashlib.sha256(result.stdout).hexdigest()
    return hashes


def check_jailed_execution():
    # Reuse the real Docker controls for all three languages under unchanged limits.
    command = [shutil.which("python3") or sys.executable, "-B", "-m", "unittest", "-f", "-v",
               "tests.test_docker_benchmark_integration.DockerIntegration.test_nonroot_chroot_and_no_controller_assets",
               "tests.test_cross_language_docker.CrossLanguageDocker.test_real_rust_and_python_runtime_isolation_and_io"]
    code, out, err = run(command, timeout=600)
    if code:
        raise ValueError("fresh jailed execution failed; infrastructure failure: " + out + err)


def repository_execution_ref(ref, data, identity):
    # RepoDigests can name an index rather than the selected platform manifest.
    # Neither digest shape nor inspect metadata alone proves local resolution.
    repository = ref.rsplit(":", 1)[0]  # capture's custom refs have explicit tags
    candidates = list(data.get("RepoDigests") or [])
    candidates += [repository + "@" + identity["manifest_digest"],
                   repository + "@" + identity["docker_id"]]
    for candidate in dict.fromkeys(candidates):
        if not isinstance(candidate, str) or not re.fullmatch(
                r"[^\s@]+@sha256:[0-9a-f]{64}", candidate):
            continue
        try:
            resolved = rebuilt_identity(inspect_image(candidate, "linux/amd64"))
        except (ValueError, KeyError, TypeError, IndexError):
            continue
        if resolved == identity:
            return candidate
    raise ValueError("no locally resolvable immutable repository digest matches " + ref)


def prepare_vessel_lock(directory, build_record):
    directory = external_path(directory)
    baseline = json.loads(DEFAULT_LOCK.read_text())
    build = json.loads(external_path(build_record).read_text())
    if not check_docker("linux/amd64"):
        raise ValueError("local Linux Docker required")
    environment = vessel_environment()
    verify_build_record(build, baseline, environment)
    directory.mkdir(exist_ok=False)
    config = dict(baseline)
    images = {}
    refs = {"oracle_image": "agentic-linux-utilities:latest",
            "compiler_image": baseline["compiler_image"],
            "rust_compiler_image": "agentic-linux-utilities-rust:latest"}
    for key, ref in refs.items():
        data = inspect_image(ref, "linux/amd64")
        identity = rebuilt_identity(data)
        # Keep the pinned Python base; custom images need a Docker-resolvable
        # repository digest, not an assumed runnable bare index/config ID.
        selected = ref if key == "compiler_image" else repository_execution_ref(ref, data, identity)
        if rebuilt_identity(inspect_image(selected, "linux/amd64")) != identity:
            raise ValueError("selected immutable reference does not resolve to inspected image")
        if key == "compiler_image" and identity["manifest_digest"] != baseline["base_amd64_manifest"]:
            raise ValueError("pinned AMD64 Python base manifest mismatch")
        probe_reference(selected)
        config[key] = selected
        images[key] = {"execution_ref": selected, "identity": identity, "inspect": data,
                       "history": required_run(["docker", "history", "--no-trunc", "--format", "{{json .}}", selected])}
        if key == "oracle_image":
            metadata = {name: probe_reference(selected, ["cat", "/provenance/" + name])
                        for name in ("base-image.txt", "build-architecture.txt", "packages.txt", "compiler.txt")}
            if metadata["base-image.txt"] != baseline["compiler_image"] or metadata["build-architecture.txt"] != "amd64":
                raise ValueError("oracle embedded build inputs differ from pinned AMD64 inputs")
            images[key]["build_metadata"] = metadata
    provenance = {"schema_version": 1, "mode": "vessel-built",
                  "baseline_lock_sha256": canonical_sha(baseline), "lock_sha256": canonical_sha(config),
                  "environment": environment, "images": images,
                  "build_record": build,
                  "build_record_status": "operator supplied; image history is not a signed build attestation",
                  "pinned_bases": [baseline["compiler_image"], baseline["rust_base_image"]],
                  "captured_at": time.time(), "windows_byte_identity_claimed": False}
    write_new_json(directory / "lock.json", config)
    write_new_json(directory / "provenance.json", provenance)
    print("Captured only; independent validation and approval still required: " + str(directory))


def verify_build_record(build, baseline, environment):
    if (not isinstance(build, dict) or not re.fullmatch(r"[0-9a-f]{40}", build.get("revision", ""))
            or build.get("dockerfiles") != environment["dockerfiles"]
            or build.get("pinned_bases") != [baseline["compiler_image"], baseline["rust_base_image"]]
            or not all(isinstance(build.get(k), str) and build[k].strip()
                       for k in ("oracle_build_command", "rust_build_command", "builder_description"))):
        raise ValueError("incomplete build record: actual revision, matching Dockerfile hashes, pinned bases, commands and builder description required")
    if git_dockerfile_hashes(build["revision"]) != build["dockerfiles"]:
        raise ValueError("build revision Dockerfiles differ from recorded hashes")


def vessel_binding(config, lock_path, provenance_path):
    external_path(lock_path)
    provenance = json.loads(external_path(provenance_path).read_text())
    baseline = json.loads(DEFAULT_LOCK.read_text())
    if ({k: v for k, v in config.items() if k not in IMAGE_KEYS} !=
            {k: v for k, v in baseline.items() if k not in IMAGE_KEYS}):
        raise ValueError("vessel lock changed non-image benchmark fields")
    if (provenance.get("schema_version") != 1 or provenance.get("mode") != "vessel-built"
            or provenance.get("baseline_lock_sha256") != canonical_sha(baseline)
            or provenance.get("lock_sha256") != canonical_sha(config)
            or provenance.get("windows_byte_identity_claimed") is not False
            or provenance.get("pinned_bases") != [baseline["compiler_image"], baseline["rust_base_image"]]):
        raise ValueError("missing or mismatched local build provenance")
    environment = vessel_environment()
    verify_build_record(provenance.get("build_record"), baseline, environment)
    if stable_environment(provenance.get("environment", {})) != stable_environment(environment):
        raise ValueError("checkout or Docker environment changed since provenance capture")
    import docker_benchmark
    if docker_benchmark.settings() != config:
        raise ValueError("active Docker adapter lock differs from vessel lock")
    IMAGE_IDENTITIES.clear()
    for action, language in (("case", "c"), ("compile", "c"), ("compile", "rust"), ("compile", "py")):
        command = docker_benchmark.command(action, "vessel-binding", language)
        chosen = "oracle_image" if action == "case" else "rust_compiler_image" if language == "rust" else "compiler_image"
        if command[command.index("-i") + 1] != config[chosen] or command[command.index("--platform") + 1] != "linux/amd64":
            raise ValueError("Docker adapter execution reference mismatch")
    for key in IMAGE_KEYS:
        ref = config[key]
        identity = rebuilt_identity(inspect_image(ref, "linux/amd64"))
        expected = provenance.get("images", {}).get(key, {})
        if (expected.get("execution_ref") != ref or expected.get("identity") != identity
                or rebuilt_identity(expected.get("inspect", {})) != identity or not expected.get("history")):
            raise ValueError("active image changed: " + key)
        if key == "compiler_image" and (ref != baseline[key] or identity["manifest_digest"] != baseline["base_amd64_manifest"]):
            raise ValueError("pinned Python base changed")
        if key == "oracle_image":
            metadata = expected.get("build_metadata", {})
            if (metadata.get("base-image.txt") != baseline["compiler_image"]
                    or metadata.get("build-architecture.txt") != "amd64"
                    or not metadata.get("packages.txt") or not metadata.get("compiler.txt")):
                raise ValueError("missing or mismatched embedded oracle build provenance")
        IMAGE_IDENTITIES[key] = {"execution_ref": ref, "identity": identity}
    return {"lock_sha256": file_sha(lock_path), "provenance_sha256": file_sha(provenance_path),
            "environment": environment, "images": dict(IMAGE_IDENTITIES),
            "execution_profile": docker_benchmark.execution_profile()}


def validation_commands(directory, config):
    python = shutil.which("python3") or sys.executable
    commands = [["bash", str(ROOT / "docker/linux-utilities/run.sh"), config["oracle_image"], str(directory / "oracle"), "linux/amd64"],
                [python, "-B", "-m", "unittest", "-f", "-v", "tests.test_docker_benchmark_integration", "tests.test_cross_language_docker", "tests.test_cross_language_static"],
                [python, "-B", str(SCRIPTS / "validate_docker_adapter.py"), "--output", str(directory / "calibration")]]
    for selector in DEFAULT_SELECTORS:
        commands.append([python, "-B", str(SCRIPTS / "validate_docker_entrypoints.py"), "--utility", selector, "--output", str(directory / ("entry-" + selector))])
    commands.append([python, "-B", str(SCRIPTS / "validate_linux_static.py"), "--output", str(directory / "static")])
    return commands


def validation_files(directory):
    return {p.relative_to(directory).as_posix(): file_sha(p) for p in sorted(directory.rglob("*"))
            if p.is_file() and p != directory / "validation.json"}


def required_validation_files(directory, config):
    import docker_benchmark
    return ({"prerequisites.log", "oracle/validation.log", "calibration/summary.json", "static/summary.json"}
            | {"step-%02d.log" % i for i in range(len(validation_commands(directory, config)))}
            | {"oracle/validated/c-%s/validation.json" % u for u in ("cp", "mv", "mkdir", "sort")}
            | {"calibration/%s-%s.json" % (s, kind) for s in docker_benchmark.SELECTORS for kind in ("public", "heldout")}
            | {"entry-%s/%s.json" % (s, kind) for s in DEFAULT_SELECTORS for kind in ("summary", "public", "heldout")})


def checked_validation(path, binding, config):
    path = external_path(path)
    report = json.loads(path.read_text())
    if (report.get("schema_version") != 1 or report.get("passed") is not True
            or report.get("generation_invoked") is not False or report.get("infrastructure_failure") is not False
            or stable_binding(report.get("binding", {"environment": {}})) != stable_binding(binding)
            or not 0 <= time.time() - report.get("completed_at", 0) <= VALIDATION_MAX_AGE
            or report.get("commands") != validation_commands(path.parent, config)
            or report.get("returncodes") != [0] * len(validation_commands(path.parent, config))
            or report.get("files") != validation_files(path.parent)
            or not required_validation_files(path.parent, config) <= set(report.get("files", {}))
            or not required_validation_checks() <= {r["check"] for r in report.get("checks", []) if r["status"] == "PASS"}
            or any(r["status"] == "FAIL" for r in report["checks"])):
        raise ValueError("missing, incomplete, stale or mismatched independent validation evidence")
    return report


def required_validation_checks():
    return {"python3 controller imports", "bash", "bash -n run_experiment.sh",
            "bash -n run_lineage_experiment.sh", "bash -n vessel_smoke_stage.sh",
            "timeout", "container architecture"} | {
                prefix + selector for selector in DEFAULT_SELECTORS
                for prefix in ("docker toolchain ", "judging inputs ", "checkpoint 000 ")}


def validate_vessel(directory, config, lock_path, provenance_path, args):
    global VALIDATION_LOG
    directory = external_path(directory)
    binding = vessel_binding(config, lock_path, provenance_path)
    directory.mkdir(exist_ok=False)
    report = {"schema_version": 1, "passed": False, "binding": binding,
              "diagnostic_only": True, "formal_result": False,
              "commands": validation_commands(directory, config), "generation_invoked": False, "returncodes": []}
    VALIDATION_LOG = directory / "prerequisites.log"
    try:
        for check, arguments in ((check_python_and_bash, ()), (check_timeout, ()),
                                 (check_architecture_probe, (config,)),
                                 (check_toolchains, (shutil.which("python3") or sys.executable, DEFAULT_SELECTORS)),
                                 (check_checkpoints, (shutil.which("python3") or sys.executable, DEFAULT_SELECTORS, args, "x86_64"))):
            check(*arguments)
            if any(r["status"] == "FAIL" for r in RESULTS):
                raise ValueError("validation prerequisite failed; infrastructure/environment failure")
        for index, command in enumerate(report["commands"]):
            print("Validation %d/%d: %s" % (index + 1, len(report["commands"]), " ".join(command)), flush=True)
            # Full logs, no truncated run() output. Existing inner limits remain unchanged.
            with (directory / ("step-%02d.log" % index)).open("x") as log:
                done = subprocess.run(command, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
            report["returncodes"].append(done.returncode)
            if done.returncode:
                raise ValueError("validation step %d failed (rc=%d); infrastructure/environment failure, not a candidate verdict" % (index, done.returncode))
        if vessel_binding(config, lock_path, provenance_path) != binding:
            raise ValueError("environment changed during validation")
        if not required_validation_files(directory, config) <= set(validation_files(directory)):
            raise ValueError("validation returned success without all required reports")
        report["passed"] = True
    finally:
        VALIDATION_LOG = None
        report.update(completed_at=time.time(), checks=list(RESULTS), files=validation_files(directory),
                      infrastructure_failure=not report["passed"])
        write_new_json(directory / "validation.json", report)
    print("Independent checks passed; review reports before explicit approval. No generation authorized yet.")


def check_vessel_built(config, lock_path, args, require_approval=True):
    try:
        binding = vessel_binding(config, lock_path, args.vessel_provenance)
        checked_validation(args.vessel_validation, binding, config)
        scope = approval_scope(args, binding)
        if require_approval:
            approval = json.loads(external_path(args.vessel_approval).read_text())
            if approval != {"schema_version": 1, "validation_sha256": file_sha(args.vessel_validation),
                            "binding_sha256": canonical_sha(stable_binding(binding)), "scope": scope}:
                raise ValueError("matching explicit " + scope + " approval required")
            check_jailed_execution()
            if vessel_binding(config, lock_path, args.vessel_provenance) != binding:
                raise ValueError("environment changed during fresh jailed execution")
        boot_id = binding['environment'].get('emulation', {}).get('boot_id', 'unavailable')
        record("vessel-built independent validation", "PASS",
               "matching local rebuild evidence; no Windows byte-identity claim; scope=%s boot_id=%s" % (scope, boot_id))
        return True
    except (OSError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError) as error:
        record("vessel-built independent validation", "FAIL", str(error))
        return False


def check_toolchains(python3, selectors):
    for selector in selectors:
        code, out, err = run([python3, str(SCRIPTS / "docker_benchmark.py"), "preflight", "--utility", selector],
                             timeout=300)
        record("docker toolchain " + selector, "PASS" if code == 0 else "FAIL",
               (out or err)[-300:], None if code == 0 else "see docker_benchmark.py preflight output")


def check_ollama(url, models, num_ctx):
    parts = urlsplit(url)
    if (parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "localhost", "::1")
            or parts.path not in ("", "/") or parts.query or parts.fragment or parts.username or parts.password):
        record("ollama url", "FAIL", "URL is not a credential-free loopback native Ollama root",
               "use http://127.0.0.1:11434 (native API, never /v1)")
        return
    base = url.rstrip("/")
    try:
        version = http_json(base + "/api/version")
        tags = http_json(base + "/api/tags")
        if not isinstance(version.get("version"), str) or not version["version"].strip():
            raise ValueError("Ollama version metadata is missing")
    except Exception as error:  # noqa: BLE001 - any failure is a clear stop
        record("ollama api", "FAIL", "%s unreachable: %s" % (base, error),
               "start the existing Ollama service; preflight does not start or modify it")
        return
    record("ollama api", "PASS", "%s version %s (native /api, no inference)" % (base, version.get("version")))
    installed = dict((entry.get("name"), entry) for entry in tags.get("models", []))
    for role, model in models:
        if not model.startswith("ollama_chat/"):
            record("model " + role, "FAIL", "%s does not use the native ollama_chat/ transport" % model)
            continue
        name = model.split("/", 1)[1]
        entry = installed.get(name)
        if entry is None:
            record("model " + role, "FAIL", "%s not installed (have: %s)" % (name, ", ".join(sorted(installed))),
                   "ollama pull %s  (operator decision; preflight never pulls)" % name)
            continue
        try:
            show = http_json(base + "/api/show", {"model": name})
        except Exception as error:  # noqa: BLE001
            record("model " + role, "FAIL", "/api/show failed for %s: %s" % (name, error))
            continue
        context = [value for key, value in (show.get("model_info") or {}).items() if key.endswith(".context_length")]
        details = entry.get("details") or {}
        digest = entry.get("digest")
        if (not isinstance(digest, str) or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", digest)
                or type(entry.get("size")) is not int or entry["size"] <= 0
                or not details.get("parameter_size") or not details.get("quantization_level")
                or not context or any(type(x) is not int or x <= 0 for x in context)):
            record("model " + role, "FAIL", "%s is available but required identity/context metadata is invalid or missing" % name)
            continue
        MODEL_IDENTITIES[role] = {
            "name": name, "digest": digest, "size": entry["size"], "details": details,
            "context_lengths": context, "definition_sha256": canonical_sha(show),
            "identity_status": "observed; not verified against a historical digest",
        }
        detail = "%s available; observed digest=%s size=%s params=%s quant=%s context_length=%s modified=%s; historical identity unverified" % (
            name, entry.get("digest"), entry.get("size"), details.get("parameter_size"),
            details.get("quantization_level"), context[0] if context else "?", entry.get("modified_at"))
        too_small = bool(num_ctx and int(num_ctx) > min(context))
        record("model " + role, "FAIL" if too_small else "PASS",
               detail + (" -- num_ctx %s exceeds context_length" % num_ctx if too_small else ""))


def check_settings(args):
    sys.path.insert(0, str(SCRIPTS))
    import aider_settings
    if args.temperature is None:
        record("model settings", "WARN", "architect sampling not supplied -> UNRESOLVED; editor pinning still checked")
    try:
        settings = aider_settings.build_model_settings(
            args.architect_model, args.editor_model, args.temperature if args.temperature is not None else 0,
            top_p=args.top_p, sampling_seed=args.sampling_seed, max_tokens=args.max_tokens,
            num_ctx=args.num_ctx, architect_think=args.architect_think, editor_edit_format="editor-diff")
    except (TypeError, ValueError) as error:
        record("model settings", "FAIL", str(error))
        return
    editor = settings[1]
    pinned = (editor["extra_params"].get("temperature") == 0.0 and editor["extra_params"].get("seed") == 0
              and editor["editor_edit_format"] == "editor-diff")
    record("editor pinning", "PASS" if pinned else "FAIL",
           "temperature=%s seed=%s edit_format=%s" % (editor["extra_params"].get("temperature"),
                                                     editor["extra_params"].get("seed"), editor["editor_edit_format"]))
    if args.temperature is not None:
        record("architect settings", "INFO", "%s sha256=%s" % (json.dumps(settings[0]["extra_params"], sort_keys=True),
                                                             aider_settings.settings_sha256(settings)))


def check_checkpoints(python3, selectors, args, lock_arch):
    sys.path.insert(0, str(SCRIPTS))
    from linux_utilities_catalog import suite_root
    for selector in selectors:
        manifest = json.loads((ROOT / "experiments/utilities" / (selector + ".json")).read_text())
        suite = suite_root(ROOT, selector)
        missing = [name for name in ("engine.py", "runner.py", "props.py", "config.py", "config.json",
                                     "suites/linux.json.gz", "suites/MANIFEST.json",
                                     "heldout/heldout_cases.json.gz") if not (suite / name).is_file()]
        missing += [name for name in ("scripts/docker_benchmark_worker.py", "scripts/python_candidate.py",
                                      manifest["judge"]) if not (ROOT / name).is_file()]
        frozen = json.loads((suite / "suites/MANIFEST.json").read_text()) if not missing else {}
        corpus_arch = frozen.get("environment", {}).get("architecture")
        if missing or corpus_arch != lock_arch:
            record("judging inputs " + selector, "FAIL", "missing=%s corpus_arch=%s lock_arch=%s"
                   % (missing, corpus_arch, lock_arch), "the corpus is validated only for its recorded architecture")
        else:
            record("judging inputs " + selector, "PASS", "%s public+held-out corpora, runtime, %s corpus" % (suite.name, corpus_arch))
        plan_args = [python3, str(SCRIPTS / "lineage_plan.py"), "--repo", str(ROOT), "--utility", selector,
                     "--model", args.architect_model, "--editor-model", args.editor_model,
                     "--editor-edit-format", "editor-diff", "--remote-base-url", args.ollama_url]
        code, stages, err = run(plan_args + ["--emit", "stages"])
        row = stages.splitlines()[0].split("\x1f") if code == 0 and stages else []
        if len(row) != 7 or row[0] != "000" or row[3] != "new" or row[5] != "":
            record("checkpoint 000 " + selector, "FAIL", "plan did not resolve a clean stage 000: %s" % (err or row))
            continue
        code, plan_text, err = run(plan_args + ["--emit", "plan"])
        plan = json.loads(plan_text)
        code_cc, _, err_cc = run([python3, str(SCRIPTS / "docker_benchmark.py"), "check-commands", "--utility", selector,
                                  "--build-command", plan["build_command"], "--feature-command", row[4],
                                  "--extra-command", plan["extra_test_command"],
                                  "--base-command", plan.get("base_test_command") or ""])
        temp = tempfile.mkdtemp(prefix="vessel-preflight-")
        try:
            code_b, built, err_b = run([python3, str(SCRIPTS / "stage_test_bundle.py"), "--repo", str(ROOT),
                                        "--utility", selector, "--checkpoint", "000",
                                        "--output", os.path.join(temp, "bundle"), "--emit", "fingerprint"])
            code_r, _, err_r = run([python3, str(SCRIPTS / "prompt_render.py"), "--repo", str(ROOT),
                                    "--prompt", row[2], "--output", os.path.join(temp, "prompt.md")])
            rendered = os.path.getsize(os.path.join(temp, "prompt.md")) if code_r == 0 else 0
        finally:
            shutil.rmtree(temp, ignore_errors=True)
        code_i, _, err_i = run([python3, str(SCRIPTS / "check_heldout_isolation.py"), "--utility", selector], timeout=300)
        code_g, _, err_g = run([python3, str(SCRIPTS / "checkpoint_boundary_gate.py"), "--repo", str(ROOT),
                                "--utility", selector, "--checkpoint", "000", "--emit", "matrix"])
        problems = []
        if code_cc != 0:
            problems.append("canonical commands rejected: " + err_cc[-200:])
        if code_b != 0 or built != row[6]:
            problems.append("bundle fingerprint %s != planned %s %s" % (built, row[6], err_b[-200:]))
        if not rendered:
            problems.append("prompt render failed: " + err_r[-200:])
        if code_i != 0:
            problems.append("held-out isolation check failed: " + err_i[-200:])
        if code_g != 0:
            problems.append("boundary matrix failed: " + err_g[-200:])
        record("checkpoint 000 " + selector, "FAIL" if problems else "PASS",
               "; ".join(problems) if problems else
               "prompt %s (%d bytes rendered), bundle %s, canonical commands, isolation ok, boundary matrix ok"
               % (row[2], rendered, built[:16]))


def main(argv=None):
    RESULTS.clear()
    MODEL_IDENTITIES.clear()
    IMAGE_IDENTITIES.clear()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--selector", action="append", choices=DEFAULT_SELECTORS)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--architect-model", default="ollama_chat/qwen3.8:27b")
    parser.add_argument("--editor-model", default="ollama_chat/qwen3-coder-next:latest")
    parser.add_argument("--temperature")
    parser.add_argument("--architect-think")
    parser.add_argument("--sampling-seed")
    parser.add_argument("--num-ctx")
    parser.add_argument("--max-tokens")
    parser.add_argument("--top-p")
    parser.add_argument("--expected-aider-version", default=EXPECTED_AIDER)
    parser.add_argument("--allow-dirty", action="store_true", help="report, but do not fail on, tracked changes")
    parser.add_argument("--skip-ollama", action="store_true", help="development hosts only; never on vessel")
    parser.add_argument("--skip-aider", action="store_true", help="development hosts only; never on vessel")
    parser.add_argument("--json-report", type=Path)
    parser.add_argument("--image-evidence", type=Path, default=os.environ.get("VESSEL_IMAGE_EVIDENCE"))
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--capture-image-evidence", type=Path,
                        help="original Docker host only: write fresh identity metadata outside the repo; no archive")
    parser.add_argument("--image-mode", choices=("original", "vessel-built"), default="original")
    parser.add_argument("--diagnostic-rosetta", action="store_true",
                        help="non-formal vessel-built diagnostics only: omit the jail RLIMIT_AS cap")
    parser.add_argument("--vessel-provenance", type=Path, default=os.environ.get("VESSEL_BUILT_PROVENANCE"))
    parser.add_argument("--vessel-validation", type=Path, default=os.environ.get("VESSEL_VALIDATION"))
    parser.add_argument("--vessel-approval", type=Path, default=os.environ.get("VESSEL_APPROVAL"))
    parser.add_argument("--approval-scope", choices=("diagnostic-only", "formal-vessel-8g"),
                        default="diagnostic-only", help="explicit scope; formal requires fresh vessel-8g evidence")
    parser.add_argument("--build-record", type=Path)
    actions.add_argument("--prepare-vessel-lock", type=Path, metavar="NEW_DIRECTORY")
    actions.add_argument("--validate-vessel-built", type=Path, metavar="NEW_DIRECTORY")
    actions.add_argument("--approve-vessel-validation", type=Path, metavar="NEW_APPROVAL_FILE")
    actions.add_argument("--verify-vessel-built", action="store_true", help="recheck approval and jailed execution; no model checks")
    args = parser.parse_args(argv)
    if args.diagnostic_rosetta and args.image_mode != "vessel-built":
        parser.error("--diagnostic-rosetta requires --image-mode vessel-built")
    if os.environ.get("VESSEL_DIAGNOSTIC_ROSETTA", "0") != "0" and not args.diagnostic_rosetta:
        parser.error("inherited diagnostic profile requires explicit --diagnostic-rosetta")
    os.environ["VESSEL_DIAGNOSTIC_ROSETTA"] = "1" if args.diagnostic_rosetta else "0"
    vessel_action = args.prepare_vessel_lock or args.validate_vessel_built or args.approve_vessel_validation or args.verify_vessel_built
    if vessel_action and args.image_mode != "vessel-built":
        parser.error("vessel-built actions require explicit --image-mode vessel-built")
    if args.capture_image_evidence and args.image_mode != "original":
        parser.error("source-host capture belongs only to original image mode")
    try:
        # Check explicit tempfile candidates before tempfile can probe them by writing.
        for name in ("TMPDIR", "TEMP", "TMP"):
            if os.environ.get(name):
                external_path(os.environ[name])
        external_path(tempfile.gettempdir())
        if args.json_report:
            args.json_report = external_path(args.json_report)
            if args.json_report.exists():
                raise ValueError("preflight report must be a new file")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    selectors = tuple(args.selector or DEFAULT_SELECTORS)
    python3 = shutil.which("python3") or sys.executable

    # These actions return before all Aider/Ollama checks, including --version.
    if vessel_action:
        try:
            if args.prepare_vessel_lock:
                prepare_vessel_lock(args.prepare_vessel_lock, args.build_record)
            else:
                import docker_benchmark
                lock_path = Path(os.environ["LINUX_BENCHMARK_LOCK"])
                if not lock_path.is_absolute():
                    raise ValueError("LINUX_BENCHMARK_LOCK must be absolute")
                config = docker_benchmark.settings()
                if not check_docker(config["platform"]):
                    raise ValueError("local Linux Docker required")
                if args.verify_vessel_built:
                    return 0 if check_vessel_built(config, lock_path, args) else 1
                elif args.validate_vessel_built:
                    validate_vessel(args.validate_vessel_built, config, lock_path, args.vessel_provenance, args)
                else:
                    if not check_vessel_built(config, lock_path, args, require_approval=False):
                        return 1
                    target = external_path(args.approve_vessel_validation)
                    if external_path(args.vessel_validation).parent in target.parents:
                        raise ValueError("approval must be outside the sealed validation directory")
                    binding = vessel_binding(config, lock_path, args.vessel_provenance)
                    write_new_json(target, {"schema_version": 1, "validation_sha256": file_sha(args.vessel_validation),
                                            "binding_sha256": canonical_sha(stable_binding(binding)),
                                            "scope": approval_scope(args, binding)})
                    print("Approval recorded for " + args.approval_scope + "; fresh pre-generation verification still required.")
            return 0
        except (OSError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError) as error:
            record("vessel-built preparation", "FAIL", str(error))
            return 1

    if args.capture_image_evidence:
        try:
            target = external_path(args.capture_image_evidence)
        except ValueError as error:
            parser.error(str(error))
        if target.exists():
            parser.error("image evidence output must be new and outside the repository")
        config = json.loads(DEFAULT_LOCK.read_text())
        if not check_docker(config["platform"]) or not check_images(config, DEFAULT_LOCK, capture=True):
            return 1
        evidence = {"schema_version": 1, "baseline_lock_sha256": canonical_sha(config),
                    "images": IMAGE_IDENTITIES}
        with target.open("x", encoding="utf-8") as output:
            output.write(json.dumps(evidence, indent=2) + "\n")
        print("Image evidence captured: %s sha256=%s" % (target, hashlib.sha256(target.read_bytes()).hexdigest()))
        return 0

    print("vessel preflight (non-generative; temporary probes and optional report)")
    check_git(args.allow_dirty)
    check_host()
    check_python_and_bash()
    check_timeout()
    if args.skip_aider:
        record("aider", "WARN", "skipped by --skip-aider")
    else:
        check_aider(args.expected_aider_version)
    sys.path.insert(0, str(SCRIPTS))
    lock_path = None
    try:
        import docker_benchmark
        lock_path = docker_benchmark.lock_path()
        if not lock_path.is_absolute():
            raise ValueError("benchmark lock must use an absolute path so controller working directories cannot change its meaning")
        config = docker_benchmark.settings()
        lock_sha = hashlib.sha256(lock_path.read_bytes()).hexdigest()
        record("benchmark lock", "PASS" if os.path.realpath(str(lock_path)) == os.path.realpath(str(DEFAULT_LOCK)) else "WARN",
               "%s platform=%s sha256=%s" % (lock_path, config["platform"], lock_sha))
    except Exception as error:  # noqa: BLE001
        record("benchmark lock", "FAIL", str(error))
        config = None
    evidence = None
    try:
        if args.image_mode == "original" and args.image_evidence:
            evidence = json.loads(args.image_evidence.read_text())
    except (OSError, ValueError) as error:
        record("image evidence", "FAIL", str(error))
    if config and check_docker(config["platform"]):
        images_ok = (check_images(config, lock_path, evidence) if args.image_mode == "original"
                     else check_vessel_built(config, lock_path, args))
        if images_ok:
            check_architecture_probe(config)
            check_toolchains(python3, selectors)
    lock_arch = None if config is None else ("x86_64" if config["platform"] == "linux/amd64" else "aarch64")
    check_settings(args)
    if args.skip_ollama:
        record("ollama api", "WARN", "skipped by --skip-ollama")
    else:
        check_ollama(args.ollama_url, (("architect", args.architect_model), ("editor", args.editor_model)), args.num_ctx)
    check_checkpoints(python3, selectors, args, lock_arch)

    failures = [item for item in RESULTS if item["status"] == "FAIL"]
    skipped = [item for item in RESULTS if "skipped" in item["detail"]]
    summary = {"preflight_passed": not failures and not skipped, "failures": len(failures),
               "selectors": list(selectors), "generation_invoked": False,
               "models": MODEL_IDENTITIES, "images": IMAGE_IDENTITIES,
               "benchmark_lock": config, "benchmark_lock_path": str(lock_path),
               "image_mode": args.image_mode, "image_evidence": evidence,
               "execution_profile": docker_benchmark.execution_profile(),
               "diagnostic_only": True, "formal_result": False,
               "vessel_validation": str(args.vessel_validation) if args.image_mode == "vessel-built" else None,
               "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "checks": RESULTS}
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(summary, indent=2) + "\n")
    print("\n%s: %d failed check(s)%s. No model generation was invoked." % (
        "PREFLIGHT PASSED" if summary["preflight_passed"] else "PREFLIGHT FAILED", len(failures),
        "; checks skipped, so this is not a vessel pass" if skipped else ""))
    return 0 if summary["preflight_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
