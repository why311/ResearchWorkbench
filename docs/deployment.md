# 运行与部署

研舟默认以单用户模式运行。按 README 构建前端，再在本机启动一个 Uvicorn 进程。

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8787
```

## 在服务器上通过 HTTPS 使用

在服务器构建前端、安装后端依赖，并在启动 Uvicorn 的终端或服务配置中设置以下环境变量。

| 变量 | 用途 |
| --- | --- |
| `RESEARCH_DATA_DIR` | 可选的数据目录，建议使用仅服务账号可访问的绝对路径。默认使用项目下的 `data/`。 |
| `RESEARCH_USERS` | 用户名到密码的 JSON 对象。每个密码至少 16 个字符。第一个用户为维护者，负责模型设置和准备 Docker 镜像。 |
| `RESEARCH_ALLOWED_ORIGINS` | 浏览器访问的 HTTPS 来源，如 `https://research.example.org`。多个来源用逗号分隔。 |

启动后端时保留回环监听。使用 [Caddy 配置样例](../deploy/Caddyfile) 把域名转发到 `127.0.0.1:8787`。将 `RESEARCH_HOST` 设为实际域名，并配置域名解析和 HTTPS 所需的端口。

```sh
RESEARCH_HOST=research.example.org caddy run --config deploy/Caddyfile --adapter caddyfile
```

启用 `RESEARCH_USERS` 后，浏览器通过 HTTP Basic 登录。用户访问自己创建的项目，维护者也能访问启用账号前创建的本地项目。外部仓库运行需要服务账号可以使用 Docker，并由维护者先准备运行镜像。

## 数据和论文模板

数据目录包含 SQLite 数据库、原件、模型设置和运行产物。备份时先停止服务，再复制整个目录。

Word 导出默认使用通用格式。要使用自己的论文模板，将有权使用的 `.docx` 放在数据目录下的 `templates/school.docx`，在成果页选择「本机论文模板」。模板用于正文、标题、页眉页脚及表格样式。成果页还可导出 Markdown、指标 CSV、来源 JSON 和生成的图表。
