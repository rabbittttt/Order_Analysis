# 订单分析代码

本仓库保存 `generate_html`（订单看板与销量预测）和 `销量规律`（销量规律分析与预测辅助）的程序代码。两个文件夹直接位于仓库根目录。运行所需的原始 Excel 和生成的报告留在各自电脑，不上传到公开仓库。

## 在另一台 Windows 电脑下载

推荐两台电脑都把仓库放在 `D:\05 AI脚本\PythonProject\订单分析\scripts`。仓库根目录直接包含两个代码文件夹，数据保留在 `订单分析\input_file` 和 `订单分析\output_file`。

先安装 Git 和 Python 3.10 或更新版本。下面的克隆命令仅适用于目标 `scripts` 不存在或为空；已经有公司仓库时使用后面的“公司电脑更新”流程：

```powershell
git clone -o github https://github.com/rabbittttt/Order_Analysis.git "D:\05 AI脚本\PythonProject\订单分析\scripts"
Set-Location -LiteralPath "D:\05 AI脚本\PythonProject\订单分析\scripts"
python -m pip install -r generate_html/requirements.txt
```

历史及车型 Excel 放入 `订单分析/input_file/销量预测输入文件`，当前订单汇总报表放入 `订单分析/output_file`。生成的汇总 Excel、网页和销量规律报告也写入该 `output_file`。代码根目录名为 `scripts` 时，数据根目录自动取它的上一级；克隆到其他名称时，默认取代码根目录。具体文件要求见 [看板说明](generate_html/README.md) 与 [销量规律说明](销量规律/README.md)。

在仓库根目录运行：

```powershell
python generate_html/main.py
python 销量规律/analyze_sales_patterns.py
```

第二条命令需要数据根目录下准备好的 `output_file/鸿蒙智行销量数据汇总.xlsx`。

此仓库不含真实订单 Excel。只下载代码无法重现旧电脑的分析结果；业务数据需另行安全迁移。

## 更新版本

在这个 Git 仓库里修改代码，然后运行：

```powershell
git status
git add generate_html 销量规律 README.md .gitignore
git diff --cached --stat
git commit -m "描述这次修改"
git push github main
```

本机主要负责推送；如需获取别处提交，在干净的工作区运行 `git pull --ff-only github main`。公司的完整仓库按下一节指定目录同步，不直接合并这个公开仓库的历史。

## 公司电脑更新

公司电脑的完整 `scripts` 由公司仓库 `codehub` 管理，其中也包含这两个公开目录。配置第二个远程 `github` 获取本仓库内容，然后仅导入 `generate_html`、`销量规律`，再作为公司仓库自己的提交推送到 `codehub`。不合并两个仓库的完整历史，也不导入本仓库根目录的 `.gitignore` 或 README，以保留公司仓库对其他脚本的管理。

公司远程名使用 `codehub`，地址和分支保留公司已有配置。首次增加 GitHub 获取源（已有 `github` 时跳过添加）：

```powershell
git remote add github https://github.com/rabbittttt/Order_Analysis.git
git remote set-url --push github disabled://github-pull-only
git config remote.pushDefault codehub
```

每次更新，先用 `git status` 确认工作区干净，再获取并预览差异：

```powershell
git fetch github main
git diff --name-status HEAD github/main -- generate_html 销量规律
```

确认这两个目录以 GitHub 版本为准后导入、提交、推送：

```powershell
git restore --source=github/main --staged --worktree -- generate_html 销量规律
git diff --cached --stat
git commit -m "同步 GitHub 订单分析代码"
git push codehub HEAD
```

这会同步两个目录内的已跟踪文件及删除。若其中还混有公司专用文件，首次可在 `restore` 加上 `--overlay` 保留额外文件；该模式不会同步 GitHub 的文件删除，需另行处理。其他公司脚本及公司根目录的 README、`.gitignore` 不在导入范围内。
