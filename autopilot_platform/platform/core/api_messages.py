"""面向用户的 API 文案（后端统一；前端展示 message）。

按业务域分段；抛错处引用本模块常量，勿手写散落中文/英文。
"""

from __future__ import annotations

# ---- 登录 / 鉴权 ----
LOGIN_INVALID_CREDENTIALS = "用户名或密码错误，请重试。"
LOGIN_RATE_LIMITED = "登录尝试过于频繁，请 {seconds} 秒后再试。"
AUTH_INVALID_TOKEN = "登录已失效，请重新登录。"
AUTH_USER_DISABLED = "账号不可用或已被禁用。"
AUTH_REQUIRED = "请先登录，或提供有效的 Runner Token。"
AUTH_ADMIN_REQUIRED = "需要管理员权限。"
AUTH_ORG_CONTEXT_REQUIRED = "请先选择组织（请求头 X-Org-Id），再由组织管理员执行此操作。"
AUTH_ORG_USER_SCOPE = "只能管理当前组织内的成员。"
AUTH_ORG_NO_PLATFORM_ROLE = "组织管理员不能修改平台角色。"
AUTH_OPERATOR_NO_ADMIN = "操作员不能分配管理员角色。"
AUTH_RUNNER_IMPERSONATE = "Runner Token 不能冒充其它 Runner。"
AUTH_RUNNER_SCOPE_DENIED = "Runner Token 无权访问该项目作用域的任务。"
AUTH_RUNNER_TOKEN_REQUIRED = "此接口仅接受 Runner Token。"
AUTH_NOT_USER_SESSION = "当前会话不是用户登录，无法访问该接口。"
AUTH_USER_LOGIN_REQUIRED = "请使用用户账号登录。"
AUTH_USER_NOT_FOUND = "用户不存在。"
AUTH_ROLE_ADMIN_OR_OPERATOR = "角色必须是 admin 或 operator。"
USER_CREATE_DUTY_INVALID = "这个人来干什么必须是：普通用户、系统管理员、加入组织、管组织、加入项目、管项目或只能看。"
USER_CREATE_ORG_REQUIRED = "请先选择组织，再创建需要加入组织或项目的账号。"
USER_CREATE_PROJECT_REQUIRED = "请先选择项目，再创建要进项目的账号。"
AUTH_CANNOT_DELETE_SELF = "不能删除当前登录账号。"
AUTH_USERNAME_EXISTS = "用户名已存在：{username}。"
AUTH_REFRESH_INVALID = "刷新令牌无效。"
AUTH_REFRESH_EXPIRED = "刷新令牌已过期，请重新登录。"
AUTH_REFRESH_REVOKED = "刷新令牌已失效，请重新登录。"
AUTH_OIDC_CODE_STATE_REQUIRED = "缺少 OIDC code 或 state 参数。"
AUTH_SAML_RESPONSE_REQUIRED = "缺少 SAMLResponse。"
AUTH_OIDC_DISABLED = "未启用 OIDC 登录（请设置 MC_OIDC_ENABLED=1）。"
AUTH_OIDC_CONFIG_REQUIRED = "请配置 MC_OIDC_ISSUER / CLIENT_ID / CLIENT_SECRET。"
AUTH_OIDC_INVALID_STATE = "OIDC 登录状态无效，请重试。"
AUTH_OIDC_STATE_EXPIRED = "OIDC 登录已过期，请重新发起。"
AUTH_OIDC_USER_NOT_PROVISIONED = "该 SSO 用户尚未开通，请联系管理员或开启自动建号。"
AUTH_SAML_DISABLED = "未启用 SAML 登录（请设置 MC_SAML_ENABLED=1）。"
AUTH_SAML_CONFIG_REQUIRED = "请配置 MC_SAML_IDP_SSO_URL。"
AUTH_SAML_USER_NOT_PROVISIONED = "该 SAML 用户尚未开通，请联系管理员或开启自动建号。"
AUTH_SSO_FAILED = "单点登录失败，请稍后重试或联系管理员。"
AUTH_HANDOFF_INVALID = "打开管理台的交接码无效或已过期，请从 IDE 重新打开。"

# ---- 任务 Jobs ----
JOB_NOT_FOUND = "任务不存在。"
JOB_CANCELLED = "任务已取消。"
JOB_INVALID_ID = "无效的任务 ID。"
JOB_INVALID_RESULT_STATUS = "结果状态必须是 succeeded 或 failed。"
JOB_RUNNER_TOKEN_CANNOT_CREATE = "Runner Token 不能创建任务，请使用用户登录。"
JOB_RUNNER_OFFLINE = "Runner 离线或未注册。"
JOB_NOT_CLAIMED_BY_RUNNER = "任务未被当前 Runner 领取。"
JOB_NOT_OWNED_BY_RUNNER = "任务不属于当前 Runner。"
JOB_RUNNER_ID_REQUIRED_REPORT = "上传报告需要指定 runner_id。"
JOB_STREAM_TOKEN_SCOPED = "日志流 Token 与当前任务不匹配。"
DEVICE_LOG_STREAM_TOKEN_SCOPED = "日志流 Token 与当前远控会话不匹配。"
JOB_LOG_NOT_FOUND = "任务日志不存在。"
JOB_DEVICES_REQUIRED = "请指定 device_udids（已启用 MC_REQUIRE_JOB_DEVICES）。"
JOB_INVALID_STATUS_TRANSITION = "任务状态不允许此操作（当前：{status}）。"
JOB_CANNOT_CANCEL_STATUS = "当前状态无法取消任务（当前：{status}）。"
JOB_CANNOT_RETRY_STATUS = "仅终态任务可重试（当前：{status}）。"
JOB_DEPENDENCY_NOT_FOUND = "前置任务不存在：{job_id}。"
JOB_DEPENDENCY_SELF = "任务不能依赖自身。"
JOB_DEPENDENCY_FAILED = "前置任务未成功（{job_id}，状态：{status}），本任务已失败。"

# ---- 设备 / Runner ----
DEVICE_UDID_REQUIRED = "请提供设备 UDID。"
DEVICE_NOT_FOUND = "设备不存在：{udid}。"
RUNNER_NOT_FOUND = "Runner 不存在：{runner_id}。"
RUNNER_HAS_BUSY_DEVICES = "节点存在占用中的设备（{udids}），请先释放占用或等待任务结束后再注销。"
MANAGED_RUNNER_DISABLED = (
    "本机托管 Runner 未启用（须显式设置 MC_ALLOW_MANAGED_RUNNER=1，"
    "且 Platform 仅绑定 loopback）。"
)
MANAGED_RUNNER_EXPOSED_BIND = (
    "本机托管 Runner 在非 loopback 绑定上已禁用"
    "（MC_HOST=0.0.0.0 / 局域网 IP / --lan 禁止 Web 启停；"
    "请改绑 127.0.0.1，或在本机用 CLI/服务启动 Runner）。"
)
MANAGED_RUNNER_ALREADY_RUNNING = "本机托管 Runner 已在运行（PID {pid}）。"
MANAGED_RUNNER_NOT_RUNNING = "本机托管 Runner 当前未运行。"
MANAGED_RUNNER_START_FAILED = "启动本机托管 Runner 失败：{detail}"
MANAGED_RUNNER_STOP_FAILED = "停止本机托管 Runner 失败：{detail}"

# ---- 制品 / 应用包 ----
ARTIFACT_NOT_FOUND = "工程制品不存在。"
ARTIFACT_NOT_FOUND_ID = "工程制品不存在：{artifact_id}。"
ARTIFACT_STORAGE_MISSING = "制品存储文件缺失。"
ARTIFACT_MANIFEST_REQUIRED = (
    "制品 manifest 未通过校验（已启用 MC_REQUIRE_ARTIFACT_MANIFEST）：{detail}"
)
APP_BUILD_NOT_FOUND = "应用构建不存在。"
APP_BUILD_NOT_FOUND_ID = "应用构建不存在：{app_build_id}。"
UPLOAD_EMPTY = "上传内容为空。"
UPLOAD_MUST_ZIP = "上传文件必须是 zip。"
APP_BUILD_NAME_REQUIRED = "请填写应用构建名称。"
APP_BUILD_PLATFORM_REQUIRED = "平台须为 android 或 ios（请上传 .apk/.ipa 或显式指定 platform）。"
APP_BUILD_ANDROID_EXT = "Android 应用资源须为 .apk/.apex/.xapk。"
APP_BUILD_IOS_EXT = "iOS 应用资源须为 .ipa。"
APP_BUILD_INVALID_ZIP = "不是有效的 apk/ipa（ZIP）文件：缺少 PK 文件头。"
JOB_APP_BUILD_OPTIONAL_WARN = (
    "未指定应用资源。用例制品与 apk/ipa 分离，请在应用资源库选择要测的安装包版本。"
    "设备已装目标应用且用例不执行安装时，可忽略。"
)
JOB_APP_BUILD_PLATFORM_MISMATCH = (
    "应用资源平台为 {app_platform}，任务平台为 {job_platform}，安装可能失败。"
)
JOB_APP_BUILD_PROJECT_MISMATCH = (
    "应用资源属于项目 {app_project}，任务项目为 {job_project}。"
    "请确认已分享该资源，或改选本项目下的安装包版本。"
)

# ---- 项目 / 成员 / ACL ----
ORG_NOT_FOUND = "组织不存在。"
ORG_ALREADY_EXISTS = "组织已存在：{org_id}。"
ORG_NO_ACCESS = "无权访问该组织。"
ORG_OWNER_ADMIN_REQUIRED = "仅组织负责人/管理员或平台管理员可执行此操作。"
ORG_PROJECT_CREATE_DENIED = "当前组织不允许普通成员创建项目。请联系组织负责人或管理员。"
ORG_ROLE_INVALID = "组织角色必须是 owner、admin 或 member。"
ORG_ROLE_CANNOT_ELEVATE = "不能授予高于自己的组织角色。"
ORG_CANNOT_REMOVE_LAST_OWNER = "不能移除组织的最后一位负责人。"
ORG_MEMBER_NOT_FOUND = "组织成员不存在。"
PROJECT_ID_REQUIRED = "请指定项目 ID。"
PROJECT_ORG_ID_REQUIRED = "请指定项目所属组织。"
PROJECT_NOT_FOUND = "项目不存在。"
PROJECT_ALREADY_EXISTS = "项目已存在：{project_id}。"
PROJECT_MEMBER_NOT_FOUND = "项目成员不存在。"
PROJECT_ROLE_OWNER_OR_MEMBER = "成员角色必须是 owner、member 或 viewer。"
PROJECT_ROLE_INVITE = "邀请角色必须是 member 或 viewer。"
PROJECT_ROLE_CANNOT_ELEVATE = "不能授予高于自己的项目角色。"
PROJECT_OWNER_ADMIN_ADD = "仅项目负责人或管理员可添加成员。"
PROJECT_OWNER_ADMIN_REMOVE = "仅项目负责人或管理员可移除成员。"
PROJECT_CANNOT_REMOVE_LAST_OWNER = "不能移除项目的最后一位负责人。"
PROJECT_NO_ACCESS = "无权访问该项目。"
PROJECT_NO_WRITE = "当前项目角色为只读（viewer），无法执行写操作。"
PROJECT_MEMBER_MUST_BE_ORG_MEMBER = "只能将本组织成员加入该项目，不能跨组织授权。"
USER_CREATE_PROJECT_ROLE_NEEDS_ID = "指定项目角色时必须同时给出项目。"
USER_CREATE_PROJECT_ORG_MISMATCH = "该项目不属于当前组织，不能在创建账号时加入。"
PROJECT_ORG_ADMIN_NOT_VIEWER = "本组织负责人/管理员对该组织下的项目固定为管理者，不能设为只读。"
PROJECT_INVITE_NOT_FOUND = "邀请不存在或已失效。"
PROJECT_INVITE_EXPIRED = "邀请已过期。"
PROJECT_INVITE_EXHAUSTED = "邀请使用次数已用尽。"
PROJECT_INVITE_REVOKED = "邀请已被撤销。"
ACL_NOT_FOUND = "共享权限记录不存在。"
ACL_OWNER_ONLY_SHARE = "仅资源所有者可分享。"
ACL_RESOURCE_TYPE = "resource_type 须为 artifact|job|schedule|app_build。"
ACL_RESOURCE_ID_REQUIRED = "请提供 resource_id。"
ACL_PERMISSION = "permission 须为 read|write。"
ACL_NO_ACCESS = "无权访问该资源。"
ACL_UNSUPPORTED_RESOURCE_TYPE = "不支持的 resource_type：{resource_type}。"

# ---- 报告 / 调度 ----
REPORT_NOT_FOUND = "报告不存在。"
REPORT_NOT_FOUND_JOB = "该任务尚无报告：{job_id}。"
REPORT_EMPTY = "报告内容为空。"
REPORT_JOB_ID_REQUIRED = "请提供 job_id。"
REPORT_COMPARE_IDS_REQUIRED = "请提供左右两侧任务 ID。"
REPORT_COMPARE_SAME = "不能将同一任务报告与自身对比。"
REPORT_FILE_MISSING = "报告文件尚未上传。"
REPORT_PATH_INVALID = "报告路径无效。"
SCHEDULE_NOT_FOUND = "调度不存在。"
SCHEDULE_SOURCE_REQUIRED = "请提供 project_dir 或 artifact_id。"
SCHEDULE_CREATOR_UNAVAILABLE = "调度创建者账号不可用。"

# ---- 运维 / 存储 ----
OPS_VALUES_REQUIRED = "请提供 values 对象。"
OPS_UNKNOWN_KEYS = "存在未知或不可编辑的配置项：{keys}。"
OPS_WEBHOOK_NOT_SET = "未配置告警 Webhook（环境变量或 /ops/config）。"
S3_BUCKET_REQUIRED = "使用 S3 存储时必须配置 MC_S3_BUCKET。"
S3_BOTO3_REQUIRED = "S3 存储需要安装 boto3：pip install boto3。"

# ---- 通用 ----
VALIDATION_FAILED = "请求参数校验失败。"
INTERNAL_ERROR = "服务内部错误，请稍后重试。"
NOT_FOUND = "资源不存在。"
FORBIDDEN = "没有权限执行此操作。"
CONFLICT = "资源冲突，请刷新后重试。"
BAD_REQUEST = "请求无效。"
UNAVAILABLE = "服务暂时不可用，请稍后重试。"

# 历史英文 detail → 中文（全局 handler 兼容未改完的抛出点）
LEGACY_DETAIL_ZH: dict[str, str] = {
    "invalid username or password": LOGIN_INVALID_CREDENTIALS,
    "invalid bearer token": AUTH_INVALID_TOKEN,
    "user not found or disabled": AUTH_USER_DISABLED,
    "need X-API-Token (runner) or Authorization: Bearer <jwt>": AUTH_REQUIRED,
    "admin required": AUTH_ADMIN_REQUIRED,
    "operator cannot assign admin role": AUTH_OPERATOR_NO_ADMIN,
    "runner token cannot act as another runner": AUTH_RUNNER_IMPERSONATE,
    "not a user session": AUTH_NOT_USER_SESSION,
    "user not found": AUTH_USER_NOT_FOUND,
    "login as user required": AUTH_USER_LOGIN_REQUIRED,
    "user login required": AUTH_USER_LOGIN_REQUIRED,
    "role must be admin or operator": AUTH_ROLE_ADMIN_OR_OPERATOR,
    "cannot delete yourself": AUTH_CANNOT_DELETE_SELF,
    "code and state required": AUTH_OIDC_CODE_STATE_REQUIRED,
    "SAMLResponse required": AUTH_SAML_RESPONSE_REQUIRED,
    "OIDC disabled (set MC_OIDC_ENABLED=1)": AUTH_OIDC_DISABLED,
    "MC_OIDC_ISSUER / CLIENT_ID / CLIENT_SECRET required": AUTH_OIDC_CONFIG_REQUIRED,
    "invalid oidc state": AUTH_OIDC_INVALID_STATE,
    "oidc state expired": AUTH_OIDC_STATE_EXPIRED,
    "user not provisioned; enable MC_OIDC_AUTO_PROVISION or create user": AUTH_OIDC_USER_NOT_PROVISIONED,
    "SAML disabled (set MC_SAML_ENABLED=1)": AUTH_SAML_DISABLED,
    "MC_SAML_IDP_SSO_URL required": AUTH_SAML_CONFIG_REQUIRED,
    "user not provisioned; enable MC_SAML_AUTO_PROVISION or create user": AUTH_SAML_USER_NOT_PROVISIONED,
    "job not found": JOB_NOT_FOUND,
    "job cancelled": JOB_CANCELLED,
    "invalid job_id": JOB_INVALID_ID,
    "result status must be succeeded or failed": JOB_INVALID_RESULT_STATUS,
    "runner token cannot create jobs; use user JWT": JOB_RUNNER_TOKEN_CANNOT_CREATE,
    "runner offline or not registered": JOB_RUNNER_OFFLINE,
    "job not claimed by this runner": JOB_NOT_CLAIMED_BY_RUNNER,
    "job not owned by this runner": JOB_NOT_OWNED_BY_RUNNER,
    "runner_id required to upload report": JOB_RUNNER_ID_REQUIRED_REPORT,
    "stream token is scoped to another job": JOB_STREAM_TOKEN_SCOPED,
    "stream token is scoped to another remote session": DEVICE_LOG_STREAM_TOKEN_SCOPED,
    "udid required": DEVICE_UDID_REQUIRED,
    "artifact not found": ARTIFACT_NOT_FOUND,
    "app build not found": APP_BUILD_NOT_FOUND,
    "empty upload": UPLOAD_EMPTY,
    "upload must be a zip file": UPLOAD_MUST_ZIP,
    "name required": APP_BUILD_NAME_REQUIRED,
    "project id required": PROJECT_ID_REQUIRED,
    "project not found": PROJECT_NOT_FOUND,
    "project member not found": PROJECT_MEMBER_NOT_FOUND,
    "role must be owner or member": PROJECT_ROLE_OWNER_OR_MEMBER,
    "only project owner or admin can add members": PROJECT_OWNER_ADMIN_ADD,
    "only project owner or admin can remove members": PROJECT_OWNER_ADMIN_REMOVE,
    "cannot remove last project owner": PROJECT_CANNOT_REMOVE_LAST_OWNER,
    "only owner can share this resource": ACL_OWNER_ONLY_SHARE,
    "acl not found": ACL_NOT_FOUND,
    "resource_type must be artifact|job|schedule|app_build": ACL_RESOURCE_TYPE,
    "resource_id required": ACL_RESOURCE_ID_REQUIRED,
    "permission must be read|write": ACL_PERMISSION,
    "report not found": REPORT_NOT_FOUND,
    "empty report": REPORT_EMPTY,
    "job_id required": REPORT_JOB_ID_REQUIRED,
    "left and right job_id required": REPORT_COMPARE_IDS_REQUIRED,
    "cannot compare a job report with itself": REPORT_COMPARE_SAME,
    "schedule not found": SCHEDULE_NOT_FOUND,
    "project_dir or artifact_id required": SCHEDULE_SOURCE_REQUIRED,
    "values object required": OPS_VALUES_REQUIRED,
    "alert webhook URL not set (env or /ops/config)": OPS_WEBHOOK_NOT_SET,
    "MC_S3_BUCKET required when MC_STORAGE=s3": S3_BUCKET_REQUIRED,
    "artifact storage missing": ARTIFACT_STORAGE_MISSING,
    "job log not found": JOB_LOG_NOT_FOUND,
    "report file not uploaded": REPORT_FILE_MISSING,
    "report path outside reports root": REPORT_PATH_INVALID,
}
