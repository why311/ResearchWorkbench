# 研舟 · ResearchWorkbench

研舟是一款本地科研工作台，面向学生和小型研究团队。你可以按项目管理论文和研究问题，从原文定位证据，记录实验参数与结果，再把分析和写作草稿导出。

## 功能

- **文献管理与阅读**：导入 PDF、Markdown 和 UTF-8 文本，按页查看原文，保存批注、精读笔记和阅读待办。结构化 PDF 支持后台解析、扫描页 OCR 和原件下载。
- **文献发现与引用**：检索 Crossref、arXiv 和 PubMed，跟踪 arXiv 主题，批量获取 arXiv 和 NLM PMC 的开放全文。核对 DOI 或 arXiv 引用后，可关联项目内文献并导出引用关系。
- **证据与写作**：使用关键词或本地多语言语义模型定位原文，逐篇比较论文的实验设定。支持研究任务、双语对照、综述和开题草稿，导出时保留引用页码和原文片段。
- **实验与数据分析**：运行内置 Iris 分类示例，或在 Docker 中运行导入的 Python 仓库。按同一组随机种子做参数对照，导入 CSV、TSV 或 XLSX 进行清洗、统计和绘图，导出参数、日志、结果及复跑材料。

- **成果同步与导出**：将综述或开题草稿转为成果文稿，插入原文引用，绑定实际运行指标和图表，导出 Markdown、ZIP 或 Word。

## 快速开始

使用 Python 3.12 和 Node.js 20 或更新版本。在项目目录运行以下 PowerShell 命令。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install
npm run build
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8787
```

打开 [本地工作台](http://127.0.0.1:8787)，创建项目并填写研究问题。可以先导入一篇论文做批注，也可以打开「实验与分析」运行 Iris 示例。

## 使用说明

| 想做什么 | 从哪里开始 |
| --- | --- |
| 阅读和批注文献 | 在「项目文献」导入文件，选择文献后按页查看。普通导入支持最大 20 MB、300 页的可提取文字 PDF。 |
| 处理扫描件或长 PDF | 在「文献处理与发现 → PDF与OCR」导入。支持最大 32 MB、2,000 页，任务可停止后继续。识别结果可对照原件核对。 |
| 用中文查找英文原文 | 在「研究与写作 → 语义检索」准备本地模型，为选中的文献建索引，再输入问题。首次下载模型需要联网，后续索引和检索在本机执行。 |
| 运行外部代码 | 启动 Docker，在「实验与分析 → 实验复现」导入 GitHub 仓库或 ZIP，准备运行环境并选择 Python 入口。仓库以只读方式挂载，容器禁网，并限制 CPU、内存、进程数与运行时间。 |
| 对照实验或处理表格 | 在「批量对照」配置变体、随机种子和比较指标。在「数据分析」导入表格或已有运行产物，选择处理规则并导出复跑包。 |

项目数据和上传文件默认保存在本地 `data/` 目录。自定义数据目录、账号、HTTPS 代理和论文模板的配置见 [运行与部署](docs/deployment.md)。

## 配置聊天模型

模型辅助精读、页段翻译和综述使用兼容 Chat Completions 的服务。在「模型设置」填写基础地址、模型名称和密钥，保存后可验证连接。也可以在启动终端设置 `RESEARCH_MODEL_URL`、`RESEARCH_MODEL_NAME` 和 `RESEARCH_MODEL_KEY` 作为初始配置。变量示例见 [.env.example](.env.example)。

手动阅读、本地检索、实验和数据分析可独立使用。调用聊天模型时，相关原文会发送给所配置的服务。生成内容可以回看引用，便于核对上下文和结论。

## 开发

前端使用 React、TypeScript 和 Vite。后端使用 FastAPI 和 SQLite。

```powershell
npm run dev
.\.venv\Scripts\python.exe -m pytest tests -q
```

前端开发时另开终端运行后端，Vite 将 `/api` 请求转发到本地服务。第三方组件及来源见 [第三方说明](THIRD_PARTY_NOTICES.md)。
