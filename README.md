<<<<<<< HEAD
# AstrBot 网易云音乐「一起听」链接提取插件

[![AstrBot](https://img.shields.io/badge/AstrBot-4.16%2B-blue)](https://github.com/AstrBotDevs/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-orange)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-aiocqhttp-lightgrey)](https://docs.go-cqhttp.org/)

> 实时监控群聊消息，自动提取网易云音乐「一起听」邀请链接，支持触发词发送。

## 功能特性

- **自动存储**：检测到「一起听」JSON 卡片时自动提取并存储链接和卡片数据
- **触发发送**：收到触发词后，根据配置的发送格式发送内容
- **多种格式**：支持纯文本链接、原始 JSON 卡片、链接+卡片同时发送
- **自定义前后缀**：支持在发送内容前后添加自定义文本
- **时间差变量**：支持 `{time_diff}` 变量，显示友好的时间差格式（如3小时前）
- **关键词管理**：支持通过指令动态查看、添加和删除触发关键词
- **多群监听**：支持配置监听的群聊 ID 列表
- **自定义触发词**：支持配置多个触发关键词

## 工作流程

```
群内发送「一起听」卡片 → 插件自动存储（不发送）
群内发送触发词（如"一起听"） → 按配置的格式发送存储的内容
```

## 快速开始

### 安装

1. 将 `astrbot_plugin_netease_listentogether` 文件夹放置到 `data/plugins/` 目录下
2. 重启 AstrBot 或在 WebUI 中重载插件

### 配置

在 AstrBot WebUI 插件配置面板中可设置以下参数：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_monitoring` | bool | `true` | 启用/停用插件监听 |
| `monitored_groups` | text | 空 | 监听的群聊 ID，多个用英文逗号分隔 |
| `trigger_keywords` | text | `一起听,一起来听,listen together,一起聽` | 触发关键词 |
| `prefix_text` | text | 空 | 自定义前缀内容，支持 `{time}` 和 `{time_diff}` 变量 |
| `suffix_text` | text | 空 | 自定义后缀内容，支持 `{time}` 和 `{time_diff}` 变量 |
| `send_format` | string | `link` | 发送格式：`link`、`card`、`both` |
| `link_pattern` | text | 内置正则 | 网易云链接匹配正则表达式 |
| `reply_template` | text | 内置模板 | 链接回复模板 |

## 指令列表

| 指令 | 说明 |
|------|------|
| `/一起听 config` | 查看当前完整配置 |
| `/一起听 status` | 查看当前群存储的链接和卡片状态 |
| `/一起听 clear` | 清除当前群存储的链接和卡片数据 |
| `/一起听 keywords` | 查看当前触发关键词 |
| `/一起听 add_keyword <关键词>` | 添加触发关键词 |
| `/一起听 remove_keyword <关键词>` | 删除触发关键词 |
| `/一起听 help` | 显示帮助信息 |

## 支持变量

| 变量 | 说明 | 可用位置 |
|------|------|----------|
| `{links}` | 提取到的一起听链接 | `reply_template` |
| `{sender_name}` | 分享者昵称 | `reply_template` |
| `{time}` | 存储时间（YYYY-MM-DD HH:MM:SS） | 前缀、后缀、模板 |
| `{time_diff}` | 动态时间差（如3小时前） | 前缀、后缀、模板 |

## 注意事项

- 链接和卡片数据使用本地 JSON 文件持久化存储，重启后数据不会丢失
- 每个群只存储最近一次发送的「一起听」数据
- 需要确保 AstrBot 具有在群内发送消息的权限

## 许可证

本项目基于 MIT 许可证开源。详见 [LICENSE](LICENSE) 文件。

## 贡献

欢迎提交 Issue 和 Pull Request！
=======
# astrbot_plugin_netease_listentogether
网易云音乐一起听群内提醒插件
>>>>>>> db297999a15c5843bc0ee76a36c0b7769da63345
