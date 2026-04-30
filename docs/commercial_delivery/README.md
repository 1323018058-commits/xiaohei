# 首批商用交付包

## 目的

这套文档把当前小黑 ERP 控制面，沉淀为一套可重复执行的首批付费客户交付流程。

适用场景：
- 新付费客户开通
- 租户与首个管理员账号交付
- Takealot API Key / Secret 收集与校验
- 首日故障响应
- 上线前执行检查

## 推荐阅读顺序

1. `docs/commercial_delivery/customer_onboarding_sop.md`
2. `docs/commercial_delivery/customer_handoff_template.md`
3. `docs/commercial_delivery/takealot_api_key_setup_guide.md`
4. `docs/commercial_delivery/incident_response_playbook.md`
5. `docs/commercial_delivery/go_live_checklist.md`
6. `docs/commercial_delivery/takealot_offer_create_runbook.md`

## 使用前提

在使用这套交付包前，建议已经满足：
- 环境健康
- 租户、生命周期、计费、自助端相关 smoke 已通过
- 已明确客户套餐和 `trial_ends_at` 或 `current_period_ends_at`
- 已确认安全的凭证交付通道

推荐最小验证基线：
- `npm run db:smoke:tenant-onboarding`
- `npm run db:smoke:tenant-lifecycle`
- `npm run db:smoke:billing-lifecycle`
- `npm run db:smoke:tenant-self-service`
- `npm run ops:data:check`

## 文件说明

- `docs/commercial_delivery/customer_onboarding_sop.md`：内部开通 SOP
- `docs/commercial_delivery/customer_handoff_template.md`：客户交付话术模板
- `docs/commercial_delivery/takealot_api_key_setup_guide.md`：Takealot 凭证收集与校验指引
- `docs/commercial_delivery/incident_response_playbook.md`：首批商用故障响应话术
- `docs/commercial_delivery/go_live_checklist.md`：上线前与首日检查清单
- `docs/commercial_delivery/takealot_offer_create_runbook.md`：Takealot 官方创建报价实战执行手册

## 边界

本交付包暂不覆盖：
- 在线支付扣款
- 发票自动化
- 公网 webhook 回调
- 客户自助续费结算门户

这些内容继续延后到支付渠道和公网域名正式确定之后再做。
