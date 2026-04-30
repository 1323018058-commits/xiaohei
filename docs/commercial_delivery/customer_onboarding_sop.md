# 客户开通 SOP

## 目标

把一个新的 Takealot 客户，从“已签约”推进到“可以登录、看 Dashboard、完成首轮同步”。

## 需要提前收集的信息

- 客户公司名
- 租户显示名
- 租户 slug
- 客户首个管理员邮箱
- 客户首个管理员用户名
- 套餐：`starter` / `growth` / `scale` / `war-room`
- 商业状态：`trialing` 或 `active`
- `trial_ends_at` 或 `current_period_ends_at`
- Takealot 店铺显示名
- Takealot API Key
- Takealot API Secret
- 客户支持联系人
- 内部交付负责人

## 入场门槛

正式开通前，至少确认以下项目已通过：
- `npm run db:smoke:tenant-onboarding`
- `npm run db:smoke:billing-lifecycle`
- `npm run db:smoke:tenant-self-service`
- `npm run ops:data:check`
- 最新 `release:preflight` 与 `host:check` 为绿色，或仅剩公网域名类已知告警

## 交付步骤

### 1. 创建租户

在 Admin 中：
- 打开 `Admin -> Tenants`
- 创建最终 `name`、`slug`
- 创建首个 `tenant_admin`
- 生成临时密码
- 记录租户 ID

通过标准：
- 租户出现在列表中
- 新租户管理员可以登录

### 2. 激活商业状态

仍在 Admin 中：
- 选择该租户
- 设置 `plan`
- 设置 `subscription_status`
- 试用客户填写 `trial_ends_at`
- 付费客户填写 `current_period_ends_at`
- 写入审计原因

通过标准：
- 租户 Dashboard 显示正确套餐和日期
- `/api/auth/me` 显示正确订阅状态

### 3. 录入 Takealot 店铺

切到租户视角：
- 打开 `Stores`
- 创建店铺
- 输入 Takealot API Key 和 Secret
- 保存并确认店铺详情页能正常打开

通过标准：
- 店铺行出现
- 凭证状态正常

### 4. 触发首轮同步

- 点击 `Sync`
- 等待任务变为 `succeeded` 或可接受的 `partial`
- 确认 Listing 已回流

通过标准：
- `Tasks` 页面有完成任务
- 店铺详情能看到 Listing 数据

### 5. 验证客户自助视图

用租户管理员账号验证：
- Dashboard 显示正确套餐
- Dashboard 显示 Trial Ends 或 Paid Through
- Dashboard 警告与真实状态一致
- `Stores` 页面可以正常打开

### 6. 发送交付信息

使用 `docs/commercial_delivery/customer_handoff_template.md` 给客户发送交付消息。

必须包含：
- 登录地址
- 用户名
- 临时密码
- 套餐
- 到期信息
- 客户首日动作
- 支持与升级路径

### 7. 首日观察

首个业务窗口内重点观察：
- 第一次客户成功登录
- 第一次客户主动读取店铺
- 同步失败
- 凭证鉴权失败
- 异常 `402`
- 配额逼近警告

## 出场门槛

只有以下全部满足，才算客户开通完成：
- 客户可登录
- 密码已安全交付
- Dashboard 套餐与日期显示正确
- 首次店铺同步已完成
- 没有未处理的严重告警

## 故障分支

- 如果客户不能登录：先查租户状态，再查订阅状态，再查密码重置流程
- 如果店铺同步失败：使用 `docs/commercial_delivery/incident_response_playbook.md`
- 如果客户尚未提供真实 Takealot 凭证：不要标记为“正式可运营”
