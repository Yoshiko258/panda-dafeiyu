# qqmind 本地修复版（Fork 快照）

这是当前安装的 qqmind 0.3.8 的完整快照，只改了一行：

```python
# 原版：协程没有 await，主动回复监听不会执行
self._proactive_reply_watch(puid)

# 修复
await self._proactive_reply_watch(puid)
```

`metadata.yaml` 里的 `repo` 已置空，所以 AstrBot 不会从上游市场覆盖这个目录。

## 推到你自己的 GitHub

1. 在 GitHub 新建一个空仓库，名字随意，例如 `astrbot_plugin_qqmind`（不要勾选 README）。
2. 在本目录执行（把 `<你的用户名>` 换掉）：

```powershell
cd I:\dshdafeiyu\patches\qqmind-fork
git remote add origin https://github.com/<你的用户名>/astrbot_plugin_qqmind.git
git push -u origin main
```

3. 在 AstrBot：插件 → 安装插件 → 填

```text
https://github.com/<你的用户名>/astrbot_plugin_qqmind
```

安装后它会使用同一个插件名，原有配置和数据目录不变；如果不放心，先把
`astrbot/data/plugins/astrbot_plugin_qqmind` 备份一份。

## 以后更新

这个仓库是“当前安装版的快照”，不是上游源码仓库。上游 GitHub 的 `main.py` 已经模块化，
和这份 137 KB 的单文件构建不一样，不能直接 merge。以后要么：

- 只改这个 fork，提交后 push，AstrBot 从你的仓库更新；
- 或者等上游发布新版本时，重新做一次快照并重打这一行。

## 不想建 GitHub 仓库

继续用 `I:\dshdafeiyu\patches\apply_patches.ps1`：每次 qqmind 更新后运行一次，
再在 AstrBot 里重载插件。这个脚本不会自动运行，但至少补丁不会丢。
