# TVBox Manager

TVBox / FongMi TV 源管理与配置方案工具。管理 Spider 源文件（JS/Python/JAR）、站点、
配置方案，一键发布为 TVBox 兼容 `vod.json`。

## 启动

```bash
./start.sh            # 后端 8000 端口，浏览器打开 http://127.0.0.1:8000
```

开发模式（前端热更新）：

```bash
cd frontend && npm run dev   # vite dev 9981，代理 /api 到 8000
cd backend && python3 -m uvicorn app.main:app --port 8000
```

## 功能

- **源库**：JS/Python/JAR 源文件上传、URL 导入、在线编辑（文本源）、版本历史与回滚、
  引用统计、SHA-256 去重。
- **站点**：站点 CRUD（key/name/type/api/ext/jar/extra），搜索、启停、标签。
- **配置方案**：站点编组 + 站点级覆写（overrides）、全局 spider 与字段、
  实时预览编译结果、发布导出 `data/configs/published/{slug}.json`。
- **导入向导**：粘贴/URL 拉取 TVBox 配置（明文或 Base64），解析候选站点，
  勾选导入，自动关联已有源文件。

## 目录

```
backend/app/
  main.py          入口（路由组装 + dist 托管）
  config.py        路径/上传限制
  database.py      SQLite (data/tvbox.db)
  models.py        Source/SourceVersion/Site/Config/ConfigSite
  schemas.py       Pydantic 模型
  routers/         sources / sites / configs / importer
  services/        source_parser（js/py/jar 解析）、source_store（存储/版本/回滚）
frontend/
  src/views/       SiteList / SourceList / SourceView / ConfigList / ConfigDetail / ImportWizard
data/
  sources/{js,py,jar}/   源文件库
  configs/published/     发布产物
```

## 端口

- 生产：8000（后端 + 静态托管）
- 开发：8000（后端）+ 9981（vite dev，代理）

## 字段参考

完整字段文档见 `../开发文档/FongMi-TV字段完全参考手册.md`。
