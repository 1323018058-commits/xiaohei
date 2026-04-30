# 客户交付模板

下面这段可以直接复制后发给客户。

---

主题：您的小黑 ERP 工作区已准备完成

您好，`{{customer_name}}`

您的小黑 ERP Takealot 工作区已经准备完成。

## 访问方式

- 登录地址：`{{login_url}}`
- 用户名：`{{tenant_admin_username}}`
- 临时密码：`{{temporary_password}}`

## 商业状态

- 套餐：`{{plan_name}}`
- 订阅状态：`{{subscription_status}}`
- 试用截止：`{{trial_ends_at_or_na}}`
- 付费有效期至：`{{current_period_ends_at_or_na}}`

## 店铺接入情况

- Takealot 店铺：`{{store_name}}`
- 初始凭证校验：`{{validated / pending customer key / blocked}}`
- 首次同步结果：`{{succeeded / partial / pending}}`

## 您今天需要完成的动作

1. 首次登录并修改临时密码
2. 打开 `Dashboard`，确认套餐、日期、用量显示正确
3. 打开 `Stores`，确认 Takealot 店铺已可见
4. 如已告知可手动同步，请触发一次同步并确认 Listing 已出现
5. 如发现套餐、到期日、店铺数据不一致，请立即回复

## 重要说明

- 如果 Dashboard 显示 `past_due`，系统会暂停写操作，需由平台运营侧完成续费更新
- 即使写操作被暂停，已有数据仍然可以读取
- 请不要在群聊或截图中传播 API Key / Secret

## 支持信息

- 交付负责人：`{{delivery_owner}}`
- 支持通道：`{{support_channel}}`
- 升级联系人：`{{escalation_contact}}`

请直接回复：
- “访问已验证”
- 或当前看到的第一个阻塞问题

此致  
`{{sender_name}}`

---
