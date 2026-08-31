# 微信公众号数据驱动运营 Agent

基于 Python、FastAPI、LangGraph 与 SQLite 的公众号运营应用。一个 LangGraph 状态图串联数据分析、选题、研究、写作、审核、排版与人工反馈，模型能力封装为版本化 Skills。

本仓库是用于作品展示的脱敏源码快照，包含虚构账号示例，不含真实账号画像、运营指标、文章草稿、数据库、运行日志、截图或 API 密钥。

## 主要功能

- 指定主题写作、数据驱动写作与周度计划三种任务模式。
- CSV/XLSX 指标导入、数据质量检查与 7/30/90 天分析。
- JSON Schema / Pydantic 输出校验、Token 预算、失败重跑、SQLite 检查点与节点运行记录。
- 研究来源证据快照、网页抓取安全校验、微信 HTML 排版及可选素材/草稿接口。
- MCP 工具发现与调用；人工改稿记录、发布信息登记与效果回流。

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
- `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL`：配置自己有访问权限的密钥和模型；示例模型名不保证所有账户均可用。
- `WECHAT_ACCOUNT_NAME`：替换虚构账号名称；选题定位目前位于 `app/container.py` 的 `account_profile`。
- 仅在需要草稿接口时配置微信 App ID / AppSecret，并显式开启 `WECHAT_DRAFT_ENABLED`。
- 搜索、图片生成与 MCP 在公开示例中默认关闭。使用时自行配置供应商及服务，模型调用可能计费。

```powershell
python -m app.cli serve --host 127.0.0.1 --port 8000 --no-reload
```

打开 http://127.0.0.1:8000 。也可先执行 `python -m app.cli --help` 查看 CLI。数据库与运行产物会在本地自动创建，已由 `.gitignore` 排除。

若使用 MCP，将 `mcp_servers.example.json` 复制为 `mcp_servers.json`，配置可信服务器后再将该服务器的 `enabled` 改为 `true`。示例域名不可直接使用。

## 验证与 Docker

```powershell
python -m pytest -q
docker compose up --build
```

测试使用临时数据库及模拟依赖。运行前不要配置真实凭据，勿将运行产物加入版本控制。Docker 需要先准备 `.env`，对宿主机仅绑定 `127.0.0.1:8000`；首次运行可先创建 `outputs` 与 `runtime` 目录并确保容器用户 UID 10001 可写。

## 安全和人工边界

应用默认用于本地演示；公开源码不等于可直接暴露生产服务。对外部署需要另行配置访问认证、HTTPS、请求限制、备份与网络出口规则。网页抓取的应用层检查不能替代出口防火墙。

最多自动修订两轮，未通过审核的内容交由人工处理。系统不提供公众号正式发布或群发接口；草稿上传必须显式开启，正式发布始终由人在微信后台完成。

请勿提交 `.env`、`mcp_servers.json`、`data/` 中的真实资料、数据库、私密文章、运行产物、凭据或访问令牌。公开前请对待提交文件再次执行敏感信息检查。

第三方 Human Writing Skill 的来源与许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
