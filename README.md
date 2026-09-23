# 订单分析代码

本仓库保存 `scripts/generate_html`（订单看板与销量预测）和 `scripts/销量规律`（销量规律分析与预测辅助）的程序代码。运行所需的原始 Excel 和生成的报告留在各自电脑，不上传到公开仓库。

## 在另一台 Windows 电脑下载

先安装 Git 和 Python，然后在 PowerShell 中运行：

```powershell
git clone https://github.com/rabbittttt/Order_Analysis.git
cd Order_Analysis
python -m pip install -r scripts/generate_html/requirements.txt
```

将自己的业务 Excel 放入仓库根目录的 `input_file`，运行后报告会写入根目录的 `output_file`。具体输入文件名、目录结构和运行方式请看 [看板说明](scripts/generate_html/README.md) 与 [销量规律说明](scripts/销量规律/README.md)。原说明中的 `D:\05 AI脚本\PythonProject\订单分析` 是旧电脑路径，迁移后换成新电脑上的仓库目录。

此仓库不含真实订单 Excel。只下载代码无法重现旧电脑的分析结果；业务数据需另行安全迁移。

## 更新版本

在这个 Git 仓库里修改代码，然后运行：

```powershell
git status
git add scripts/generate_html scripts/销量规律 README.md .gitignore
git diff --cached --stat
git commit -m "描述这次修改"
git push
```

另一台电脑更新代码时，在该仓库目录运行 `git pull`。如果两台电脑都修改了代码，先在当前电脑 `git pull`、处理可能出现的冲突，再 `git push`。
