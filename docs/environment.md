# 运行环境

## 软件与依赖

| 项目 | 用途或安装入口 |
| --- | --- |
| Python 3.11 或 3.12 | 后端与解析工作进程。用 `requirements.txt` 安装 |
| Node.js 22 与 npm | 前端构建。用 `npm ci` 安装 `package-lock.json` 记录的依赖 |
| Docker Desktop 或兼容的 Docker Engine | 执行实验容器。用 `Dockerfile.runner` 构建镜像 |
| Git | 克隆仓库、查看真实提交历史 |

## 配置方式

`.env.example` 是变量模板，服务启动时从进程环境读取。Windows PowerShell 可在服务启动前使用 `$env:变量名 = '值'`。模型密钥、账号口令使用终端的安全输入或部署环境的密钥配置注入。公开仓库只提交空模板。本机设置页保存的模型字段优先于同名环境变量，存放在数据目录的 `model.json`。

| 变量 | 用途 |
| --- | --- |
| `RESEARCH_DATA_DIR` | 可写的数据目录，省略时使用仓库下的 `data/` |
| `RESEARCH_MODEL_URL` | 兼容 Chat Completions 的基础地址，按模型供应商的路径填写 |
| `RESEARCH_MODEL_NAME` | 模型标识。原页分析需要支持图像输入的服务 |
| `RESEARCH_MODEL_KEY` | 模型访问密钥，留空模板由实际环境注入 |
| `RESEARCH_USERS` | 可选的用户名与口令 JSON 对象。口令至少 16 字符，第一位用户为维护者 |
| `RESEARCH_ALLOWED_ORIGINS` | 逗号分隔的额外站点来源，每项包含协议、主机及需要的端口 |
| `HTTPS_PROXY`、`NO_PROXY` | 按实际网络需要配置。可为环回地址设置排除项 |

默认服务地址为 `http://127.0.0.1:8787/`。`GET /api/status` 可确认服务状态与 Docker 镜像是否就绪。开发模式的 Vite 服务位于 5178 端口，并将 API 转发到 8787 端口。需要向局域网或公网提供服务时，部署方负责 TLS 反向代理、访问账号和站点来源配置。线上演示的地址与账号单独交付。

首次下载本地 MiniLM 模型、检索学术题录或调用外部模型需要网络。外部实验容器运行时禁网，挂载的代码目录只读，运行结果写入 `/output`。项目原件、数据库和运行输出可按数据目录整体备份。
