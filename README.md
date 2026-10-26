# 全域内容运营平台

基于 Python、FastAPI、LangGraph 与 SQLite 的多渠道内容运营应用。一个 LangGraph 状态图串联数据分析、选题、研究、写作、审核、排版与人工反馈，模型能力封装为版本化 Skills；发布中心把小红书、视频号、抖音、快手与公众号五个渠道的内容记录、审核与效果数据统一在一个工作台。

本仓库是用于作品展示的脱敏源码快照，包含虚构账号示例，不含真实账号画像、运营指标、文章草稿、数据库、运行日志、截图或 API 密钥。

## 主要功能

- 指定主题写作、数据驱动写作与周度计划三种任务模式，AI 写稿走研究-写作-审核流水线。
- 视频脚本生成：主题一键扩写成结构化口播脚本（分镜/字幕/CTA），脚本可直接转公众号文章或存为渠道草稿。
- 发布中心：全渠道发布记录时间线、待审核/草稿/失败筛选、发布成功率与环比概览、待处理事项与本周发布计划。
- 渠道管理：五渠道账号信息、近 7 天表现、单渠道详情页；平台对比与内容表现排名。
- CSV/XLSX 指标导入、数据质量检查与 7/30/90 天分析；人工改稿记录、发布信息登记与效果回流。
- JSON Schema / Pydantic 输出校验、Token 预算、失败重跑、SQLite 检查点与节点运行记录。
- 操作日志：发布登记、脚本转化、渠道调整等关键操作全部落库可回放。

## 本地运行

需要 Python 3.12 或 3.13。先进入仓库目录，再执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

在仅保存在本机的 `.env` 中填写所需配置：

- `APP_SECRET_KEY`：替换为随机字符串，例如用 `python -c "import secrets; print(secrets.token_urlsafe(32))"` 生成。
- `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL`：配置自己有访问权限的密钥和模型；脚本生成与文章流水线依赖写作模型。
- `OPERATOR_NAME` / `TEAM_NAME`：控制台右上角显示的运营者与团队名。
- 长文可设置 `TEXT_MODEL_STREAMING_ENABLED=true` 持续接收输出，避免整篇返回前触发读超时。
- `WECHAT_ACCOUNT_NAME`：公众号渠道显示的账号名；账号定位位于 `app/container.py` 的 `account_profile`。
- 仅在需要草稿接口时配置微信 App ID / AppSecret，并显式开启 `WECHAT_DRAFT_ENABLED`。
- 搜索、图片生成与 MCP 在公开示例中默认关闭。使用时自行配置供应商及服务，模型调用可能计费。
- `SEED_DEMO_DATA=true` 可生成一套标记为 demo 的多渠道示例数据用于演示（默认关闭：未接入的渠道粉丝、浏览等数据一律留空占位，接入数据源或在发布中心手动登记后自动统计）。

```powershell
python -m app.cli serve --host 127.0.0.1 --port 8000 --no-reload
```

打开 http://127.0.0.1:8000 。也可先执行 `python -m app.cli --help` 查看 CLI。数据库与运行产物会在本地自动创建，已由 `.gitignore` 排除。

Windows 下也可以直接双击 `启动.bat`（优先使用仓库内 `.venv`）：服务会以隐藏后台进程运行，就绪后自动打开浏览器；日志写入 `runtime/uvicorn.out.log` 与 `runtime/uvicorn.err.log`。需要停止服务时，双击 `停止服务.bat`。后台模式使用 `--no-reload`，改动代码后请先停止再重新启动。

## 内容边界

- 各渠道发布记录用于统一登记、审核与复盘；正式发布始终由人工在各平台后台完成。
- 系统不提供公众号正式发布或群发接口；草稿上传必须显式开启，最多自动修订两轮。

## 农业知识库连接

默认账号定位可按需切换。若启用知识库（`KNOWLEDGE_BASE_ENABLED=true` 等），研究节点优先检索知识库原文并保存来源快照，视觉节点优先复用图库素材。配置细节见 `.env.example` 注释。

## 验证与 Docker

```powershell
python -m pytest -q
docker compose up --build
```

测试使用临时数据库及模拟依赖。运行前不要配置真实凭据，勿将运行产物加入版本控制。Docker 需要先准备 `.env`，对宿主机仅绑定 `127.0.0.1:8000`；首次运行可先创建 `outputs` 与 `runtime` 目录并确保容器用户 UID 10001 可写。

## 安全和人工边界

应用默认用于本地演示；公开源码不等于可直接暴露生产服务。对外部署需要另行配置访问认证、HTTPS、请求限制、备份与网络出口规则。网页抓取的应用层检查不能替代出口防火墙。

请勿提交 `.env`、`mcp_servers.json`、`data/` 中的真实资料、数据库、私密文章、运行产物、凭据或访问令牌。公开前请对待提交文件再次执行敏感信息检查。

第三方 Human Writing Skill 的来源与许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
