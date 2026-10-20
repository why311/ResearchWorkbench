# 研舟 · ResearchWorkbench

面向学生的科研工作台，围绕论文阅读、证据定位、实验复现与成果整理构建研究流程。

## 当前公开版本

最小可运行骨架：React页面、FastAPI服务、SQLite项目列表与新建项目。
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

打开 http://127.0.0.1:8787 。可新建项目、保存研究问题并查看已保存项目。数据保存在本地data目录，未配置公网账号和访问控制。

## 后续阶段

项目与文献管理 → 原文定位与精读批注 → 实验运行与数据分析 → 成果引用 → 结构化PDF与OCR → 证据比较和研究任务工具编排 → 双语阅读与引用图谱。

运行数据、密钥、依赖与临时文件不上传。阶段记录见 [开发记录](docs/development.md)。
