import uuid
from sqlalchemy import Column, String, DateTime, Date, Boolean, Numeric, Integer, Text, JSON, ForeignKey, Index, func
from sqlalchemy.types import Uuid
from .database import Base

# ==========================================
# 1. 用户账号表 (users)
# ==========================================
class User(Base):
    __tablename__ = "users"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True, comment="用户唯一 ID")
    username = Column(String(50), unique=True, index=True, nullable=False, comment="用户名")
    email = Column(String(255), unique=True, index=True, nullable=False, comment="邮箱")
    password_hash = Column(String(255), nullable=False, comment="加盐哈希后的密码")
    role = Column(String(20), default="user", comment="角色：user/admin")
    status = Column(String(20), default="active", comment="状态：active/disabled")
    nickname = Column(String(50), nullable=True, comment="用户昵称")
    avatar_url = Column(Text, nullable=True, comment="头像地址")
    bio = Column(Text, nullable=True, comment="个人简介")
    last_login_at = Column(DateTime, nullable=True, comment="最近登录时间")
    created_at = Column(DateTime, default=func.now(), nullable=False, comment="注册时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False, comment="资料更新时间")

# ==========================================
# 2. Prompt 主表 (prompts)
# ==========================================
class Prompt(Base):
    __tablename__ = "prompts"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True, comment="Prompt ID")
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=False, comment="创建者 ID")
    title = Column(String(200), nullable=False, comment="提示词标题")
    description = Column(Text, nullable=True, comment="提示词简要描述")
    system_prompt = Column(Text, nullable=True, comment="系统提示词")
    user_prompt = Column(Text, nullable=False, comment="用户提示词正文")
    variables = Column(JSON, nullable=True, default=list, comment="变量定义")
    tags = Column(JSON, nullable=True, default=list, comment="标签列表")
    visibility = Column(String(20), default="private", comment="private / public")
    current_version = Column(Integer, default=1, comment="当前版本号")
    created_at = Column(DateTime, default=func.now(), nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False, comment="最后一次修改时间")

# ==========================================
# 3. Prompt 版本记录表 (prompt_versions)
# ==========================================
class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True, comment="版本快照 ID")
    prompt_id = Column(Uuid, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False, comment="关联的 Prompt ID")
    version_number = Column(Integer, nullable=False, comment="版本号")
    title = Column(String(200), nullable=False, comment="该版本的标题")
    description = Column(Text, nullable=True, comment="该版本的简要描述快照")
    system_prompt = Column(Text, nullable=True, comment="该版本的系统提示词")
    user_prompt = Column(Text, nullable=False, comment="该版本的用户提示词正文")
    variables = Column(JSON, nullable=True, comment="该版本的变量快照")
    tags_snapshot = Column(JSON, nullable=True, default=list, comment="该版本的标签快照")
    note = Column(Text, nullable=True, comment="版本变更备注")
    created_at = Column(DateTime, default=func.now(), nullable=False, comment="版本创建时间")

# ==========================================
# 4. 用户 AI 配置表 (ai_api_keys)
# ==========================================
class AIApiKey(Base):
    __tablename__ = "ai_api_keys"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True, comment="配置 ID")
    user_id = Column(Uuid, ForeignKey("users.id"), unique=True, nullable=False, comment="所属用户")
    provider = Column(String(50), nullable=False, comment="AI 服务商")
    base_url = Column(Text, nullable=False, comment="API 地址")
    encrypted_api_key = Column(Text, nullable=False, comment="加密后的 API Key")
    key_mask = Column(String(50), nullable=False, comment="脱敏后的 Key")
    default_model = Column(String(100), nullable=False, comment="默认使用的模型")
    is_verified = Column(Boolean, default=False, nullable=False, comment="最近一次连通性校验是否成功")
    last_verified_at = Column(DateTime, nullable=True, comment="最近一次校验时间")
    status = Column(String(20), default="active", comment="active / disabled")
    created_at = Column(DateTime, default=func.now(), nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")

# ==========================================
# 5. 系统 AI 配置表 (system_ai_configs)
# ==========================================
class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    jti = Column(String(100), unique=True, index=True, nullable=False)
    token_type = Column(String(20), nullable=False)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, default=func.now(), nullable=False)


class SystemAIConfig(Base):
    __tablename__ = "system_ai_configs"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True, comment="系统配置 ID")
    provider = Column(String(50), nullable=False, comment="服务商名称")
    base_url = Column(Text, nullable=False, comment="系统默认 API 地址")
    key_mask = Column(String(50), nullable=False, comment="脱敏后的系统 Key")
    encrypted_api_key = Column(Text, nullable=False, comment="加密存储的系统 Key")
    default_model = Column(String(100), nullable=False, comment="系统默认模型")
    is_default = Column(Boolean, default=False, comment="是否为当前生效的默认配置")
    is_enabled = Column(Boolean, default=True, comment="是否启用")
    daily_guest_limit = Column(Integer, default=10, comment="游客单日调用次数上限")
    created_by = Column(Uuid, ForeignKey("users.id"), nullable=True, comment="创建该配置的管理员 ID")
    updated_by = Column(Uuid, ForeignKey("users.id"), nullable=True, comment="最近修改该配置的管理员 ID")
    created_at = Column(DateTime, default=func.now(), nullable=False, comment="记录创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")

# ==========================================
# 6. AI 调用日志表 (ai_call_records)
# ==========================================
class AICallRecord(Base):
    __tablename__ = "ai_call_records"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True, comment="调用记录 ID")
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=True, comment="调用用户（游客为 NULL）")
    guest_session_id = Column(String(100), nullable=True, comment="游客会话 ID")
    prompt_id = Column(Uuid, ForeignKey("prompts.id"), nullable=True, comment="关联的个人 Prompt")
    community_prompt_id = Column(Uuid, ForeignKey("community_prompts.id"), nullable=True, comment="关联的社区 Prompt")
    call_type = Column(String(20), nullable=False, comment="polish(润色) / test(测试)")
    api_key_source = Column(String(20), nullable=False, comment="user / system_default")
    provider = Column(String(50), nullable=False, comment="AI 服务商")
    model = Column(String(100), nullable=False, comment="调用的模型名称")
    input_summary = Column(Text, nullable=True, comment="输入摘要")
    rendered_system_prompt = Column(Text, nullable=True, comment="渲染后的系统提示词")
    rendered_user_prompt = Column(Text, nullable=True, comment="渲染后的用户提示词")
    output_text = Column(Text, nullable=True, comment="AI 输出的完整内容")
    suggestions = Column(JSON, nullable=True, comment="润色建议列表")
    variables = Column(JSON, nullable=True, comment="测试时使用的变量值快照")
    temperature = Column(Numeric(3, 2), nullable=True, comment="模型温度参数")
    max_tokens = Column(Integer, nullable=True, comment="设定的最大 Token 数")
    prompt_tokens = Column(Integer, nullable=True, comment="输入消耗 Token 数")
    completion_tokens = Column(Integer, nullable=True, comment="输出生成 Token 数")
    total_tokens = Column(Integer, nullable=True, comment="总 Token 消耗")
    latency_ms = Column(Integer, nullable=True, comment="响应耗时（毫秒）")
    status = Column(String(20), default="success", comment="success / failed")
    error_code = Column(String(50), nullable=True, comment="错误码")
    error_message = Column(Text, nullable=True, comment="错误详情")
    ip_address = Column(String(100), nullable=True, comment="调用者 IP")
    user_agent = Column(Text, nullable=True, comment="浏览器或客户端信息")
    created_at = Column(DateTime, default=func.now(), nullable=False, comment="调用时间")

# ==========================================
# 7. 游客调用额度表 (guest_ai_quotas)
# ==========================================
class GuestAIQuota(Base):
    __tablename__ = "guest_ai_quotas"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True, comment="记录 ID")
    guest_session_id = Column(String(100), nullable=False, index=True, comment="游客会话 ID")
    ip_address = Column(String(100), nullable=True, comment="游客 IP")
    usage_date = Column(Date, nullable=False, comment="统计日期")
    polish_count = Column(Integer, default=0, comment="当日 AI 润色调用次数")
    test_count = Column(Integer, default=0, comment="当日 AI 测试调用次数")
    total_count = Column(Integer, default=0, comment="当日总调用次数")
    daily_limit = Column(Integer, default=10, comment="每日上限")
    last_called_at = Column(DateTime, nullable=True, comment="最近调用时间")
    created_at = Column(DateTime, default=func.now(), nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")

# ==========================================
# 8. 社区分享表 (community_prompts)
# ==========================================
class CommunityPrompt(Base):
    __tablename__ = "community_prompts"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True, comment="分享 ID")
    prompt_id = Column(Uuid, ForeignKey("prompts.id"), nullable=True, comment="原始提示词 ID")
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=True, comment="分享者 ID")
    title_snapshot = Column(String(200), nullable=False, comment="分享时的标题快照")
    system_prompt_snapshot = Column(Text, nullable=True, comment="分享时的系统提示词快照")
    user_prompt_snapshot = Column(Text, nullable=False, comment="分享时的用户提示词快照")
    tags_snapshot = Column(JSON, nullable=True, comment="分享时的标签快照")
    description = Column(Text, nullable=True, comment="用户填写的分享描述信息")
    usage_guide = Column(Text, nullable=True, comment="Prompt 使用说明")
    status = Column(String(20), default="pending", comment="pending/approved/rejected/removed")
    reviewed_by = Column(Uuid, ForeignKey("users.id"), nullable=True, comment="审核人")
    reviewed_at = Column(DateTime, nullable=True, comment="审核时间")
    view_count = Column(Integer, default=0, comment="浏览次数")
    favorite_count = Column(Integer, default=0, comment="收藏总数")
    audit_note = Column(Text, nullable=True, comment="审核意见")
    created_at = Column(DateTime, default=func.now(), nullable=False, comment="分享提交时间")

# ==========================================
# 9. 用户收藏表 (user_favorites)
# ==========================================
class UserFavorite(Base):
    __tablename__ = "user_favorites"
    __table_args__ = (
        Index(
            "uq_user_favorites_user_community_prompt",
            "user_id",
            "community_prompt_id",
            unique=True,
        ),
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True, comment="收藏记录 ID")
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="收藏者用户 ID")
    community_prompt_id = Column(Uuid, ForeignKey("community_prompts.id", ondelete="CASCADE"), nullable=False, comment="收藏的社区作品 ID")
    created_at = Column(DateTime, default=func.now(), nullable=False, comment="收藏时间")

# ==========================================
# 10. 社区举报表 (community_reports)
# ==========================================
class CommunityReport(Base):
    __tablename__ = "community_reports"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True, comment="举报 ID")
    reporter_id = Column(Uuid, ForeignKey("users.id"), nullable=True, comment="举报人（匿名可为 NULL）")
    community_prompt_id = Column(Uuid, ForeignKey("community_prompts.id"), nullable=False, comment="被举报的社区作品")
    reason = Column(String(200), nullable=False, comment="举报原因")
    description = Column(Text, nullable=True, comment="补充说明")
    status = Column(String(20), default="pending", comment="pending / processed / rejected")
    handled_by = Column(Uuid, ForeignKey("users.id"), nullable=True, comment="处理的管理员")
    handled_at = Column(DateTime, nullable=True, comment="处理时间")
    handle_result = Column(Text, nullable=True, comment="处理结果说明")
    created_at = Column(DateTime, default=func.now(), nullable=False, comment="举报时间")

# ==========================================
# 11. 系统审计日志表 (audit_logs)
# ==========================================
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True, comment="日志 ID")
    actor_id = Column(Uuid, ForeignKey("users.id"), nullable=True, comment="操作者ID")
    actor_role = Column(String(20), nullable=True, comment="操作人角色")
    action = Column(String(100), nullable=False, comment="动作")
    target_type = Column(String(50), nullable=False, comment="目标类型")
    target_id = Column(Uuid, nullable=False, comment="目标 ID")
    detail = Column(JSON, nullable=True, comment="详细信息")
    ip_address = Column(String(100), nullable=True, comment="操作者 IP 地址")
    user_agent = Column(Text, nullable=True, comment="浏览器或客户端信息")
    created_at = Column(DateTime, default=func.now(), nullable=False, comment="记录时间")
