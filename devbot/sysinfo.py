"""服务器状态（只读）和看门狗：负载、内存、磁盘、被监视的 systemd 服务、Docker 容器。"""
import os
import shutil
import subprocess


def _cmd(args, timeout=10):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return out.returncode, (out.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return -1, ""


def meminfo():
    data = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                data[k] = int(v.split()[0]) // 1024
    except OSError:
        return None
    total, avail = data.get("MemTotal", 0), data.get("MemAvailable", 0)
    return {"总内存MB": total, "可用MB": avail, "使用率%": round(100 * (total - avail) / total) if total else None}


def disk(path="/"):
    try:
        u = shutil.disk_usage(path)
    except OSError:
        return None
    return {"总GB": round(u.total / 2 ** 30, 1), "可用GB": round(u.free / 2 ** 30, 1),
            "使用率%": round(100 * u.used / u.total)}


def uptime_text():
    try:
        secs = float(open("/proc/uptime").read().split()[0])
    except (OSError, ValueError):
        return "?"
    d, h = int(secs // 86400), int(secs % 86400 // 3600)
    return f"{d}天{h}小时"


def service_state(name):
    if not shutil.which("systemctl"):
        return "unknown"
    _, out = _cmd(["systemctl", "is-active", name])
    return out or "unknown"


def docker_containers():
    if not shutil.which("docker"):
        return None
    code, out = _cmd(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"])
    if code != 0:
        return None
    rows = []
    for line in out.splitlines():
        name, _, status = line.partition("\t")
        rows.append({"名称": name, "状态": status})
    return rows


def journal_has(service, text, minutes=12):
    """最近几分钟的服务日志里有没有出现某段文字（用来发现健康助手的 ClawBot 登录过期）。"""
    if not shutil.which("journalctl"):
        return False
    _, out = _cmd(["journalctl", "-u", service, "--since", f"-{minutes}min", "--no-pager", "-o", "cat"], 15)
    return text in out


def status(services):
    try:
        load = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        load = None
    info = {"运行时间": uptime_text(), "负载(1/5/15分钟)": load, "CPU核数": os.cpu_count(),
            "内存": meminfo(), "磁盘/": disk("/"),
            "服务": {s: service_state(s) for s in services}}
    containers = docker_containers()
    if containers is not None:
        info["Docker容器"] = containers
    return info


def status_text(services):
    s = status(services)
    lines = [f"🖥 运行 {s['运行时间']}，负载 {s['负载(1/5/15分钟)']}（{s['CPU核数']} 核）"]
    if s["内存"]:
        lines.append(f"内存：已用 {s['内存']['使用率%']}%，可用 {s['内存']['可用MB']} MB")
    if s["磁盘/"]:
        lines.append(f"磁盘：已用 {s['磁盘/']['使用率%']}%，剩 {s['磁盘/']['可用GB']} GB")
    for name, st in s["服务"].items():
        lines.append(f"{'✅' if st == 'active' else '❌'} {name}：{st}")
    if s.get("Docker容器") is not None:
        bad = [c for c in s["Docker容器"] if not c["状态"].startswith("Up")]
        lines.append(f"🐳 容器 {len(s['Docker容器'])} 个" +
                     (("，没在运行：" + "、".join(c["名称"] for c in bad)) if bad else "，全部在运行"))
    return "\n".join(lines)
