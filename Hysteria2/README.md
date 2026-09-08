# VPSKit — Hysteria2

仓库：<https://github.com/JoongDa/VPSKit>

`hy2.py` 为 Hysteria2 安装、配置、服务管理脚本。0.1.3 修复全局快捷启动，0.1.4 将可选订阅功能做成独立菜单，0.1.5 在“查看配置”中补回已保存的分享链接和二维码。此版本基于用户提供的 0.1.2 修改，不是之前 VH2 双协议脚本的替代副本。

## 快速安装（Debian / Ubuntu）

在 VPS 中以 root 执行下面两步，普通用户先运行 `sudo -i`。

**1. 安装依赖（首次安装执行即可，可重复运行）：**

```bash
wget -O phy2.sh https://raw.githubusercontent.com/JoongDa/VPSKit/main/Hysteria2/phy2.sh && bash phy2.sh
```

**2. 下载并启动管理脚本：**

```bash
wget -O hy2.py https://raw.githubusercontent.com/JoongDa/VPSKit/main/Hysteria2/hy2.py && /usr/bin/python3 hy2.py
```

进入菜单后选择 **1. 安装/更新 Hysteria2**，按提示配置节点。此后在任意目录输入 `hy2` 即可打开管理菜单。

`phy2.sh` 安装 Python 3、CA 证书、curl、wget、OpenSSL 和二维码工具。不会安装 Nginx、启用订阅或修改节点。依赖齐全时可以直接执行第二步；如果 VPS 连 wget 都没有，先执行 `apt-get update && apt-get install -y ca-certificates wget`。

这里明确使用 Bash/Python 解释器执行文件，因此无需先 `chmod +x`。命令中的 `&&` 确保下载成功才执行。

## 菜单与可选订阅

```text
1. 安装/更新 Hysteria2
2. 卸载 Hysteria2
3. Hysteria2 配置
4. Hysteria2 服务管理
5. 订阅链接（可选）
0. 退出
```

普通安装和节点配置只生成本地客户端文件，不自动生成订阅令牌、订阅 Web 文件或 Nginx 模板，也不会为订阅安装 Web 服务。需要订阅时，主动选择 **5 → 1. 配置/修改订阅**，填写订阅域名。单纯打开菜单、查看未配置的链接或按回车返回都不会启用订阅。

从 **0.1.6** 开始，首次配置和修改订阅都必须手动填写域名，没有默认域名；空输入会要求重新填写，不会自动沿用旧域名。下文 `example.com` 仅用于演示，请替换为你自己的域名。

**3. Hysteria2 配置 → 1. 查看配置** 会依次显示服务端配置、已保存的 HY2 分享链接、二维码和客户端文件位置。查看操作不重新生成节点或同步订阅；二维码与显示的链接内容一致。未安装 `qrencode` 时会显示安装命令，仍可复制链接导入。

订阅子菜单提供 **配置/修改、查看链接、同步文件、停用**。首次准备后仍需按下文完成 DNS、HTTPS 和 Nginx 站点配置，菜单不会将“文件已生成”视为“公网已上线”。已经主动配置订阅的用户，后续导出节点配置时自动同步订阅文件。

## 全局命令 hy2

按上面的快速安装启动一次，正常同意使用说明后就会安装全局快捷命令。也可以上传本地新版 `hy2.py`，单独安装或修复快捷命令：

```bash
sudo /usr/bin/python3 hy2.py --install-shortcut
hash -r
hy2
```

此后可以切换到任意工作目录输入 `hy2`。它运行本机 `/usr/local/lib/vpskit/hy2.py`，不会下载网络脚本或在当前目录创建文件。普通用户通过 sudo 运行，会按系统 sudo 配置要求输入密码；没有 sudo 时须先切换 root。命令也支持参数，例如 `hy2 --help`。

正常启动新版脚本也会安装或修复快捷命令。首次运行先要求同意使用说明；已存在 `/etc/hy2config/agree.txt` 时不会重复询问。

如果提示 `hy2: command not found`，先检查：

```bash
command -v hy2
ls -l /usr/local/bin/hy2 /usr/local/lib/vpskit/hy2.py
printf '%s\n' "$PATH"
```

若 PATH 缺少 `/usr/local/bin`，在当前 shell 运行 `export PATH="/usr/local/bin:$PATH"`，并将同一行加入该用户所用 shell 的启动文件。无需更改工作目录。

提供的 `wget -O hy2.py ... && python3 hy2.py` 方案在具备权限、网络和依赖时可以运行，但会覆盖当前目录同名文件、启动指定远程仓库的版本，并且每次都依赖下载成功。旧 VPSKit 启动器也每次下载远程脚本；空仓库或尚未上传 `main/hy2.py` 时会失败。新启动器固定运行本机副本，脚本更新由用户主动执行。

## 从 GitHub 更新管理脚本

```bash
wget -O hy2.py https://raw.githubusercontent.com/JoongDa/VPSKit/main/Hysteria2/hy2.py && sudo /usr/bin/python3 hy2.py --install-shortcut
```

更新后输入 `hy2` 启动。更换管理脚本不会自动升级 Hysteria 内核；内核更新仍使用菜单 1。

源码仓库可以公开；VPS 上的 `node.json`、配置导出、订阅令牌、证书私钥和 Cloudflare Token 不应提交到源码仓库。本目录的 `.gitignore` 包含常见运行产物与备份排除规则。

## 使用自己的域名提供订阅

订阅链接是一个 HTTPS 配置文件地址。客户端读取它取得节点配置；服务器保存新配置后，客户端下一次刷新才会收到变化。GitHub 脚本下载地址与客户端订阅地址是两个用途不同的地址。

本方案使用 **Nginx 静态文件 + Cloudflare HTTPS**，不需要新增常驻 Python 转换服务。准备功能仅生成文件和 Nginx 模板，不会自行更改 DNS、防火墙、证书或现有网站。

### 1. 在 Cloudflare 设置两个独立记录

| 类型 | 名称 | 内容 | 代理状态 | 用途 |
|---|---|---|---|---|
| A | `hy2` | VPS 当前外部 IPv4 | DNS only，灰云 | HY2 直连节点，可选，节点也可直接用 IP |
| A | `sub` | VPS 当前外部 IPv4 | Proxied，橙云 | HTTPS 配置订阅 |

Cloudflare 普通橙云代理处理 HTTP/HTTPS，不能当作 HY2 的 UDP 转发。因此客户端节点地址使用 `hy2.example.com` 或 VPS IP，订阅地址才使用 `sub.example.com`。不要把订阅域名直接当作 HY2 节点域名。仅在 VPS 确有可达的外部 IPv6 时添加 AAAA。

参考：[Cloudflare 代理状态](https://developers.cloudflare.com/dns/proxy-status/)。

### 2. 准备本地订阅文件

先完成 HY2 节点配置，确认 `/etc/hy2config/` 下已有 `links.txt`、`mihomo.yaml`、`sing-box.json`、`surge.conf`。以下 Nginx 安装步骤适用于 Debian/Ubuntu：

```bash
sudo apt-get update
sudo apt-get install -y nginx
hy2
```

选择 **5. 订阅链接（可选） → 1. 配置/修改订阅**，输入 `sub.example.com`。也可继续使用命令行入口 `hy2 --prepare-subscription sub.example.com`；两种入口调用同一个准备函数。

脚本输出五条带随机令牌的订阅 URL，重复执行保留原令牌，因此客户端地址保持不变。Nginx 的默认 worker 组为 `www-data`；其他发行版若使用 `nginx` 组，执行时加 `--web-group nginx`。

生成位置：

| 路径 | 内容 |
|---|---|
| `/etc/hy2config/subscription.json` | 域名、访问令牌、Web 服务组；仅 root 可读 |
| `/etc/hy2config/subscription.nginx.conf` | 待安装的 Nginx 配置模板；包含令牌，仅 root 可读 |
| `/var/lib/vpskit/subscription/` | 仅五个客户端订阅文件；root:Web组，目录 750、文件 640 |

原始 `node.json`、自签证书私钥及 DNS API Token 不复制到 Web 目录。Nginx 只允许五个精确 URL，其他路径返回 404，不开放目录浏览。**链接本身就是访问凭据，Base64 只是编码，不是加密。**

### 3. 为订阅域名安装 HTTPS 证书

在 Cloudflare 的 SSL/TLS → Origin Server 创建覆盖 `sub.example.com` 的 Origin CA 证书，保存证书和私钥。Origin CA 用于 Cloudflare 到 Nginx 的连接；订阅域名必须保持橙云。它不能代替灰云 HY2 节点的公开信任证书。

在 VPS 建立 root 专用证书目录：

```bash
sudo install -d -m 700 /etc/nginx/ssl
sudo nano /etc/nginx/ssl/sub.example.com.pem
sudo nano /etc/nginx/ssl/sub.example.com.key
sudo chmod 600 /etc/nginx/ssl/sub.example.com.pem /etc/nginx/ssl/sub.example.com.key
```

分别粘贴证书 PEM 和私钥 PEM。Cloudflare 的 SSL/TLS 加密模式使用 **Full (strict)**；若域名下已有其他网站，先确认其源站也满足严格模式要求，或使用针对订阅主机名的配置。不要使用 Flexible 模式。

参考：[Cloudflare Origin CA](https://developers.cloudflare.com/ssl/origin-configuration/origin-ca/)。

### 4. 启用 Nginx 订阅站点

模板使用 **TCP 443**，HY2 使用 **UDP 443**，可以同时监听。若 TCP 443 已由 Xray、Apache 或其他程序独占，请先协调已有入口，不要直接停止已有服务。

```bash
sudo ss -ltnp 'sport = :443'
sudo install -m 600 /etc/hy2config/subscription.nginx.conf /etc/nginx/conf.d/vpskit-subscription.conf
sudo nginx -t
```

只有 `nginx -t` 成功后，执行：

```bash
sudo systemctl enable --now nginx
sudo systemctl reload nginx
```

在 GCP VPC 和 VPS 本机防火墙放行 Nginx 所需 TCP 443；这与已有 HY2 UDP 放行规则独立。此方案无需为订阅站开放 TCP 80。

在 Cloudflare 为 `sub.example.com` 添加 **Cache Rule：Bypass cache**，避免旧节点配置被缓存；不要对订阅路径启用浏览器验证码、交互登录或 JS Challenge，否则客户端无法自动获取。模板也发送 `Cache-Control: private, no-store`，并关闭该站点访问日志，减少令牌落入源站日志。

参考：[Nginx alias](https://nginx.org/en/docs/http/ngx_http_core_module.html#alias)、[Cloudflare 缓存控制](https://developers.cloudflare.com/cache/concepts/cache-control/)。

### 5. 导入客户端并设置刷新

下面的 `随机令牌` 必须替换成脚本实际输出的令牌，不是字面输入。

| 客户端/用途 | HTTPS 文件地址 |
|---|---|
| Mihomo / Clash Verge 远程配置 | `https://sub.example.com/s/随机令牌/mihomo.yaml` |
| 支持远程 JSON 配置的 sing-box 客户端 | `https://sub.example.com/s/随机令牌/sing-box.json` |
| Surge 远程配置 | `https://sub.example.com/s/随机令牌/surge.conf` |
| 支持 Base64 节点订阅的客户端，如 Shadowrocket | `https://sub.example.com/s/随机令牌/base64.txt` |
| 支持纯文本 URI 列表的客户端 | `https://sub.example.com/s/随机令牌/links.txt` |

在客户端添加“远程配置/订阅”，粘贴对应地址。Mihomo 是内核，订阅刷新通常由 Clash Verge 等界面管理；sing-box 也取决于具体前端是否提供远程配置刷新。开启对应客户端的自动更新选项即可，建议从每天一次开始；原生 CLI 不会仅因为保存了 URL 就自动定时下载。

Surge 发布的配置自动增加 `#!MANAGED-CONFIG ... interval=86400 strict=false`，保留相同 URL 并允许获取失败时继续使用旧配置。Surge 官方说明自动更新需要主应用处于运行状态，间隔并非精确定时器。[Surge 托管配置](https://manual.nssurge.com/profile/managed-profile.html)

可以先在自己的浏览器打开其中一条 URL，确认返回的是配置文本，而非 HTML 验证页面。只测试错误令牌应得到 404；不要将完整订阅 URL 粘贴到公开测速、验证或转换网站。

### 后续更新与停用

脚本菜单“一键重新配置”或“重新生成本地客户端配置”会自动同步发布的订阅文件。只替换已有静态文件时不用重载 Nginx。若手动修改服务端配置，需同步更新客户端导出；本脚本仍按原有 `node.json` 导出，不能自动推断手动修改的所有内容。

单独同步已有导出：

```bash
hy2 --sync-subscription
```

改域名后重新执行 `--prepare-subscription 新域名`，补齐新证书并重新安装模板、检查和重载 Nginx。令牌泄露时，删除 `/etc/hy2config/subscription.json` 后重新准备可生成新令牌；必须重新安装模板并重载 Nginx，旧 URL 才失效，客户端也要换成新地址。

停用时选择 **5. 订阅链接 → 4. 停用订阅**，确认后删除订阅设置、待安装模板及发布的五个文件，停止后续自动同步；HY2 节点、本地客户端导出、证书和不相关文件保留。已安装的 Nginx 站点不自动修改，原 URL 因文件移除返回 404。客户端已下载的配置不会远程删除。

卸载 HY2 也会删除本工具发布的五个订阅文件。若要额外移除订阅站点入口，可移除 `/etc/nginx/conf.d/vpskit-subscription.conf` 后检查并重载 Nginx。

## 验证范围

在仓库的 `Hysteria2/` 目录中执行：

```bash
python3 -m unittest -v test_hy2.py
python3 -m py_compile hy2.py
```

测试覆盖本地快捷命令、跨工作目录启动与参数传递、拒绝同意时不安装、订阅令牌稳定性、发布文件白名单、刷新与 Nginx 模板约束。不会修改真实 systemd、防火墙或 Cloudflare 配置。POSIX 权限断言在相应平台执行；真实 VPS、Nginx HTTPS 和各客户端导入仍需按上面的步骤验证。
