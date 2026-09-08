#!/usr/bin/env bash
# VPSKit: optional first-run dependencies for Debian/Ubuntu.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
    printf '%s\n' '请先执行 sudo -i 切换 root，再运行 bash phy2.sh。' >&2
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
    printf '%s\n' '此依赖安装脚本支持 Debian/Ubuntu；其他系统请自行安装 Python 3、curl、OpenSSL 和 wget。' >&2
    exit 1
fi

printf '%s\n' '正在安装 VPSKit 基础依赖……'
apt-get update
apt-get install -y --no-install-recommends python3 ca-certificates curl wget openssl qrencode
printf '%s\n' '基础依赖已安装。下一步下载并运行 hy2.py，选择菜单 1 安装 Hysteria2。'
