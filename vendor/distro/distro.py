"""Minimal stand-in for the `distro` package on OpenHarmony.

ChimeraX only uses distro to describe the host in HTTP user agents and to look up binary
platform tags. HarmonyOS reports itself through /etc/os-release, but that file can be absent in
an app sandbox, so this shim reports a stable identity instead of raising ImportError.
"""

import platform


def _os_release():
    values = {}
    try:
        with open("/etc/os-release", "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "=" not in line:
                    continue
                key, value = line.strip().split("=", 1)
                values[key] = value.strip().strip('"')
    except OSError:
        pass
    return values


def id():
    release = _os_release()
    return release.get("ID", "openharmony")


def name(pretty=False):
    release = _os_release()
    if pretty and release.get("PRETTY_NAME"):
        return release["PRETTY_NAME"]
    return release.get("NAME", "OpenHarmony")


def version(pretty=False, best=False):
    release = _os_release()
    if pretty and release.get("PRETTY_NAME"):
        return release["PRETTY_NAME"]
    return release.get("VERSION_ID", platform.release())


def like():
    release = _os_release()
    return release.get("ID_LIKE", "")


def codename():
    return _os_release().get("VERSION_CODENAME", "")


def id_like():
    return like()


def info():
    return {
        "id": id(),
        "version": version(),
        "like": like(),
        "codename": codename(),
    }
