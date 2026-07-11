# PromptCafe

PromptCafe 是一个基于 FastAPI、SQLite、SQLAlchemy 和 Pydantic 的 Prompt 管理与分享系统。项目提供用户认证、个人 Prompt 管理、Prompt 版本管理、社区分享、收藏举报、AI 润色/测试以及管理员审核等接口，并可通过内置 Swagger UI 进行接口调试。

本仓库同时包含后端源码、SQLite 测试数据库和已构建的前端静态文件。启动后，FastAPI 会提供后端 API，并在根路径挂载 `dist/` 中的前端页面。

## 环境准备

建议使用 Python 3.13，并在项目根目录创建虚拟环境。

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r app\requirements.txt
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r app/requirements.txt
```

## 启动项目

请在项目根目录运行，也就是包含 `app/` 和 `dist/` 的目录。

```bash
python -m uvicorn app.main:app --reload
```

默认服务地址：

- 前端页面：`http://127.0.0.1:8000/`
- Swagger API 文档：`http://127.0.0.1:8000/docs`
- ReDoc 文档：`http://127.0.0.1:8000/redoc`

如果端口被占用，可以指定其他端口：

```bash
python -m uvicorn app.main:app --reload --port 8001
```

## 测试数据库说明

项目使用 SQLite，数据库文件位于：

```text
app/db/prompt_app.db
```

本项目计划随仓库提交该数据库，方便评审人员直接使用已有测试数据。当前代码中的 SQLAlchemy 模型与该数据库的表结构保持一致，正常从项目根目录启动时，不需要额外创建数据库。

请注意：

- 不要从 `app/` 目录内部启动服务，否则相对数据库路径可能不符合预期。
- 数据库中已经包含测试用户、Prompt、社区分享和 AI 配置等数据。
- 启动时系统会检查是否存在管理员账号；如果不存在，会创建默认管理员。
- 默认管理员仅用于本地测试：`superadmin / superadmin123`。
- 测试账号可用：`aitester001 / 12345678`。
- 若用于正式部署，请替换测试数据库、修改默认管理员逻辑，并设置独立的 `PROMPT_CAFE_JWT_SECRET`。

可选环境变量：

```powershell
$env:PROMPT_CAFE_JWT_SECRET="your-local-secret"
python -m uvicorn app.main:app --reload
```

macOS / Linux:

```bash
export PROMPT_CAFE_JWT_SECRET="your-local-secret"
python -m uvicorn app.main:app --reload
```

## 常用接口入口

- `POST /api/auth/register`：注册用户
- `POST /api/auth/login`：登录并获取 Token
- `GET /api/auth/me`：查看当前登录用户
- `GET /api/prompts`：查看个人 Prompt 列表
- `POST /api/prompts`：创建 Prompt
- `GET /api/community/prompts`：查看社区 Prompt
- `POST /api/community/shares`：分享 Prompt 到社区
- `GET /api/ai/models`：查看支持的 AI 模型
- `PUT /api/ai/api-key`：保存当前用户的 AI API Key
- `GET /api/admin/users`：管理员查看用户列表

需要登录的接口请在 Swagger UI 中点击 `Authorize`，填入：

```text
Bearer <accessToken>
```

其中 `<accessToken>` 来自登录接口返回的 `data.accessToken`。

## 推荐测试流程

建议跨组测试人员按“先核心流程、再扩展流程”的顺序测试。若时间有限，优先执行 P0/P1 流程；若 P0 流程失败，建议先记录问题并暂停后续大范围测试。

### Step 1：启动服务并确认测试准入

1. 按“环境准备”和“启动项目”完成依赖安装与服务启动。
2. 浏览器打开 `http://127.0.0.1:8000/`，确认前端页面可访问。
3. 打开 `http://127.0.0.1:8000/docs`，确认 Swagger UI 可访问。
4. 确认数据库文件 `app/db/prompt_app.db` 存在，且服务启动无导入错误。

测试准入参考：

| 准入项 | 通过标准 |
| --- | --- |
| 系统可启动 | `python -m uvicorn app.main:app --reload` 正常运行 |
| 前端可访问 | 浏览器可打开首页，静态资源正常加载 |
| 接口可访问 | Swagger UI 可打开，接口列表可见 |
| 数据库可用 | SQLite 文件可读写，已有测试数据可查询 |
| 测试账号可用 | 可注册普通用户，默认管理员可登录 |

### Step 2：注册、登录与个人资料

1. 注册一个普通用户，例如 `qa_test_自己的编号`，避免和其他测试人员重复。
2. 使用注册账号登录，确认能获取 `accessToken`。
3. 在 Swagger UI 的 `Authorize` 中填入 `Bearer <accessToken>`。
4. 调用或操作个人资料页面，测试查看、修改昵称、头像、简介等功能。
5. 尝试错误账号、错误密码、重复用户名、非法邮箱等异常输入，确认系统有明确提示。

### Step 3：Prompt 管理核心流程

建议至少完整测试一条 Prompt 从创建到删除的生命周期：

1. 创建 Prompt，填写标题、简介、系统提示词、用户提示词、变量、标签和可见性。
2. 查看 Prompt 列表，测试分页、搜索、排序和标签筛选。
3. 查看 Prompt 详情，确认字段与创建时一致。
4. 修改 Prompt 内容，确认保存成功。
5. 使用变量渲染功能，例如在提示词中写入 `{{topic}}`，提交变量值后确认渲染结果正确。
6. 复制 Prompt，确认副本为当前用户所有，且默认可作为独立 Prompt 使用。
7. 删除 Prompt，确认列表中不再显示该条记录。

重点观察：

- 必填字段为空时是否被拦截。
- 超长标题、空标签、重复标签是否能被正确处理。
- 普通用户是否只能修改和删除自己的 Prompt。

### Step 4：Prompt 版本控制

版本控制依赖已有 Prompt，建议在 Step 3 创建的 Prompt 基础上继续测试：

1. 修改 Prompt 内容，确认版本号递增。
2. 查看历史版本列表，确认版本快照字段完整。
3. 手动创建版本快照，确认不会出现重复版本号。
4. 对比两个历史版本，确认差异内容合理。
5. 回滚到某个历史版本，确认主 Prompt 内容更新，并生成新的当前版本。

重点观察：

- `currentVersion` 是否与最新版本一致。
- 不存在的版本 ID 是否返回明确错误。
- 普通用户是否无法访问或回滚他人的私有 Prompt 版本。

### Step 5：社区分享、收藏、举报与 Fork

1. 将自己的 Prompt 分享到社区，填写分享标题、说明和使用指南。
2. 使用管理员账号审核该分享，通过后回到社区列表查看。
3. 普通用户浏览社区 Prompt，查看详情。
4. 收藏和取消收藏社区 Prompt，确认收藏数与“我的收藏”列表变化。
5. 对社区 Prompt 提交举报，确认重复举报会被拦截。
6. Fork 社区 Prompt，确认会在个人 Prompt 中生成副本。

重点观察：

- 未审核通过的社区分享不应出现在公开列表。
- 游客可浏览公开社区内容，但涉及收藏、举报、Fork 等操作应要求登录。
- 撤回、驳回、下架等状态变化后，前台展示应同步变化。

### Step 6：管理员功能

使用默认管理员 `superadmin / superadmin123` 登录后测试：

1. 查看待审核社区分享列表。
2. 对分享执行通过、驳回、下架操作。
3. 查看举报列表并处理举报。
4. 查看用户列表、用户详情，测试禁用和恢复用户。
5. 查看用户 Prompt 列表和详情，测试管理员侧 Prompt 管理能力。
6. 查看审计日志，确认关键管理操作有记录。

重点观察：

- 普通用户访问 `/api/admin/*` 应被拒绝。
- 管理员不能误操作导致自己账号不可用。
- 审核、举报处理、用户状态变更后，相关页面和数据库状态应一致。

### Step 7：AI 功能

AI 功能依赖有效 API Key 和外部服务，若网络或 Key 不可用，可重点测试失败处理和配置流程。

1. 查看 `/api/ai/models`，确认模型列表可返回。
2. 普通用户保存自己的 AI API Key，确认只显示脱敏 Key。
3. 管理员配置系统默认 AI Key，供游客或未配置私钥的场景使用。
4. 使用 Prompt 润色功能，观察优化结果和建议。
5. 使用 Prompt 测试功能，填写变量并运行，确认渲染 Prompt、模型输出、耗时和 Token 用量展示合理。
6. 查看 AI 测试记录列表和详情。
7. 尝试无效 Key、网络不可用或游客额度耗尽等异常场景，确认系统返回可理解的错误提示。

注意：

- AI 请求可能耗时较长，等待期间不要重复快速提交。
- 若 AI 服务失败，优先确认网络、API Key、服务商地址和模型名是否正确。
- 不建议把 AI 润色/测试接口纳入高并发压测。

### Step 8：安全、兼容性和稳定性抽测

建议至少补充以下非功能测试：

| 测试类别 | 推荐测试内容 |
| --- | --- |
| 权限安全 | 未登录访问、普通用户越权访问、管理员接口访问控制、禁用用户登录 |
| 数据安全 | API Key 是否仅脱敏显示，密码是否不明文返回，用户间数据是否隔离 |
| 浏览器兼容 | 使用 Chrome 和 Edge 分别打开登录页、列表页、表单页和详情页 |
| 易用性 | 错误输入、空结果、删除确认、保存成功提示是否清晰 |
| 稳定性 | 重复点击、重复提交、快速分页、连续使用 30 分钟是否异常 |
| 性能 | 非 AI 接口平均响应建议不超过 3 秒，P95 响应建议不超过 3 秒 |

如果要做轻量并发测试，建议只覆盖登录、Prompt 列表、社区列表、个人资料等非 AI 接口。SQLite 适合本地测试，但不建议用它做大规模并发写入压测。

## 测试通过参考标准

本项目测试文档采用 P0、P1、P2、P3 用例优先级和 S0、S1、S2、S3 缺陷严重度。跨组评审可参考以下简化标准：

| 项目 | 建议标准 |
| --- | --- |
| P0 核心流程 | 注册登录、Prompt CRUD、权限校验、管理员登录必须通过 |
| P1 主要流程 | 版本控制、社区分享、管理员审核、AI 配置等通过率建议达到 95% 以上 |
| 严重缺陷 | 不应遗留 S0/S1 缺陷 |
| 回归验证 | 若发现并修复缺陷，应复测原失败步骤和相关模块 |
| 测试记录 | 建议记录测试账号、测试数据、操作步骤、实际结果和截图 |

## 已知限制和测试提示

- 本项目使用 SQLite 作为本地测试数据库，适合课程项目评审，不适合生产级高并发写入。
- 默认管理员用于本地测试，正式部署前应修改默认账号逻辑。
- AI 功能依赖外部服务商，失败时不一定是系统缺陷，应先排查 Key、网络和模型配置。
- 数据库中已有测试数据，列表数量、排序结果可能会随测试人员操作变化。
- 如果测试人员共用同一数据库，建议注册带有个人编号的账号，例如 `qa_test_01`。
- 删除、下架、禁用等操作会改变共享测试数据，执行前建议截图或记录原始状态。

## 问题反馈建议

发现问题时，建议按以下格式记录，方便复现和定位：

```text
问题标题：
测试账号：
测试环境：浏览器 / 操作系统 / Python 版本
前置条件：
复现步骤：
期望结果：
实际结果：
接口状态码：
接口响应内容：
截图或日志：
严重度建议：S0 / S1 / S2 / S3
```

特别有用的信息：

- 你点击了哪个页面或调用了哪个接口。
- 输入了哪些测试数据。
- 浏览器开发者工具 Network 中失败请求的状态码和 Response。
- 后端终端中是否出现异常堆栈。
- 该问题是否可以稳定复现。

## 项目结构

```text
prompt-cafe1/
├── app/
│   ├── main.py                  # FastAPI 应用入口、路由注册、前端静态文件挂载
│   ├── requirements.txt          # Python 依赖列表
│   ├── api/
│   │   ├── dependencies.py       # 数据库 Session、认证、Token、权限依赖
│   │   └── routes/
│   │       ├── auth.py           # 注册、登录、刷新 Token、退出登录
│   │       ├── user.py           # 当前用户资料
│   │       ├── prompt.py         # Prompt 创建、查询、更新、删除、复制、渲染
│   │       ├── prompt_version.py # Prompt 历史版本、差异、回滚
│   │       ├── community.py      # 社区分享、收藏、举报、Fork
│   │       ├── ai.py             # AI Key、模型列表、Prompt 润色和测试
│   │       └── admin.py          # 管理员审核、用户管理、审计日志
│   ├── core/
│   │   └── bootstrap.py          # 启动初始化逻辑
│   ├── db/
│   │   ├── database.py           # SQLite 连接与 Session 配置
│   │   ├── models.py             # SQLAlchemy 表模型
│   │   └── prompt_app.db         # SQLite 测试数据库
│   └── schemas/                  # Pydantic 请求与响应模型
├── dist/                         # 前端构建产物，由 FastAPI 静态挂载
├── README.md                     # 项目说明
└── .gitgonre                     # 当前仓库中的忽略配置文件，建议后续更名为 .gitignore
```

## 依赖说明

运行项目所需核心依赖位于 `app/requirements.txt`：

- `fastapi`：Web 框架与接口文档
- `uvicorn`：ASGI 服务
- `sqlalchemy`：ORM 与数据库访问
- `pydantic`：请求和响应数据校验
- `passlib[bcrypt]`：密码哈希相关依赖，当前代码使用自定义 PBKDF2 哈希逻辑，保留该依赖不影响运行

如果后续要编写基于 FastAPI `TestClient` 的自动化测试，建议额外安装并加入开发依赖：

```bash
python -m pip install httpx pytest
```

## 快速排查

- `ModuleNotFoundError: No module named 'fastapi'`：确认已激活虚拟环境，并执行了 `python -m pip install -r app/requirements.txt`。
- 找不到数据库或数据为空：确认启动命令是在项目根目录执行。
- 访问 `/` 没有前端页面：确认 `dist/index.html` 存在。
- Swagger 中提示未认证：先调用登录接口，再在 `Authorize` 中填入 `Bearer <accessToken>`。
