@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 尚未安装后端依赖，请按 README.md 中的首次安装步骤配置。
  pause
  exit /b 1
)
if not exist "dist\index.html" (
  echo 尚未构建界面，请先运行 npm install 和 npm run build。
  pause
  exit /b 1
)
echo 研舟工作台：http://127.0.0.1:8787
echo 保持此窗口运行；按 Ctrl+C 停止服务。
".venv\Scripts\python.exe" -m uvicorn backend.app:app --host 127.0.0.1 --port 8787
pause
