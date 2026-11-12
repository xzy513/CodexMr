# CodexMr

CodexMr 是一个 Windows 桌面悬浮窗，显示当前 ChatGPT 账号的 Codex 限额，支持贴边自动收起、透明度调节和浏览器登录。

## 使用

- 左键拖动窗口，贴近屏幕边缘后自动收起；鼠标移到露出的边缘可展开。
- 点击左上角 CODEX 打开 ChatGPT；右键可登录、刷新、查看重置时间、调整透明度或退出。
- 限额每 60 秒刷新一次。账号或服务未返回限额时可能没有数据。

## 从源码运行

需要 Windows、带 tkinter 的 Python，以及通过 npm 安装的 Codex CLI：

```powershell
npm install -g @openai/codex
python widget.py
```

首次运行时按提示在浏览器登录 ChatGPT。程序使用独立的 `%LOCALAPPDATA%\CodexMr` 数据目录，登录凭据不会保存在项目目录中。该项目非 OpenAI 官方产品。

运行测试：

```powershell
python -B -m unittest -v
```

此源码仓库不包含预编译 EXE。单文件版可通过 PyInstaller 构建，并需将 Windows 版 Codex CLI 作为 `codex-runtime/codex.exe` 一同打包。
