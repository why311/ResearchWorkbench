# 研舟 · ResearchWorkbench

面向学生和小型研究团队的科研工作台。在同一项目里导入文献、核对原文、准备复现实验、分析数据，并把已核对的引文和真实运行结果带入文稿。

## 能做什么

- **文献与开题**。导入 PDF、TXT 与 Markdown。支持扫描页 OCR、版本比较、原文与译文联动、带页段来源的问答、项目内引用图谱，以及 Crossref、arXiv、PubMed 检索与 arXiv 追踪。
- **实验复现**。从原文整理复现条件，运行内置 Iris 案例，或将外部 Python 仓库放入隔离容器。记录逐次参数、日志和实际指标，并支持多种子对照。
- **数据分析**。读入 CSV、TSV、XLSX 或运行产生的数据，配置清洗步骤，计算描述统计、分组统计和 Pearson 相关；导出图表、数据和复跑代码。
- **成果同步**。把项目里的原文引文和成功运行的指标绑定到文稿；导出 Word、Markdown 或含来源文件的 ZIP。

公开仓库入口为 [why311/ResearchWorkbench](https://github.com/why311/ResearchWorkbench)。

## 技术架构

浏览器由 React、TypeScript 与 Vite 构建，通过 HTTP 调用 FastAPI。FastAPI 用 SQLite 管理项目、文档页段、引用和运行记录，原件及成果按项目保存在本机数据目录。独立 PDF 工作进程逐页解析原件，扫描页用 RapidOCR。证据检索融合 TF-IDF 与可选的本地多语言 MiniLM；聊天、翻译和页面解读使用兼容 Chat Completions 的模型接口。外部实验由 Docker 执行，限制网络、资源和可写目录。

| 路径 | 主要职责 |
| --- | --- |
| `src/` | 工作区、原文与引用定位、结果渲染 |
| `backend/` | API、文档解析、检索、模型调用、实验与成果 |
| `tests/` | 接口和流程回归 |
| `examples/` | Iris 流程示例与可导入仓库 |
| `docs/environment.md` | 环境变量、依赖及启动说明 |

## 安装与运行

需要 Git、Python 3.11 或 3.12、Node.js 22 和 npm。Docker Desktop 仅在运行隔离实验时使用。

```powershell
# 从随附开发历史包检出本次交付
# 将下列路径替换成开发历史包所在位置
git clone "研舟开发历史.bundle" ResearchWorkbench
cd ResearchWorkbench
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
npm run build
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8787
```

打开 [本机工作台](http://127.0.0.1:8787/)。后续在 Windows 上可直接双击 `启动研舟.cmd`。若使用 Python 3.11，将命令中的 `py -3.12` 改为 `py -3.11`。前端开发时保留后端 8787 端口，另开终端运行 `npm run dev`，访问 5178 端口。

安装后可先新建项目，导入一篇自有使用权限的 PDF，在“证据比较”提问并打开出处，再运行一次 Iris 实验。要体验隔离实验，先启动 Docker 并执行：

```powershell
docker build -t research-workbench:0.1 -f Dockerfile.runner .
```

随后在“实验复现”导入 `examples/iris-repository.zip`，入口选择 `train.py`，依次填写 `--config`、`/output/config.json`、`--output`、`/output`，每项单独一行。

## 模型与配置

[环境变量模板](.env.example) 记录数据目录、模型地址、名称和密钥，以及可选的账户与站点来源。将所需变量设置在启动进程的终端中。已保存的本机配置优先使用，模型密钥由运行环境提供。首次准备本地语义模型需联网下载权重。无聊天模型时仍可导入全文、检索原文、手工精读和执行实验。

模型调用会发送当前请求需要的原文或原页图像。系统核验引文位置和逐字摘录，分析结论由作者复核。图谱中的 PageRank 描述当前项目内已确认的引用关系。[第三方来源](THIRD_PARTY_NOTICES.md)

## 团队信息

| 项目 | 内容 |
| --- | --- |
| 团队名称 |  |
| 成员及分工 |  |
| 指导教师 |  |
