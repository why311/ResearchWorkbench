# 研舟 · ResearchWorkbench

面向学生的科研工作台，围绕论文阅读、证据定位、实验复现与成果整理构建研究流程。

## 当前公开版本

项目与文献管理：React页面、FastAPI服务、SQLite项目存储，支持PDF、UTF-8文本和Markdown导入、分页原文阅读、逐段批注、阅读笔记导出及原文件下载。
已有本地实现按可运行阶段整理后逐步公开；本仓库当前版本尚不包含完整科研功能。提交与验证使用实际时间记录。

## 运行

使用Python 3.12与Node.js 20或更新版本。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
npm install
npm run build
.venv/Scripts/python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8787
```

打开 http://127.0.0.1:8787 。新建项目并填写研究问题，在“项目文献”中导入全文，选择资料后按页阅读。每次显示最多100段，可以继续翻页段；下载保留原文件。

单篇最大20MB、300页、100万字符。当前仅提取PDF可选文字，扫描PDF未包含OCR；支持逐段标记重点/待弄清/已理解、保存或编辑个人批注，并导出带页码及原文的Markdown笔记。单篇最多200段批注，每段4000字。尚未包含模型精读、检索、实验执行或成果导出。数据保存在本地data目录，未配置公网账号和访问控制。

## 后续阶段

结构化精读 → 实验运行与数据分析 → 成果引用 → 结构化PDF与OCR → 证据比较和研究任务工具编排 → 双语阅读与引用图谱。

运行数据、密钥、依赖与临时文件不上传。阶段记录见 [开发记录](docs/development.md)。

## 验证

```powershell
.venv/Scripts/python.exe -m pytest tests -q
npm run build
```
