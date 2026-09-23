#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-only
"""
VPSKit - Hysteria2 一键安装/配置脚本

本版本重点：
- 客户端配置全部在 VPS 本地生成，不再调用第三方订阅转换服务。
- 使用 Hysteria2 原生端口范围监听实现端口跳跃。
- 修正 BBR / Brutal / Reno 的配置语义。
- 本地导出：links.txt / mihomo.yaml / sing-box.json / surge.conf。
- 配置向导所有普通输入均支持直接回车采用默认值；首次密码自动生成。
- 修复自签证书目录权限，允许 hysteria 服务用户读取证书/私钥。

项目地址： https://github.com/JoongDa/VPSKit

说明：本脚本仅用于合法的服务器运维、远程访问与网络测试。
请遵守服务器所在地、使用者所在地以及相关网络服务提供商的法律法规和服务条款。
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


SCRIPT_NAME = "VPSKit Hysteria2"
SCRIPT_VERSION = "0.1.6"
GITHUB_REPO = "JoongDa/VPSKit"
GITHUB_BRANCH = "main"
GITHUB_SCRIPT_PATH = "Hysteria2/hy2.py"
RAW_SCRIPT_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_REPO}/"
    f"{GITHUB_BRANCH}/{GITHUB_SCRIPT_PATH}"
)

HY_BIN = Path("/usr/local/bin/hysteria")
HY_CONFIG = Path("/etc/hysteria/config.yaml")
CONFIG_DIR = Path("/etc/hy2config")
SSL_DIR = CONFIG_DIR / "ssl"
AGREE_FILE = CONFIG_DIR / "agree.txt"
NODE_FILE = CONFIG_DIR / "node.json"
LINKS_FILE = CONFIG_DIR / "links.txt"
MIHOMO_FILE = CONFIG_DIR / "mihomo.yaml"
SINGBOX_FILE = CONFIG_DIR / "sing-box.json"
SURGE_FILE = CONFIG_DIR / "surge.conf"
SHORTCUT_FILE = Path("/usr/local/bin/hy2")
INSTALLED_SCRIPT = Path("/usr/local/lib/vpskit/hy2.py")
SUBSCRIPTION_DIR = Path("/var/lib/vpskit/subscription")
SUBSCRIPTION_FILE = CONFIG_DIR / "subscription.json"
NGINX_TEMPLATE = CONFIG_DIR / "subscription.nginx.conf"
SERVICE_NAME = "hysteria-server.service"

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


def cprint(text: str, color: str = RESET) -> None:
    print(f"{color}{text}{RESET}")


def clear() -> None:
    os.system("clear" if os.name == "posix" else "cls")


def ensure_root() -> None:
    if os.name != "posix" or os.geteuid() != 0:
        cprint("请使用 root 权限运行，例如：sudo -i", RED)
        sys.exit(1)


def ensure_dirs() -> None:
    """创建配置目录并保证 hysteria 服务用户可穿越证书目录。

    CONFIG_DIR/SSL_DIR 使用 0710：root 可完整访问，hysteria 组只有 traverse 权限，
    无法列目录；具体证书与私钥再通过 0640 控制读取。
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SSL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        run(["chown", "root:hysteria", str(CONFIG_DIR), str(SSL_DIR)], check=False)
        CONFIG_DIR.chmod(0o710)
        SSL_DIR.chmod(0o710)
    except OSError:
        pass


def run(cmd, *, check=False, capture=False, shell=False, timeout=None):
    kwargs = {
        "check": check,
        "text": True,
        "shell": shell,
        "timeout": timeout,
    }
    if capture:
        kwargs["capture_output"] = True
    return subprocess.run(cmd, **kwargs)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def write_private(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(mode)
    except OSError:
        pass


def yaml_scalar(value) -> str:
    """使用 JSON 字符串作为 YAML 标量，避免特殊字符破坏 YAML。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def yes_no(prompt: str, default: bool | None = None) -> bool:
    suffix = " [Y/n]：" if default is True else " [y/N]：" if default is False else " [y/n]："
    while True:
        value = input(prompt + suffix).strip().lower()
        if not value and default is not None:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        cprint("请输入 y 或 n。", RED)


def input_default(prompt: str, default: str) -> str:
    """普通文本输入；直接回车返回默认值。"""
    value = input(f"{prompt} [{default}]：").strip()
    return value if value else str(default)


def input_nonempty(prompt: str, default: str | None = None) -> str:
    while True:
        suffix = f" [{default}]：" if default is not None else "："
        value = input(prompt.rstrip("：") + suffix).strip()
        if value:
            return value
        if default is not None:
            return str(default)
        cprint("不能为空，请重新输入。", RED)


def input_port(prompt: str, default: int = 443) -> int:
    while True:
        raw = input(f"{prompt.rstrip('：')} [{default}]：").strip()
        if not raw:
            return default
        try:
            port = int(raw)
            if 1 <= port <= 65535:
                return port
        except ValueError:
            pass
        cprint("端口必须是 1~65535 的整数。", RED)


def input_positive_int(prompt: str, default: int | None = None) -> int:
    while True:
        raw = input(prompt).strip()
        if not raw and default is not None:
            return default
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
        cprint("请输入正整数。", RED)


def generate_password(length_bytes: int = 18) -> str:
    """生成适合 URI/配置使用的高强度随机密码。"""
    return secrets.token_urlsafe(length_bytes)


def getpass_default(prompt: str, default: str | None = None, *, generate_if_empty: bool = False) -> str:
    hint = "（直接回车自动生成）" if generate_if_empty and not default else "（直接回车沿用默认值）" if default else ""
    value = getpass.getpass(f"{prompt}{hint}：").strip()
    if value:
        return value
    if default:
        return default
    if generate_if_empty:
        value = generate_password()
        cprint(f"已自动生成密码：{value}", GREEN)
        return value
    return ""


def load_existing_node() -> dict:
    if not NODE_FILE.exists():
        return {}
    try:
        data = json.loads(NODE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def validate_hostname(value: str) -> bool:
    if len(value) > 253:
        return False
    if value.endswith("."):
        value = value[:-1]
    labels = value.split(".")
    pattern = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
    return bool(labels and all(pattern.match(label) for label in labels))


def validate_http_url(value: str) -> bool:
    try:
        p = urllib.parse.urlsplit(value)
        return p.scheme in {"http", "https"} and bool(p.netloc)
    except ValueError:
        return False


def format_host_for_uri(host: str) -> str:
    try:
        ip = ipaddress.ip_address(host)
        return f"[{host}]" if ip.version == 6 else host
    except ValueError:
        return host


def install_basic_dependencies() -> None:
    """尽量安装基础依赖。失败不会立即退出，后续按功能检查。"""
    required = ["curl", "openssl"]
    optional = ["qrencode"]
    missing = [x for x in required + optional if not command_exists(x)]
    if not missing:
        return

    cprint(f"检测到缺少工具：{', '.join(missing)}，尝试安装...", YELLOW)
    try:
        if command_exists("apt-get"):
            run(["apt-get", "update"], check=False)
            run(["apt-get", "install", "-y", "curl", "openssl", "qrencode"], check=False)
        elif command_exists("dnf"):
            run(["dnf", "install", "-y", "curl", "openssl", "qrencode"], check=False)
        elif command_exists("yum"):
            run(["yum", "install", "-y", "curl", "openssl", "qrencode"], check=False)
        elif command_exists("apk"):
            run(["apk", "add", "curl", "openssl", "libqrencode-tools"], check=False)
    except Exception as exc:
        cprint(f"自动安装依赖失败：{exc}", YELLOW)


def atomic_install(path: Path, content: bytes | str, mode: int, gid: int = 0, uid: int = 0) -> None:
    """Write complete files before replacement; do not hide permission errors."""
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError(f"拒绝覆盖符号链接：{path}")
    fd, name = tempfile.mkstemp(prefix=".vpskit-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content.encode("utf-8") if isinstance(content, str) else content)
            stream.flush()
            os.fsync(stream.fileno())
        if hasattr(os, "chown"):
            os.chown(name, uid, gid)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def owned_directory(path: Path, mode: int, gid: int = 0) -> None:
    if path.is_symlink():
        raise ValueError(f"拒绝使用符号链接目录：{path}")
    path.mkdir(parents=True, exist_ok=True)
    if hasattr(os, "chown"):
        os.chown(path, 0, gid)
    path.chmod(mode)


def shortcut_content() -> str:
    target = shlex.quote(str(INSTALLED_SCRIPT))
    return f'''#!/bin/sh
# VPSKit: run the installed local copy; no network or current-directory files.
set -eu
if [ "$(/usr/bin/id -u)" -eq 0 ]; then
    exec /usr/bin/python3 {target} "$@"
fi
if [ -x /usr/bin/sudo ]; then
    exec /usr/bin/sudo -- /usr/bin/python3 {target} "$@"
fi
printf '%s\\n' '请切换到 root 后运行 hy2；本机未安装 sudo。' >&2
exit 1
'''


def create_shortcut() -> None:
    source = Path(__file__).resolve().read_bytes()
    compile(source, str(INSTALLED_SCRIPT), "exec")
    if INSTALLED_SCRIPT.is_symlink():
        raise ValueError(f"拒绝覆盖符号链接：{INSTALLED_SCRIPT}")
    owned_directory(INSTALLED_SCRIPT.parent, 0o755)
    if not INSTALLED_SCRIPT.exists() or INSTALLED_SCRIPT.read_bytes() != source:
        atomic_install(INSTALLED_SCRIPT, source, 0o644)
    SHORTCUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_install(SHORTCUT_FILE, shortcut_content(), 0o755)


def agree_treaty() -> None:
    if AGREE_FILE.exists():
        return

    print("使用说明：")
    print("1. 本脚本用于合法的服务器运维、远程访问与网络测试。")
    print("2. 请遵守服务器所在地、用户所在地及相关服务商的法律法规和服务条款。")
    print("3. 使用者应自行承担配置、运维与使用责任。")
    if not yes_no("是否同意并继续", default=False):
        cprint("已取消。", YELLOW)
        sys.exit(0)
    ensure_dirs()
    write_private(AGREE_FILE, f"accepted={time.strftime('%Y-%m-%d %H:%M:%S')}\n", 0o600)


def run_hysteria_installer(args: list[str] | None = None):
    """下载 Hysteria 官方安装脚本到临时文件后用 bash 执行。

    不使用 ``bash <(curl ...)``，因为 Python 的 ``shell=True`` 默认调用
    /bin/sh，而 Debian/Ubuntu 上的 /bin/sh 通常是 dash，不支持 Bash 的
    process substitution（<(... )），会报 ``Syntax error: "(" unexpected``。
    """
    args = args or []

    if not command_exists("bash"):
        cprint("未找到 bash，无法运行 Hysteria 官方安装脚本。", RED)
        return subprocess.CompletedProcess(["bash"], 127)
    if not command_exists("curl"):
        cprint("未找到 curl，无法下载 Hysteria 官方安装脚本。", RED)
        return subprocess.CompletedProcess(["curl"], 127)

    fd, tmp_path = tempfile.mkstemp(prefix="vpskit-hy2-installer-", suffix=".sh")
    os.close(fd)
    try:
        download = run([
            "curl", "-fsSL", "--retry", "3", "--connect-timeout", "10",
            "https://get.hy2.sh/", "-o", tmp_path
        ], check=False)
        if download.returncode != 0:
            cprint("下载 Hysteria 官方安装脚本失败。", RED)
            return download

        try:
            Path(tmp_path).chmod(0o700)
        except OSError:
            pass

        return run(["bash", tmp_path, *args], check=False)
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass


def hysteria2_install() -> None:
    install_basic_dependencies()
    while True:
        print("1. 安装/更新到最新版本")
        print("2. 安装指定版本")
        print("0. 返回")
        choice = input("请输入选项 [1]：").strip() or "1"
        if choice == "0":
            return
        if choice == "1":
            installer_args = []
        elif choice == "2":
            version = input("请输入版本号（例如 2.12.2，不要加 v；直接回车=最新）：").strip()
            if not version:
                installer_args = []
            else:
                if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
                    cprint("版本号格式不正确。", RED)
                    continue
                installer_args = ["--version", f"v{version}"]
        else:
            cprint("输入错误。", RED)
            continue

        result = run_hysteria_installer(installer_args)
        if result.returncode != 0:
            cprint("Hysteria2 安装/更新失败，请检查网络和上方日志。", RED)
            return
        cprint("Hysteria2 安装/更新完成。", GREEN)
        if yes_no("现在进入配置向导吗", default=True):
            hysteria2_config_wizard()
        return


def hysteria2_uninstall() -> None:
    if not yes_no("确认卸载 Hysteria2 并删除 VPSKit HY2 配置", default=False):
        return
    result = run_hysteria_installer(["--remove"])
    if result.returncode != 0:
        cprint("官方卸载脚本执行失败，将继续清理 VPSKit 本地配置。", YELLOW)

    # Remove only the published allowlist, leaving any unrelated web content alone.
    for name in (*subscription_sources(), "base64.txt"):
        (SUBSCRIPTION_DIR / name).unlink(missing_ok=True)
    for path in [Path("/etc/hysteria"), CONFIG_DIR, SHORTCUT_FILE, INSTALLED_SCRIPT]:
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        except Exception:
            pass
    run(["systemctl", "daemon-reload"], check=False)
    cprint("卸载完成。", GREEN)


def server_manage() -> None:
    while True:
        print("\n1. 启动并设置开机自启")
        print("2. 停止服务")
        print("3. 重启服务")
        print("4. 查看服务状态")
        print("5. 查看日志")
        print("6. 查看 Hysteria2 版本")
        print("0. 返回")
        choice = input("请输入选项 [4]：").strip() or "4"
        if choice == "1":
            run(["systemctl", "enable", "--now", SERVICE_NAME], check=False)
        elif choice == "2":
            run(["systemctl", "stop", SERVICE_NAME], check=False)
        elif choice == "3":
            run(["systemctl", "restart", SERVICE_NAME], check=False)
        elif choice == "4":
            run(["systemctl", "status", SERVICE_NAME, "--no-pager"], check=False)
        elif choice == "5":
            run(["journalctl", "--no-pager", "-e", "-u", SERVICE_NAME], check=False)
        elif choice == "6":
            if HY_BIN.exists():
                run([str(HY_BIN), "version"], check=False)
            else:
                cprint("未找到 Hysteria2。", RED)
        elif choice == "0":
            return
        else:
            cprint("输入错误。", RED)


def get_public_ip(version: int) -> str:
    """自动获取公网 IP；Google Cloud 上优先兼容 Metadata Server。"""
    endpoints = [
        "https://api64.ipify.org",
        "https://ifconfig.me/ip",
        "https://icanhazip.com",
        "https://api.ip.sb/ip",
    ]
    flag = "-4" if version == 4 else "-6"

    while True:
        # Google Cloud IPv4 Metadata Server（本地链路，不携带节点凭据）。
        if version == 4:
            try:
                req = urllib.request.Request(
                    "http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip",
                    headers={"Metadata-Flavor": "Google"},
                )
                with urllib.request.urlopen(req, timeout=2) as resp:
                    value = resp.read().decode().strip()
                if value and ipaddress.ip_address(value).version == 4:
                    return value
            except Exception:
                pass

        if command_exists("curl"):
            for endpoint in endpoints:
                try:
                    result = run(
                        ["curl", flag, "-fsS", "--max-time", "5", endpoint],
                        capture=True,
                        check=False,
                        timeout=7,
                    )
                    value = result.stdout.strip() if result.returncode == 0 else ""
                    if value and ipaddress.ip_address(value).version == version:
                        return value
                except Exception:
                    continue

        value = input(
            f"无法自动获取 IPv{version}。请输入地址（直接回车=重新自动检测）："
        ).strip()
        if not value:
            continue
        try:
            if ipaddress.ip_address(value).version == version:
                return value
        except ValueError:
            pass
        cprint(f"不是有效的 IPv{version} 地址。", RED)


def generate_self_signed_certificate(cert_name: str) -> dict:
    if not command_exists("openssl"):
        raise RuntimeError("未找到 openssl")
    SSL_DIR.mkdir(parents=True, exist_ok=True)
    key_file = SSL_DIR / f"{cert_name}.key"
    crt_file = SSL_DIR / f"{cert_name}.crt"

    try:
        ipaddress.ip_address(cert_name)
        san_type = "IP"
    except ValueError:
        san_type = "DNS"

    cmd = [
        "openssl", "req", "-x509", "-nodes",
        "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
        "-keyout", str(key_file),
        "-out", str(crt_file),
        "-subj", f"/CN={cert_name}",
        "-addext", f"subjectAltName={san_type}:{cert_name}",
        "-days", "3650",
    ]
    run(cmd, check=True)

    der = subprocess.check_output(
        ["openssl", "x509", "-in", str(crt_file), "-outform", "DER"]
    )
    cert_sha256_hex = hashlib.sha256(der).hexdigest()
    fingerprint_colon = ":".join(
        cert_sha256_hex[i:i + 2].upper() for i in range(0, len(cert_sha256_hex), 2)
    )
    cert_pem = crt_file.read_text(encoding="utf-8")

    try:
        # hysteria 服务通常以 hysteria 用户运行；目录必须可 traverse，文件需组可读。
        run(["chown", "root:hysteria", str(CONFIG_DIR), str(SSL_DIR), str(key_file), str(crt_file)], check=False)
        CONFIG_DIR.chmod(0o710)
        SSL_DIR.chmod(0o710)
        key_file.chmod(0o640)
        crt_file.chmod(0o640)
    except OSError:
        pass

    return {
        "cert": str(crt_file),
        "key": str(key_file),
        "cert_pem": cert_pem,
        "cert_sha256_hex": cert_sha256_hex,
        "fingerprint_colon": fingerprint_colon,
    }


def prompt_dns_acme() -> dict | None:
    print("\nACME DNS 服务商：")
    print("1. Cloudflare")
    print("2. Duck DNS")
    print("3. Gandi.net")
    print("4. GoDaddy")
    print("5. Namecheap")
    print("6. Njalla")
    print("7. Porkbun")
    print("8. Vultr")
    print("0. 不使用 DNS Challenge（默认）")
    choice = input("请选择 [0]：").strip() or "0"
    if choice == "0":
        return None

    def secret_or_cancel(prompt: str) -> str | None:
        value = getpass.getpass(f"{prompt}（直接回车=取消 DNS Challenge）：").strip()
        if value:
            return value
        cprint("未输入凭据，已取消 DNS Challenge；将使用 ACME 默认挑战方式。", YELLOW)
        return None

    if choice == "1":
        token = secret_or_cancel("Cloudflare API Token")
        return {"name": "cloudflare", "config": {"cloudflare_api_token": token}} if token else None
    if choice == "2":
        token = secret_or_cancel("DuckDNS API Token")
        if not token:
            return None
        override = input("DuckDNS override domain（直接回车=不设置）：").strip()
        cfg = {"duckdns_api_token": token}
        if override:
            cfg["duckdns_override_domain"] = override
        return {"name": "duckdns", "config": cfg}
    if choice == "3":
        token = secret_or_cancel("Gandi API Token")
        return {"name": "gandi", "config": {"gandi_api_token": token}} if token else None
    if choice == "4":
        token = secret_or_cancel("GoDaddy API Token")
        return {"name": "godaddy", "config": {"godaddy_api_token": token}} if token else None
    if choice == "5":
        api_key = secret_or_cancel("Namecheap API Key")
        if not api_key:
            return None
        api_user = input("Namecheap API User（直接回车=取消 DNS Challenge）：").strip()
        if not api_user:
            cprint("未输入 API User，已取消 DNS Challenge。", YELLOW)
            return None
        cfg = {"namecheap_api_key": api_key, "namecheap_api_user": api_user}
        client_ip = input("Namecheap Client IP（直接回车=自动发现）：").strip()
        if client_ip:
            cfg["namecheap_client_ip"] = client_ip
        return {"name": "namecheap", "config": cfg}
    if choice == "6":
        token = secret_or_cancel("Njalla API Token")
        return {"name": "njalla", "config": {"njalla_api_token": token}} if token else None
    if choice == "7":
        api_key = secret_or_cancel("Porkbun API Key")
        if not api_key:
            return None
        secret_key = secret_or_cancel("Porkbun API Secret Key")
        if not secret_key:
            return None
        return {"name": "porkbun", "config": {"porkbun_api_key": api_key, "porkbun_api_secret_key": secret_key}}
    if choice == "8":
        token = secret_or_cancel("Vultr API Token")
        return {"name": "vultr", "config": {"vultr_api_token": token}} if token else None

    cprint("无效选项，将不使用 DNS Challenge。", YELLOW)
    return None


def build_server_config(node: dict) -> str:
    lines: list[str] = []
    lines.append(f"listen: {node['listen']}")
    lines.append("")

    cert = node["certificate"]
    if cert["mode"] == "acme":
        lines.extend([
            "acme:",
            "  domains:",
            f"    - {yaml_scalar(cert['domain'])}",
            f"  email: {yaml_scalar(cert['email'])}",
        ])
        dns = cert.get("dns")
        if dns:
            lines.extend([
                "  type: dns",
                "  dns:",
                f"    name: {yaml_scalar(dns['name'])}",
                "    config:",
            ])
            for key, value in dns["config"].items():
                lines.append(f"      {key}: {yaml_scalar(value)}")
        lines.append("")
    else:
        lines.extend([
            "tls:",
            f"  cert: {yaml_scalar(cert['cert'])}",
            f"  key: {yaml_scalar(cert['key'])}",
            "",
        ])

    if node["congestion"]["mode"] == "bbr":
        lines.extend([
            "ignoreClientBandwidth: true",
            "congestion:",
            "  type: bbr",
            f"  bbrProfile: {node['congestion']['profile']}",
            "",
        ])
    elif node["congestion"]["mode"] == "reno":
        lines.extend([
            "ignoreClientBandwidth: true",
            "congestion:",
            "  type: reno",
            "",
        ])
    else:
        # Brutal：允许客户端通过 bandwidth 提示启用 Brutal。
        lines.extend([
            "ignoreClientBandwidth: false",
            "",
        ])

    if node.get("obfs"):
        lines.extend([
            "obfs:",
            f"  type: {node['obfs']['type']}",
            f"  {node['obfs']['type']}:",
            f"    password: {yaml_scalar(node['obfs']['password'])}",
            "",
        ])

    lines.extend([
        "auth:",
        "  type: password",
        f"  password: {yaml_scalar(node['password'])}",
        "",
        "masquerade:",
        "  type: proxy",
        "  proxy:",
        f"    url: {yaml_scalar(node['masquerade'])}",
        "    rewriteHost: true",
        "",
    ])

    if node.get("sniff"):
        lines.extend([
            "sniff:",
            "  enable: true",
            "  timeout: 2s",
            "  rewriteDomain: false",
            "  tcpPorts: 80,443,8000-9000",
            "  udpPorts: all",
            "",
        ])

    return "\n".join(lines).rstrip() + "\n"


def build_hy2_uri(node: dict) -> str:
    auth = urllib.parse.quote(node["password"], safe="")
    host = format_host_for_uri(node["server"])
    if node["port_hopping"]["enabled"]:
        port_part = f"{node['port_hopping']['start']}-{node['port_hopping']['end']}"
    else:
        port_part = str(node["port"])

    params = {"sni": node["sni"]}
    cert = node["certificate"]
    if cert["mode"] == "self_signed":
        params["insecure"] = "1"
        params["pinSHA256"] = cert["cert_sha256_hex"]
    else:
        params["insecure"] = "0"

    if node.get("obfs"):
        params["obfs"] = node["obfs"]["type"]
        params["obfs-password"] = node["obfs"]["password"]

    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote, safe="")
    fragment = urllib.parse.quote(node["name"], safe="")
    return f"hysteria2://{auth}@{host}:{port_part}/?{query}#{fragment}"


def build_mihomo_config(node: dict) -> str:
    name = node["name"]
    lines = [
        "# Generated locally by VPSKit. No node credential is sent to a converter.",
        "mixed-port: 7890",
        "allow-lan: false",
        "mode: rule",
        "log-level: info",
        "ipv6: true",
        "unified-delay: true",
        "tcp-concurrent: true",
        "",
        "proxies:",
        f"  - name: {yaml_scalar(name)}",
        "    type: hysteria2",
        f"    server: {yaml_scalar(node['server'])}",
    ]

    if node["port_hopping"]["enabled"]:
        lines.extend([
            f"    port: {node['port_hopping']['start']}",
            f"    ports: {yaml_scalar(str(node['port_hopping']['start']) + '-' + str(node['port_hopping']['end']))}",
            f"    hop-interval: {node['port_hopping'].get('interval', 30)}",
        ])
    else:
        lines.append(f"    port: {node['port']}")

    lines.extend([
        f"    password: {yaml_scalar(node['password'])}",
        f"    sni: {yaml_scalar(node['sni'])}",
    ])

    cert = node["certificate"]
    if cert["mode"] == "self_signed":
        lines.extend([
            "    skip-cert-verify: true",
            f"    fingerprint: {yaml_scalar(cert['fingerprint_colon'])}",
        ])
    else:
        lines.append("    skip-cert-verify: false")

    if node.get("obfs"):
        lines.extend([
            f"    obfs: {node['obfs']['type']}",
            f"    obfs-password: {yaml_scalar(node['obfs']['password'])}",
        ])

    if node["congestion"]["mode"] == "brutal":
        lines.extend([
            f"    up: {yaml_scalar(str(node['congestion']['up_mbps']) + ' Mbps')}",
            f"    down: {yaml_scalar(str(node['congestion']['down_mbps']) + ' Mbps')}",
        ])
    elif node["congestion"]["mode"] == "bbr":
        lines.append(f"    bbr-profile: {node['congestion']['profile']}")

    lines.extend([
        "",
        "proxy-groups:",
        "  - name: PROXY",
        "    type: select",
        "    proxies:",
        f"      - {yaml_scalar(name)}",
        "      - DIRECT",
        "",
        "rules:",
        "  - IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
        "  - IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
        "  - IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
        "  - IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
        "  - IP-CIDR,100.64.0.0/10,DIRECT,no-resolve",
        "  - GEOSITE,cn,DIRECT",
        "  - GEOIP,CN,DIRECT,no-resolve",
        "  - MATCH,PROXY",
        "",
    ])
    return "\n".join(lines)


def build_singbox_config(node: dict) -> str:
    hy2 = {
        "type": "hysteria2",
        "tag": node["name"],
        "server": node["server"],
        "password": node["password"],
        "tls": {
            "enabled": True,
            "server_name": node["sni"],
        },
    }

    if node["port_hopping"]["enabled"]:
        # sing-box 的 server_ports 范围格式使用 start:end。
        hy2["server_ports"] = [
            f"{node['port_hopping']['start']}:{node['port_hopping']['end']}"
        ]
        hy2["hop_interval"] = f"{node['port_hopping'].get('interval', 30)}s"
    else:
        hy2["server_port"] = node["port"]

    cert = node["certificate"]
    if cert["mode"] == "self_signed":
        # 将自签证书直接嵌入配置，避免只依赖 insecure。
        hy2["tls"]["certificate"] = cert["cert_pem"]
        hy2["tls"]["insecure"] = False
    else:
        hy2["tls"]["insecure"] = False

    if node.get("obfs"):
        hy2["obfs"] = {
            "type": node["obfs"]["type"],
            "password": node["obfs"]["password"],
        }

    if node["congestion"]["mode"] == "brutal":
        hy2["up_mbps"] = node["congestion"]["up_mbps"]
        hy2["down_mbps"] = node["congestion"]["down_mbps"]
    elif node["congestion"]["mode"] == "bbr":
        # sing-box 1.14+ 支持 bbr_profile；旧版会忽略/报未知字段，因此仅 standard 不写。
        if node["congestion"]["profile"] != "standard":
            hy2["bbr_profile"] = node["congestion"]["profile"]

    config = {
        "_comment": "Generated locally by VPSKit; node credentials are not sent to any converter.",
        "log": {"level": "info"},
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": 2080,
            }
        ],
        "outbounds": [
            {
                "type": "selector",
                "tag": "PROXY",
                "outbounds": [node["name"], "direct"],
                "default": node["name"],
            },
            hy2,
            {"type": "direct", "tag": "direct"},
        ],
        "route": {
            "rules": [
                {"ip_is_private": True, "outbound": "direct"},
                {"rule_set": "geosite-cn", "outbound": "direct"},
                {"rule_set": "geoip-cn", "outbound": "direct"},
            ],
            "rule_set": [
                {
                    "type": "remote",
                    "tag": "geosite-cn",
                    "format": "binary",
                    "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-cn.srs",
                    "download_detour": node["name"],
                    "update_interval": "24h",
                },
                {
                    "type": "remote",
                    "tag": "geoip-cn",
                    "format": "binary",
                    "url": "https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/geoip-cn.srs",
                    "download_detour": node["name"],
                    "update_interval": "24h",
                },
            ],
            "final": "PROXY",
            "auto_detect_interface": True,
        },
        "experimental": {
            "cache_file": {"enabled": True}
        },
    }
    return json.dumps(config, ensure_ascii=False, indent=2) + "\n"


def surge_value(value: str) -> str:
    """Surge 参数值：包含逗号/引号/反斜杠时使用双引号。"""
    value = str(value)
    if any(ch in value for ch in [",", '"', "\\"]):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def build_surge_config(node: dict) -> str:
    # Surge 官方支持 Hysteria2 的 port-hopping / Salamander / Gecko / 证书指纹固定。
    port = node["port_hopping"]["start"] if node["port_hopping"]["enabled"] else node["port"]
    server = format_host_for_uri(node["server"])
    params = [
        f"password={surge_value(node['password'])}",
        f"sni={surge_value(node['sni'])}",
    ]

    if node["port_hopping"]["enabled"]:
        params.append(
            f"port-hopping={node['port_hopping']['start']}-{node['port_hopping']['end']}"
        )
        params.append(f"port-hopping-interval={node['port_hopping'].get('interval', 30)}")

    if node.get("obfs"):
        if node["obfs"]["type"] == "gecko":
            params.append(f"gecko-password={surge_value(node['obfs']['password'])}")
        else:
            params.append(f"salamander-password={surge_value(node['obfs']['password'])}")

    if node["congestion"]["mode"] == "brutal":
        # Surge 当前 Hysteria2 策略公开参数提供 download-bandwidth。
        params.append(f"download-bandwidth={node['congestion']['down_mbps']}")

    if node["certificate"]["mode"] == "self_signed":
        # Surge 的 pin 会替代标准 X.509 校验，比单独 skip-cert-verify 更安全。
        params.append(
            f"server-cert-fingerprint-sha256={node['certificate']['cert_sha256_hex']}"
        )

    proxy = (
        f"{node['name']} = hysteria2, {server}, {port}, "
        + ", ".join(params)
    )

    lines = [
        "# Generated locally by VPSKit. No node credential is sent to a converter.",
        "[General]",
        "loglevel = notify",
        "ipv6 = true",
        "",
        "[Proxy]",
        proxy,
        "",
        "[Proxy Group]",
        f"PROXY = select, {node['name']}, DIRECT",
        "",
        "[Rule]",
        "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
        "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
        "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
        "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
        "GEOIP,CN,DIRECT",
        "FINAL,PROXY",
        "",
    ]
    return "\n".join(lines)


def subscription_sources() -> dict:
    return {"links.txt": LINKS_FILE, "mihomo.yaml": MIHOMO_FILE,
            "sing-box.json": SINGBOX_FILE, "surge.conf": SURGE_FILE}


def read_subscription_settings() -> dict:
    settings = json.loads(SUBSCRIPTION_FILE.read_text(encoding="utf-8"))
    if not validate_hostname(settings.get("domain", "")):
        raise ValueError("订阅域名无效")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", settings.get("token", "")):
        raise ValueError("订阅访问令牌无效")
    return settings


def web_group_gid(group: str) -> int:
    import grp
    try:
        return grp.getgrnam(group).gr_gid
    except KeyError as exc:
        raise ValueError(f"未找到 Web 服务组 {group}；请先安装 Nginx 或指定 --web-group") from exc


def subscription_urls(settings: dict) -> dict:
    base = f"https://{settings['domain']}/s/{settings['token']}/"
    return {name: base + name for name in (*subscription_sources(), "base64.txt")}


def sync_subscription_files() -> None:
    if not SUBSCRIPTION_FILE.exists():
        return
    settings = read_subscription_settings()
    gid = web_group_gid(settings["web_group"])
    # Explicit allowlist: never copy node.json, TLS private keys, or DNS API tokens.
    payloads = {name: path.read_bytes() for name, path in subscription_sources().items()}
    payloads["base64.txt"] = base64.b64encode(payloads["links.txt"]) + b"\n"
    url = subscription_urls(settings)["surge.conf"]
    payloads["surge.conf"] = (
        f"#!MANAGED-CONFIG {url} interval=86400 strict=false\n".encode("utf-8")
        + payloads["surge.conf"]
    )
    owned_directory(SUBSCRIPTION_DIR.parent, 0o750, gid)
    owned_directory(SUBSCRIPTION_DIR, 0o750, gid)
    for name, content in payloads.items():
        atomic_install(SUBSCRIPTION_DIR / name, content, 0o640, gid)


def build_subscription_nginx(settings: dict) -> str:
    domain = settings["domain"]
    lines = ["# VPSKit subscription only. Install the TLS certificate before enabling.",
             "server {", "    listen 443 ssl;", f"    server_name {domain};",
             f"    ssl_certificate /etc/nginx/ssl/{domain}.pem;",
             f"    ssl_certificate_key /etc/nginx/ssl/{domain}.key;",
             "    ssl_protocols TLSv1.2 TLSv1.3;", "    server_tokens off;",
             "    access_log off;", "    error_log /dev/null crit;",
             "    autoindex off;", "    etag off;", "    if_modified_since off;",
             "    add_header Cache-Control \"private, no-store, max-age=0\" always;",
             "    add_header X-Content-Type-Options nosniff always;",
             "    location / { return 404; }"]
    for name in subscription_urls(settings):
        path = SUBSCRIPTION_DIR / name
        mime = "application/json" if name.endswith(".json") else "text/plain"
        lines += [f"    location = /s/{settings['token']}/{name} {{",
                  f"        alias {path.as_posix()};", f"        default_type {mime};",
                  "        limit_except GET { deny all; }", "    }"]
    return "\n".join(lines + ["}", ""])


def prepare_subscription(domain: str, web_group: str = "www-data") -> None:
    domain = domain.lower().rstrip(".")
    if not validate_hostname(domain) or "." not in domain:
        raise ValueError("请输入你自己的订阅域名；不要包含 https:// 或路径")
    web_group_gid(web_group)
    if not all(path.is_file() for path in subscription_sources().values()):
        raise ValueError("请先完成节点配置或重新导出，确保四种客户端文件均已生成")
    existing = read_subscription_settings() if SUBSCRIPTION_FILE.exists() else {}
    settings = {"domain": domain, "web_group": web_group,
                "token": existing.get("token") or secrets.token_urlsafe(32)}
    atomic_install(SUBSCRIPTION_FILE, json.dumps(settings, indent=2) + "\n", 0o600)
    sync_subscription_files()
    atomic_install(NGINX_TEMPLATE, build_subscription_nginx(settings), 0o600)
    cprint("订阅文件和 Nginx 模板已准备；尚未配置 DNS、安装证书或启用网站。", GREEN)
    print(f"Nginx 模板：{NGINX_TEMPLATE}")
    print("完成 README 中的 HTTPS 配置后，使用以下链接（链接本身是访问凭据）：")
    for name, url in subscription_urls(settings).items():
        print(f"  {name}: {url}")


def show_subscription_links() -> None:
    if not SUBSCRIPTION_FILE.exists():
        cprint("尚未配置订阅；需要时选择“配置/修改订阅”。", YELLOW)
        return
    settings = read_subscription_settings()
    print("以下链接需在 DNS、HTTPS 证书和 Nginx 站点配置完成后才能访问：")
    for name, url in subscription_urls(settings).items():
        print(f"  {name}: {url}")
    print(f"Nginx 配置模板：{NGINX_TEMPLATE}")


def disable_subscription() -> None:
    if SUBSCRIPTION_DIR.is_symlink() or SUBSCRIPTION_DIR.parent.is_symlink():
        raise ValueError("订阅目录为符号链接，拒绝清理")
    # Remove the opt-in marker first so future local exports cannot republish files.
    SUBSCRIPTION_FILE.unlink(missing_ok=True)
    for name in (*subscription_sources(), "base64.txt"):
        (SUBSCRIPTION_DIR / name).unlink(missing_ok=True)
    NGINX_TEMPLATE.unlink(missing_ok=True)
    cprint("订阅已停用，发布文件已移除；HY2 节点、本地导出和证书保留。", GREEN)
    print("已安装的 Nginx 站点不会被修改；原订阅地址将因文件移除返回 404。")


def subscription_menu() -> None:
    """Optional subscription management; merely opening this menu has no side effects."""
    while True:
        status = "已准备（公网可用性需自行验证）" if SUBSCRIPTION_FILE.exists() else "未配置"
        print(f"\n订阅链接（可选）— {status}")
        print("1. 配置/修改订阅")
        print("2. 查看订阅链接")
        print("3. 同步订阅文件")
        print("4. 停用订阅（保留节点和本地配置）")
        print("0. 返回")
        choice = input("请选择 [0]：").strip() or "0"
        try:
            if choice == "0":
                return
            if choice == "1":
                current = read_subscription_settings() if SUBSCRIPTION_FILE.exists() else {}
                print("此操作生成订阅文件和 Nginx 模板；首次还需按 README 配置 DNS、HTTPS 和站点。")
                domain = input_nonempty("请输入你自己的订阅域名（必填）")
                prepare_subscription(domain, current.get("web_group", "www-data"))
            elif choice == "2":
                show_subscription_links()
            elif choice == "3":
                if not SUBSCRIPTION_FILE.exists():
                    cprint("尚未配置订阅；请先选择“配置/修改订阅”。", YELLOW)
                    continue
                sync_subscription_files()
                cprint("订阅文件已同步。", GREEN)
            elif choice == "4":
                if yes_no("确认停用订阅？现有客户端将无法再从此站点更新", default=False):
                    disable_subscription()
            else:
                cprint("输入错误。", RED)
        except (OSError, ValueError, KeyError) as exc:
            cprint(f"订阅操作失败：{exc}", RED)
        except KeyboardInterrupt:
            cprint("已取消当前订阅操作。", YELLOW)


def show_share_link(uri: str, show_qr: bool = True) -> None:
    print("\n" + "=" * 72)
    cprint("Hysteria2 分享链接：", CYAN)
    print(uri)
    print("=" * 72)
    if not show_qr:
        return
    if not command_exists("qrencode"):
        cprint("未安装 qrencode，无法显示二维码；可复制上面的链接导入。", YELLOW)
        print("Debian/Ubuntu 安装命令：sudo apt-get install -y qrencode")
        return
    try:
        result = subprocess.run(
            ["qrencode", "-s", "1", "-m", "1", "-t", "ANSI256", "-o", "-"],
            input=uri, text=True, capture_output=True, check=False, timeout=10,
        )
        if result.returncode == 0 and result.stdout:
            print("\n二维码（扫描导入）：")
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        else:
            cprint("二维码生成失败；可复制上面的链接导入。", YELLOW)
    except (OSError, subprocess.TimeoutExpired):
        cprint("二维码工具无法运行或超时；可复制上面的链接导入。", YELLOW)


def copy_client_configs_to_user_home() -> None:
    """Copy downloadable exports to the invoking sudo user's account home."""
    username = os.environ.get("SUDO_USER")
    if not username or username == "root":
        cprint("未检测到普通用户 SUDO_USER，跳过 Home 配置副本。", YELLOW)
        return
    try:
        import pwd

        account = pwd.getpwnam(username)
        if account.pw_uid == 0:
            cprint("SUDO_USER 对应 root，跳过 Home 配置副本。", YELLOW)
            return
        home = Path(account.pw_dir)
        if not home.is_absolute() or not home.is_dir():
            raise ValueError(f"用户 Home 目录不存在或无效：{home}")
        for filename, source in subscription_sources().items():
            atomic_install(home / filename, source.read_bytes(), 0o600,
                           gid=account.pw_gid, uid=account.pw_uid)
        cprint(f"客户端配置已额外复制到 {home}，属主为 {username}，可通过 SSH 下载。", GREEN)
    except (ImportError, KeyError, OSError, ValueError) as exc:
        cprint(f"Home 配置复制失败：{exc}；原配置仍保留在 {CONFIG_DIR}。", YELLOW)


def export_client_configs(node: dict, show_qr: bool = True) -> None:
    ensure_dirs()
    uri = build_hy2_uri(node)

    write_private(LINKS_FILE, uri + "\n", 0o600)
    write_private(MIHOMO_FILE, build_mihomo_config(node), 0o600)
    write_private(SINGBOX_FILE, build_singbox_config(node), 0o600)
    write_private(SURGE_FILE, build_surge_config(node), 0o600)
    write_private(NODE_FILE, json.dumps(node, ensure_ascii=False, indent=2) + "\n", 0o600)
    copy_client_configs_to_user_home()
    if SUBSCRIPTION_FILE.exists():
        try:
            sync_subscription_files()
            cprint("订阅文件已同步更新。", GREEN)
        except (OSError, ValueError, KeyError) as exc:
            cprint(f"本地导出完成，但订阅同步失败：{exc}；修复后运行 hy2 --sync-subscription。", RED)

    show_share_link(uri, show_qr=show_qr)

    cprint("\n本地客户端配置已生成：", GREEN)
    print(f"  {LINKS_FILE}")
    print(f"  {MIHOMO_FILE}")
    print(f"  {SINGBOX_FILE}")
    print(f"  {SURGE_FILE}")
    print("\n转换过程完全在本 VPS 本地完成，没有向第三方转换服务提交节点凭据。")
    if node["congestion"]["mode"] == "brutal":
        cprint(
            "提示：官方 hysteria2:// URI 不携带带宽参数；Brutal 的 up/down 已写入 Mihomo 与 sing-box 本地配置。",
            YELLOW,
        )


def repair_hysteria_permissions() -> None:
    """修复 Hysteria 服务读取配置/自签证书所需的最小权限。"""
    ensure_dirs()
    try:
        if HY_CONFIG.exists():
            run(["chown", "root:hysteria", str(HY_CONFIG)], check=False)
            HY_CONFIG.chmod(0o640)
    except OSError:
        pass

    node = load_existing_node()
    cert = node.get("certificate") or {}
    if cert.get("mode") == "self_signed":
        for key in ("cert", "key"):
            raw = cert.get(key)
            if not raw:
                continue
            path = Path(raw)
            if path.exists():
                try:
                    run(["chown", "root:hysteria", str(path)], check=False)
                    path.chmod(0o640)
                except OSError:
                    pass


def restart_service() -> None:
    repair_hysteria_permissions()
    run(["systemctl", "enable", SERVICE_NAME], check=False)
    result = run(["systemctl", "restart", SERVICE_NAME], check=False)
    time.sleep(1)
    active = run(["systemctl", "is-active", SERVICE_NAME], capture=True, check=False)
    if result.returncode == 0 and active.stdout.strip() == "active":
        cprint("Hysteria2 服务已启动。", GREEN)
    else:
        cprint("Hysteria2 服务启动失败，请查看日志。", RED)
        run(["journalctl", "--no-pager", "-n", "40", "-u", SERVICE_NAME], check=False)


def hysteria2_config_wizard() -> None:
    if not HY_BIN.exists():
        cprint("未找到 /usr/local/bin/hysteria，请先安装 Hysteria2。", RED)
        return

    ensure_dirs()
    existing = load_existing_node()
    clear()
    print(f"{SCRIPT_NAME} v{SCRIPT_VERSION} - 配置向导")
    print("提示：除明确要求确认的安全操作外，直接回车都会采用方括号中的默认值。\n")

    default_name = existing.get("name", "VPSKit-HY2")
    name = input_default("节点名称", default_name)

    old_password = existing.get("password")
    password = getpass_default(
        "Hysteria2 密码",
        old_password,
        generate_if_empty=not bool(old_password),
    )

    default_masquerade = existing.get("masquerade", "https://www.bing.com/")
    while True:
        masquerade = input_default("伪装网址", default_masquerade)
        if validate_http_url(masquerade):
            break
        cprint("请输入完整的 http:// 或 https:// URL。", RED)

    old_congestion = existing.get("congestion") or {}
    old_mode = old_congestion.get("mode", "bbr")
    default_cc = {"bbr": "1", "brutal": "2", "reno": "3"}.get(old_mode, "1")
    print("\n拥塞控制：")
    print("1. BBR（推荐）")
    print("2. Brutal（需要填写客户端带宽）")
    print("3. Reno")
    congestion_choice = input(f"请选择 [{default_cc}]：").strip() or default_cc
    if congestion_choice == "2":
        congestion = {
            "mode": "brutal",
            "up_mbps": input_positive_int(
                f"客户端上传带宽 Mbps [{old_congestion.get('up_mbps', 100)}]：",
                default=int(old_congestion.get("up_mbps", 100)),
            ),
            "down_mbps": input_positive_int(
                f"客户端下载带宽 Mbps [{old_congestion.get('down_mbps', 500)}]：",
                default=int(old_congestion.get("down_mbps", 500)),
            ),
        }
    elif congestion_choice == "3":
        congestion = {"mode": "reno"}
    else:
        old_profile = old_congestion.get("profile", "standard")
        default_profile = {"standard": "1", "conservative": "2", "aggressive": "3"}.get(old_profile, "1")
        print("BBR Profile：1.standard  2.conservative  3.aggressive")
        profile_choice = input(f"请选择 [{default_profile}]：").strip() or default_profile
        profile = {"1": "standard", "2": "conservative", "3": "aggressive"}.get(profile_choice, "standard")
        congestion = {"mode": "bbr", "profile": profile}

    old_obfs = existing.get("obfs")
    obfs = None
    if yes_no("是否开启 QUIC 混淆（默认不推荐；会失去标准 HTTP/3 伪装）", default=bool(old_obfs)):
        old_obfs_type = (old_obfs or {}).get("type", "salamander")
        default_obfs_type = "2" if old_obfs_type == "gecko" else "1"
        print("1. salamander（稳定）")
        print("2. gecko（实验性）")
        obfs_choice = input(f"请选择 [{default_obfs_type}]：").strip() or default_obfs_type
        obfs_type = "gecko" if obfs_choice == "2" else "salamander"
        old_obfs_password = (old_obfs or {}).get("password")
        obfs_password = getpass_default(
            "混淆密码",
            old_obfs_password,
            generate_if_empty=not bool(old_obfs_password),
        )
        obfs = {"type": obfs_type, "password": obfs_password}

    sniff = yes_no("是否开启协议嗅探 Sniff", default=bool(existing.get("sniff", False)))

    old_port = int(existing.get("port", 443) or 443)
    base_port = input_port("监听端口（不启用端口跳跃时使用）", default=old_port)

    old_hop = existing.get("port_hopping") or {"enabled": False}
    hop_default = bool(old_hop.get("enabled", False))
    port_hopping = {"enabled": False}
    listen = f":{base_port}"
    if yes_no("是否开启 Hysteria2 原生端口跳跃", default=hop_default):
        print("端口跳跃范围：")
        print("1. 使用默认/已有范围（推荐）")
        print("2. 手动指定范围")
        hop_mode = input("请选择 [1]：").strip() or "1"
        default_start = int(old_hop.get("start", 20000) or 20000)
        default_end = int(old_hop.get("end", 50000) or 50000)
        if hop_mode == "2":
            while True:
                start = input_port("起始端口", default=default_start)
                end = input_port("结束端口", default=default_end)
                if start <= end:
                    break
                cprint("起始端口不能大于结束端口。", RED)
        else:
            start, end = default_start, default_end
            print(f"已采用端口范围：{start}-{end}")

        default_interval = int(old_hop.get("interval", 30) or 30)
        interval = input_positive_int(
            f"端口跳跃间隔秒数 [{default_interval}]：",
            default=default_interval,
        )
        interval = max(5, interval)
        if not (command_exists("nft") or command_exists("iptables")):
            cprint("警告：系统未发现 nft/iptables，Hysteria 原生端口范围可能无法自动配置防火墙。", YELLOW)
        port_hopping = {"enabled": True, "start": start, "end": end, "interval": interval}
        listen = f":{start}-{end}"
        cprint(f"请同时在云厂商安全组/防火墙放行 UDP {start}-{end}。", YELLOW)

    old_cert = existing.get("certificate") or {}
    old_cert_mode = old_cert.get("mode", "self_signed")
    default_cert_choice = {"acme": "1", "self_signed": "2", "manual": "3"}.get(old_cert_mode, "2")
    print("\n证书方式：")
    print("1. ACME 自动申请域名证书")
    print("2. 自签证书（无需自己的域名，推荐默认）")
    print("3. 手动指定证书路径")
    cert_choice = input(f"请选择 [{default_cert_choice}]：").strip() or default_cert_choice

    if cert_choice == "1":
        default_domain = old_cert.get("domain", "") if old_cert_mode == "acme" else ""
        domain = input("请输入已解析到本服务器的域名（留空则改用自签证书）：").strip() or default_domain
        if not domain:
            cprint("未提供域名，自动切换为自签证书。", YELLOW)
            cert_choice = "2"
        elif not validate_hostname(domain):
            cprint("域名格式不正确，自动切换为自签证书。", YELLOW)
            cert_choice = "2"
        else:
            default_email = old_cert.get("email") if old_cert_mode == "acme" else None
            if not default_email:
                default_email = f"admin@{domain}"
            email = input_default("ACME 邮箱", default_email)
            dns = None
            if yes_no("是否使用 ACME DNS Challenge", default=bool(old_cert.get("dns"))):
                dns = prompt_dns_acme()
            certificate = {
                "mode": "acme",
                "domain": domain,
                "email": email,
                "dns": dns,
            }
            server = domain
            sni = domain

    if cert_choice == "3":
        default_cert = old_cert.get("cert", "/etc/hysteria/server.crt") if old_cert_mode == "manual" else "/etc/hysteria/server.crt"
        default_key = old_cert.get("key", "/etc/hysteria/server.key") if old_cert_mode == "manual" else "/etc/hysteria/server.key"
        cert_path = input_default("证书文件路径", default_cert)
        key_path = input_default("私钥文件路径", default_key)
        if not Path(cert_path).exists() or not Path(key_path).exists():
            cprint("默认/指定证书文件不存在，自动切换为自签证书。", YELLOW)
            cert_choice = "2"
        else:
            old_server = existing.get("server") or get_public_ip(4)
            server = input_default("客户端连接地址（域名或 IP）", old_server)
            sni = input_default("TLS SNI/证书域名", existing.get("sni", "bing.com"))
            certificate = {
                "mode": "manual",
                "cert": cert_path,
                "key": key_path,
            }

    if cert_choice == "2":
        default_sni = existing.get("sni", "bing.com") if old_cert_mode == "self_signed" else "bing.com"
        cert_name = input_default("自签证书 SNI", default_sni)
        if not validate_hostname(cert_name):
            try:
                ipaddress.ip_address(cert_name)
            except ValueError:
                cprint("SNI/证书名称格式不正确，已使用 bing.com。", YELLOW)
                cert_name = "bing.com"
        cert_info = generate_self_signed_certificate(cert_name)
        certificate = {"mode": "self_signed", **cert_info}
        sni = cert_name
        old_server = str(existing.get("server", ""))
        default_ip_mode = "2" if ":" in old_server and old_cert_mode == "self_signed" else "1"
        ip_mode = input(f"连接地址：1.IPv4  2.IPv6 [{default_ip_mode}]：").strip() or default_ip_mode
        server = get_public_ip(6 if ip_mode == "2" else 4)

    node = {
        "schema": 2,
        "generator": f"{SCRIPT_NAME} v{SCRIPT_VERSION}",
        "name": name,
        "server": server,
        "port": base_port,
        "listen": listen,
        "password": password,
        "sni": sni,
        "masquerade": masquerade,
        "sniff": sniff,
        "obfs": obfs,
        "port_hopping": port_hopping,
        "congestion": congestion,
        "certificate": certificate,
    }

    server_config = build_server_config(node)
    HY_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    write_private(HY_CONFIG, server_config, 0o640)
    try:
        run(["chown", "root:hysteria", str(HY_CONFIG)], check=False)
    except Exception:
        pass

    export_client_configs(node, show_qr=True)
    restart_service()


def show_configs() -> None:
    print("\n--- Hysteria2 服务端配置 ---")
    if HY_CONFIG.exists():
        print(HY_CONFIG.read_text(encoding="utf-8"))
    else:
        cprint("未找到服务端配置。", YELLOW)

    # View the saved exports without regenerating credentials, files, or subscriptions.
    links = []
    if LINKS_FILE.is_file():
        links = [line.strip() for line in LINKS_FILE.read_text(encoding="utf-8").splitlines()
                 if line.strip().startswith(("hysteria2://", "hy2://"))]
    if links:
        print("--- 已保存的客户端分享信息 ---")
        for uri in links:
            show_share_link(uri)
    else:
        cprint("未找到已保存的 HY2 分享链接；请先完成一键配置或选择“重新生成本地客户端配置”。", YELLOW)

    print("--- 客户端导出文件 ---")
    for path in [LINKS_FILE, MIHOMO_FILE, SINGBOX_FILE, SURGE_FILE]:
        print(f"{path}: {'存在' if path.exists() else '不存在'}")


def manual_edit_config() -> None:
    editor = shutil.which("nano") or shutil.which("vi")
    if not editor:
        cprint("未找到 nano/vi。", RED)
        return
    run([editor, str(HY_CONFIG)], check=False)
    if yes_no("是否重启 Hysteria2 服务使修改生效", default=True):
        restart_service()


def reexport_configs() -> None:
    if not NODE_FILE.exists():
        cprint("未找到 node.json，请先运行一键配置。", RED)
        return
    try:
        node = json.loads(NODE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        cprint(f"读取 node.json 失败：{exc}", RED)
        return
    export_client_configs(node, show_qr=True)


def performance_optimize() -> None:
    cprint("该功能会调用第三方 Linux-NetSpeed/tcpx.sh，可能修改内核、BBR、sysctl 等系统设置。", YELLOW)
    if not yes_no("确认继续调用第三方脚本", default=False):
        return
    url = "https://raw.githubusercontent.com/ylx2016/Linux-NetSpeed/master/tcpx.sh"
    tmp = Path(tempfile.gettempdir()) / "vpskit-tcpx.sh"
    result = run(["curl", "-fsSL", url, "-o", str(tmp)], check=False)
    if result.returncode != 0:
        cprint("下载失败。", RED)
        return
    tmp.chmod(0o700)
    run([str(tmp)], check=False)


def hysteria2_config_menu() -> None:
    while True:
        print("\n1. 查看配置")
        print("2. 一键重新配置")
        print("3. 手动编辑服务端配置")
        print("4. 性能优化（第三方，高级）")
        print("5. 重新生成本地客户端配置")
        print("0. 返回")
        choice = input("请输入选项 [1]：").strip() or "1"
        if choice == "1":
            show_configs()
        elif choice == "2":
            hysteria2_config_wizard()
        elif choice == "3":
            manual_edit_config()
        elif choice == "4":
            performance_optimize()
        elif choice == "5":
            reexport_configs()
        elif choice == "0":
            return
        else:
            cprint("输入错误。", RED)


def main() -> None:
    parser = argparse.ArgumentParser(description=SCRIPT_NAME)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--install-shortcut", action="store_true", help="安装/修复全局 hy2 命令后退出")
    actions.add_argument("--prepare-subscription", metavar="DOMAIN", help="准备本地订阅文件和 Nginx 模板")
    actions.add_argument("--sync-subscription", action="store_true", help="同步现有本地导出到订阅目录")
    parser.add_argument("--web-group", default="www-data", help="Nginx worker 所在组，默认 www-data")
    args = parser.parse_args()
    ensure_root()
    if args.sync_subscription:
        if not SUBSCRIPTION_FILE.exists():
            parser.error("请先执行 --prepare-subscription")
        sync_subscription_files()
        cprint("订阅文件已同步。", GREEN)
        return
    agree_treaty()
    ensure_dirs()
    create_shortcut()
    if args.install_shortcut:
        cprint(f"全局命令已安装：{SHORTCUT_FILE} → {INSTALLED_SCRIPT}", GREEN)
        return
    if args.prepare_subscription:
        prepare_subscription(args.prepare_subscription, args.web_group)
        return

    while True:
        clear()
        print(f"{RED}HELLO VPSKit / HYSTERIA2 !{RESET}")
        print(f"版本：{SCRIPT_VERSION}    快捷启动：hy2")
        print("\n1. 安装/更新 Hysteria2")
        print("2. 卸载 Hysteria2")
        print("3. Hysteria2 配置")
        print("4. Hysteria2 服务管理")
        print("5. 订阅链接（可选）")
        print("0. 退出")
        default_main = "3" if HY_BIN.exists() else "1"
        choice = input(f"请选择 [{default_main}]：").strip() or default_main
        if choice == "1":
            clear()
            hysteria2_install()
            input("\n按回车继续...")
        elif choice == "2":
            clear()
            hysteria2_uninstall()
            input("\n按回车继续...")
        elif choice == "3":
            clear()
            hysteria2_config_menu()
        elif choice == "4":
            clear()
            server_manage()
        elif choice == "5":
            clear()
            subscription_menu()
        elif choice == "0":
            print("已退出。")
            return
        else:
            cprint("输入错误，请重新输入。", RED)
            time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        cprint(f"操作失败：{exc}", RED)
        sys.exit(1)
