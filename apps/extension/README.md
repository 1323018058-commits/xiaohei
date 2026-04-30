# 小黑 ERP Takealot 插件

Chrome MV3 扩展，面向 Takealot 商品详情页。

当前能力：

- 从商品 URL 提取 `PLID`
- 未登录时**不向页面注入任何 ERP UI**
- 在 Popup 中直接用 `ERP 地址 + 账号 + 密码` 登录
- 登录成功后，商品页右下角才显示护栏卡
- 调 ERP `POST /api/extension/profit-preview`
- 调 ERP `POST /api/extension/protected-floor`
- 调 ERP `POST /api/extension/list-now` 创建内部上架任务壳
- 支持在扩展本地输入空运单价(CNY/kg)、采购价(CNY)、销售价(ZAR) 与长宽高/重量，显示推荐售价与预估利润
- 支持“采用建议保护价”，把推荐售价 10% 一键回填并保存为保护价
- 通过 Popup 作为补充入口保存：
  - `erpBaseUrl`
  - `defaultStoreId`

当前限制：

- 只覆盖商品详情页
- 不包含图标
- `一键上架` 当前会先创建内部任务壳，并由 extension worker 消费到受控状态；正式平台上架 worker 仍待接入
- 推荐售价 / 利润空间当前采用 `takealot_air_margin_v1`：注意空运单价与采购价是 `CNY`，销售价与回款口径是 `ZAR`；“推荐售价 10%”会作为建议保护价默认回填

本地加载方式：

1. 打开 Chrome 扩展管理页
2. 开启开发者模式
3. 选择“加载已解压的扩展程序”
4. 选择 `manifest.json` 所在的文件夹，例如 `apps/extension`
5. 如果之前加载过旧包，先移除旧扩展，或在扩展管理页点击“重新加载”
