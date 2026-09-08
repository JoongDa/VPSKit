# VPSKit

VPS 部署与管理工具，按功能分别存放。

| 工具 | 目录与说明 |
|---|---|
| Hysteria2 安装、配置、服务管理及可选订阅 | [Hysteria2](Hysteria2/README.md) |

## Hysteria2 快速安装

适用于 Debian / Ubuntu。在 VPS 以 root 运行；普通用户先执行 `sudo -i`。

首次安装依赖：

```bash
wget -O phy2.sh https://raw.githubusercontent.com/JoongDa/VPSKit/main/Hysteria2/phy2.sh && bash phy2.sh
```

下载并启动管理脚本：

```bash
wget -O hy2.py https://raw.githubusercontent.com/JoongDa/VPSKit/main/Hysteria2/hy2.py && python3 hy2.py
```

进入菜单选择 `1. 安装/更新 Hysteria2`。以后在任意目录输入 `hy2` 即可启动；订阅功能默认不配置，需要时进入菜单 `5`。

代码已移到 `Hysteria2/`，下载地址必须包含这个目录。此前 VPS 上已安装的本地快捷命令继续可用。升级管理脚本也使用上面的新地址。

详细配置、更新、订阅和测试方法见 [Hysteria2 使用说明](Hysteria2/README.md)。
