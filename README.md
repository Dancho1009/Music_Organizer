# 音乐整理

这是一个先生成计划、再执行迁移的桌面工具。它只处理 FLAC、MP3、同目录同名 LRC 和 `cover.ico`，并在执行后逐文件验证，也可以按操作日志回滚。

## 整理规则

- FLAC：`FLAC 目标目录\主艺术家\完整专辑名\原文件名.flac`
- MP3：`MP3 目标目录\主艺术家\完整专辑名\原文件名.mp3`
- 歌词：只自动匹配与音频同目录、同 stem 的 `.lrc`；实际含歌词才随音频迁移。空文件、只有作词作曲信息或无法确认的歌词会留给人工处理。
- 封面：同目录的 `cover.ico` 随专辑归档；目标已有不同封面时保留目标，不覆盖。
- 冲突：目标已有不同文件时阻止执行，不会覆盖。

默认使用“移动”。同卷时优先原子重命名；跨卷或网络挂载目录会在目标目录内复制到临时文件，校验大小和 SHA-256 后原子落位，再删除源文件。硬链接只允许同一文件系统。

## 运行

需要 Windows、Python 3.11 或更高版本、Node.js，并确保 `python` 命令可用。

依赖安装完成后，直接双击项目根目录的 `启动音乐整理.bat` 即可启动；英文入口是 `Start-MusicOrganizer.bat`。

```powershell
cd D:\Utilits\Music_Organizer
python -m pip install -e .\engine
npm install
Start-Process .\Start-MusicOrganizer.bat
```

如需指定 Python，可在启动前设置：

```powershell
$env:MUSIC_ORGANIZER_PYTHON = 'C:\Path\To\python.exe'
npm run dev
```

## 使用顺序

1. 迁移整理模式下选择源目录，以及 FLAC 或 MP3 中至少一个目标目录；未选择目标目录的格式不会进入本次计划。本地路径、UNC 路径和已挂载网络目录都可以直接填写。
2. 如只清理异常歌词，切换到“仅清理无效歌词”模式，只选择源目录即可；该模式不会读取音频标签，也不会移动音频或封面。
3. 生成计划，处理阻断项和待确认歌词，再重新生成计划。
4. 迁移整理模式勾选“我已检查异常项目”后执行计划；歌词清理模式直接验证清理计划。
5. 对空歌词或仅有作词作曲信息的歌词，可以在计划明细中选择“删除歌词”。计划验证通过后，点击“检查异常歌词”，确认数量后永久删除。
6. 如执行中断，重新打开应用后使用“继续”或“回滚”；工具会先对照日志检查当前磁盘状态。

迁移计划、操作日志和验证报告保存在 Electron 用户数据目录下的 `migration-data` 中。

## 检查

```powershell
$env:PYTHONPATH = "$PWD\engine"
python -m pytest .\tests\engine -q
npm run check
```
