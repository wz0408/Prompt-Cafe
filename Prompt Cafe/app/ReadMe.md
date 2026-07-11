这是一个基于 **FastAPI + SQLite + SQLAlchemy + Pydantic** 的现代化 Python 后端框架 Demo。它完全满足你的需求：无需安装额外数据库环境、自带 Swagger UI 接口文档，并且项目结构清晰，非常适合后续扩展。

为了保持结构清晰，我将代码组织成了标准的工程化目录结构。

---

### 一、 项目目录结构

请在你的电脑上创建一个文件夹（例如 `prompt_backend`），并按照以下结构创建文件：

```text
prompt_backend/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 主程序入口
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py         # 数据库连接配置
│   │   └── models.py           # SQLAlchemy 数据库表模型
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── user.py             # Pydantic 接口数据验证模型 (请求/响应)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── dependencies.py     # 依赖注入 (如获取数据库Session)
│   │   └── routes/
│   │       ├── __init__.py
│   │       └── user.py         # 用户管理相关的接口路由
├── requirements.txt            # 依赖包列表
└── README.md                   # 项目说明文档

```

### 三、 介绍文档 (保存为 `README.md`)

# Prompt Hub Backend (FastAPI Demo)

这是一个基于 FastAPI + SQLite 驱动的后端项目接口服务。内置完整的 Swagger UI 文档管理。

## 📦 一、 环境安装与运行

### 1. 准备环境
确保你的电脑上安装了 Python 3.13  --环境能用
建议使用虚拟环境：


### 2. 安装依赖

```bash
pip install -r requirements.txt

```

### 3. 启动服务

在项目根目录下（包含 `app` 文件夹的同级目录）运行：

```bash
python -m uvicorn app.main:app --reload

```

### 4. 访问接口文档

打开浏览器访问：[http://127.0.0.1:8000/docs](https://www.google.com/url?sa=E&source=gmail&q=http://127.0.0.1:8000/docs)
你将看到自动生成的 Swagger UI，在这里可以直接测试接口。

---

## 🏗️ 二、 项目结构说明

* `app/main.py`：项目的核心入口，负责初始化 FastAPI 实例、挂载路由、触发数据库建表。
* `app/db/database.py`：负责配置 SQLite 数据库连接及 Session。
* `app/db/models.py`：**数据库的物理表结构**。所有的表（如 `users`, `prompts` 等）都定义在这里，使用 SQLAlchemy 的 ORM 语法。
* `app/schemas/`：**接口的数据结构验证**。使用 Pydantic。定义了前端传过来的 JSON 长什么样，以及后端返回的 JSON 长什么样。分离 schema 和 model 可以极大地保证数据安全和接口清晰。
* `app/api/dependencies.py`：存放公共的依赖函数，比如从数据库连接池获取 session 的方法。
pi/routes/`：**具体的接口业务逻辑**。按业务模块划分文件（如 `user.py`, `prompt.py`）。
* `app/a
---

## 🚀 三、 引导：如何增加一个新的接口 (以“获取 Prompt 列表”为例)

假设我们要新增一个 `GET /api/prompts` 接口，请按照以下 **标准4步工作流** 进行：

### 第一步：在 `models.py` 增加数据库表

打开 `app/db/models.py`，根据设计文档添加表结构：

```python
class Prompt(Base):
    __tablename__ = "prompts"
    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    title = Column(String(200), nullable=False)
    user_prompt = Column(Text, nullable=False)
    # ... 其他字段

```

### 第二步：在 `schemas` 定义请求和响应结构

创建文件 `app/schemas/prompt.py`：

```python
from pydantic import BaseModel

# 响应的数据结构
class PromptResponse(BaseModel):
    id: str
    title: str
    user_prompt: str

```

### 第三步：在 `routes` 编写接口逻辑

创建文件 `app/api/routes/prompt.py`：

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db import models
from app.schemas.prompt import PromptResponse
from app.api.dependencies import get_db

router = APIRouter()

@router.get("", response_model=list[PromptResponse])
def get_prompts(db: Session = Depends(get_db)):
    prompts = db.query(models.Prompt).all()
    return prompts

```

### 第四步：在 `main.py` 中注册新路由

打开 `app/main.py`，注册刚刚写好的模块：

```python
from app.api.routes import user, prompt # 引入新的 prompt 模块

# ... 其他代码 ...

app.include_router(user.router, prefix="/api/users", tags=["用户管理"])
# 注册 Prompt 路由，它将自动出现在 Swagger 文档的 "Prompt 管理" 分组下
app.include_router(prompt.router, prefix="/api/prompts", tags=["Prompt 管理"])

```

保存后，FastAPI 会自动热重载，刷新浏览器 `http://127.0.0.1:8000/docs` 即可看到新接口！

```

### 总结
这套框架完全做到了开箱即用。你只需要按照指示安装依赖并运行 `uvicorn app.main:app --reload`，系统就会在根目录自动生成 `prompt_app.db`（SQLite数据库文件），你可以直接在 Swagger UI 里输入数据进行注册测试，并且会在本地数据库中看到真实插入的加密数据。后续你可以根据 Markdown 中的【第三部分】逐步把其他 10 张表和接口补充进去。

```