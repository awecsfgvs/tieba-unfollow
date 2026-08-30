# 贴吧取关助手 (TiebaUnfollow)

一个带可视化界面的 **百度贴吧取关工具**：用于取消关注已经关注的贴吧，包括 **已关闭 / 异常的贴吧**——这类吧在 App 或网页里通常已经无法打开和正常取关，但用本工具仍可通过接口解除关注。

## 功能

- 输入 BDUSS 一键拉取**全部关注列表**（吧名 + fid，支持搜索过滤）
- 取消关注，实时日志显示每个吧的结果
- 已关闭的吧同样出现在列表中，可直接取关
- 暗色现代化界面，可打包为单文件 exe

## 接口来源（说明）

本工具调用的所有数据接口都是**百度贴吧移动客户端（Android App）内部使用的 HTTP 接口**。这些接口没有公开文档，是社区通过抓包、逆向客户端得到的，主要涉及三个接口：

| 用途 | 接口 | 关键参数 |
| --- | --- | --- |
| 获取关注列表 | `POST https://tiebac.baidu.com/c/f/forum/like` | `BDUSS`、`page_no`、`page_size` |
| 取消关注 | `POST https://tiebac.baidu.com/c/c/forum/unfavolike` | `BDUSS`、`fid`、`tbs` |
| 获取 tbs 令牌 | `GET https://tieba.baidu.com/dc/common/tbs` | `BDUSS`（Cookie） |

**为什么已关闭的吧也能取关**：贴吧被关闭后，它的记录仍保留在账号的关注列表里，只是页面无法访问；而取消关注接口按 `fid` 操作，不依赖页面，所以即使吧已关闭也能正常解除关注。

**接口细节从哪来**：接口路径、参数、字段结构、`tbs` 机制等，参考自开源库 **aiotieba**（[github.com/lumina37/aiotieba](https://github.com/lumina37/aiotieba)，MIT License）以及贴吧社区公开的逆向资料。本项目没有复制 aiotieba 的代码，仅将其作为 Python 依赖使用（源码运行时需要安装）；打包的 exe 已把相关依赖一并内置。

## 使用

### 直接使用 exe（推荐）

下载 [Releases](https://github.com/awecsfgvs/tieba-unfollow/releases) 里的 `TiebaUnfollow.exe`，双击运行：

1. 填入 BDUSS（浏览器登录贴吧后按 F12 → Application → Cookies → 复制 `BDUSS` 的值）；
2. 点 **刷新关注列表**；
3. 在列表中选择要取关的吧（支持多选、搜索）；
4. 点 **取消关注选中**。

### 源码运行

```bash
pip install aiotieba
python unfollow_gui.py
```

### 打包成 exe

```bash
pip install pyinstaller pillow
pyinstaller --onefile --noconsole --name TiebaUnfollow --icon icon.ico --add-data "icon.ico;." unfollow_gui.py
```

## 安全提示

- BDUSS 等同于账号登录凭证，请勿泄露给他人；
- 取关不可逆（之后可以重新关注），操作前请确认所选；
- 本工具仅供个人学习使用，请遵守贴吧平台规则，使用风险自负。

## License

MIT
