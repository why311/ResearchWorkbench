# 第三方参考与许可

## 本机文档解析依赖

以下作为依赖使用，许可文件保留在对应Python发行包中；本项目未复制它们的源码。重新分发可执行包、OCR模型或PDFium二进制时，需要同时携带相应发行包中的完整许可与第三方声明。

- pdfplumber：MIT，https://github.com/jsvine/pdfplumber 。用于原生文字、坐标和线框表格提取。
- pypdfium2：BSD-3-Clause / Apache-2.0及依赖许可，https://github.com/pypdfium2-team/pypdfium2 。仅逐页渲染；PDFium另含发行包列出的第三方许可。
- RapidOCR / rapidocr-onnxruntime：Apache-2.0，https://github.com/RapidAI/RapidOCR 。使用1.4.4发行包内的本地模型进行扫描页OCR。
- psutil：BSD-3-Clause，https://github.com/giampaolo/psutil 。用于解析进程的实际内存监测。

## paper-xray

来源：https://github.com/Wang-auspicious/paper-xray

研舟的精读提示与交互设计参考该项目 SKILL.md 的证据等级、机制拆解、公式手算、复现诊断及明确理解反馈。后端、数据库与 React 界面由研舟实现，未执行上游技能脚本或安装到用户全局技能目录。以下保留上游许可。

MIT License

Copyright (c) 2026 Wang-auspicious

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
