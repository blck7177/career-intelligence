# Role Category Taxonomy

产品面与存储字段统一使用 **role category**（`primary_role_category` 等）。

机器可读枚举（id、label、keywords）见 `configs/role_category_taxonomy.yaml`。本文件补充 agent 分类时需要的判断指南。

`primary_role_category` 字段值必须是 yaml 中 label 的**精确字符串**；无法匹配时用 `unknown`。

---

## Quick reference (20 categories)

| id | label | keywords 摘要 |
|---|---|---|
| `software_engineering` | Software Engineering / Platform | software engineer, backend, frontend, DevOps, SRE, API |
| `data_science_analytics` | Data Science / Analytics | data scientist, ML, experimentation, forecasting, BI |
| `product_management` | Product Management | product manager, roadmap, user research, GTM |
| `sales_business_development` | Sales / Business Development | AE, pipeline, quota, enterprise sales, partnerships |
| `marketing_growth` | Marketing / Growth | demand gen, content, brand, SEO, paid media |
| `customer_success_support` | Customer Success / Support | CS, account management, support, onboarding, retention |
| `operations_supply_chain` | Operations / Supply Chain | logistics, procurement, process improvement, vendors |
| `clinical_healthcare` | Clinical / Healthcare | clinical, patient care, nursing, clinical trials |
| `legal_compliance` | Legal / Compliance | legal, regulatory, privacy, contracts, governance |
| `hr_people_operations` | HR / People Operations | recruiting, talent acquisition, compensation, benefits |
| `design_creative` | Design / Creative | UX/UI, product design, visual design, content design |
| `finance_accounting` | Finance / Accounting | FP&A, accounting, controller, financial reporting |
| `market_risk_exposure` | Market Risk / Exposure Monitoring | VaR, exposure, Greeks, limit monitoring, P&L explain |
| `valuation_control_ipv` | Valuation Control / IPV | IPV, fair value, mark validation, derivative valuation |
| `product_control_pnl` | Product Control / P&L Reporting | P&L attribution, daily P&L, month-end close |
| `structured_credit` | Structured Credit / Credit Analytics | CLO, ABS, credit portfolio, default risk |
| `risk_analytics_automation` | Risk Analytics / Automation / Data | risk data pipelines, reporting automation |
| `model_risk_validation` | Model Risk / Model Validation | model validation, MRM, model approval |
| `stress_testing` | Stress Testing / Scenario Analysis | CCAR, DFAST, macro stress, scenario analysis |
| `treasury_alm` | Treasury / ALM / Liquidity | liquidity, ALM, FTP, IRRBB |

---

## Cross-industry role categories

### Software Engineering / Platform

**典型工作：** 构建/维护软件系统、平台、API、基础设施与可靠性。

**区分点：** 与 Data Science 的区别：工程侧交付可运行系统；DS 侧重建模与分析产出。

### Data Science / Analytics

**典型工作：** 数据分析、建模、实验、指标与 BI 报告。

**区分点：** 与 Software Engineering 的区别：分析/模型为主；工程 category 以系统交付为主。

### Product Management

**典型工作：** 路线图、需求优先级、用户研究、跨团队协调与 GTM 对齐。

**区分点：** 与 Design 的区别：PM 定方向与优先级；Design 定交互与视觉体验。

### Sales / Business Development

**典型工作：** 获客、pipeline、成交、续约与合作伙伴拓展。

**区分点：** 与 Marketing 的区别：Sales 直接负责 revenue 与客户关系；Marketing 负责需求生成与品牌。

### Marketing / Growth

**典型工作：** 品牌、内容、SEO、付费投放、增长实验。

**区分点：** 与 Sales 的区别：Marketing 创造线索与认知；Sales 负责转化与收入。

### Customer Success / Support

**典型工作：** 客户 onboarding、续约、技术支持与满意度。

**区分点：** 与 Sales 的区别：CS 关注存量客户成功；Sales 关注新签与扩张。

### Operations / Supply Chain

**典型工作：** 流程优化、物流、采购、供应商管理与运营 KPI。

**区分点：** 与 Finance / Accounting 的区别：Ops 关注运营执行；Finance 关注报表与资金规划。

### Clinical / Healthcare

**典型工作：** 临床护理、患者流程、试验运营、医院/医疗运营。

**区分点：** 与 Data Science 的区别：Clinical 直接涉及医疗场景与患者；DS 可为医疗提供分析支持。

### Legal / Compliance

**典型工作：** 合同、监管合规、隐私、治理与审计配合。

**区分点：** 与 HR 的区别：Legal 关注法规与合规风险；HR 关注人员与组织政策。

### HR / People Operations

**典型工作：** 招聘、薪酬福利、员工政策与组织发展。

**区分点：** 与 Operations 的区别：HR 聚焦人员与组织；Ops 聚焦业务流程与供应链。

### Design / Creative

**典型工作：** UX/UI、视觉设计、内容设计与创意产出。

**区分点：** 与 Product Management 的区别：Design 交付体验与视觉；PM 定产品方向与优先级。

### Finance / Accounting

**典型工作：** FP&A、会计、报表、预算与财务控制。

**区分点：** 与 Finance/risk specialty categories 的区别：本 category 为通用企业财务；下方 finance/risk 为交易/银行细分职能。

---

## Finance / risk role categories (legacy coverage)

### Market Risk / Exposure Monitoring

**日常工作：**
daily risk reporting, limit monitoring, scenario analysis, risk explain to desk

**典型对接方：**
front desk, risk manager, model owner

**区分点：**
和 Valuation Control 的区别：Market Risk 关注 risk metrics；VC 关注 price/valuation 正确性。

---

### Valuation Control / IPV

**日常工作：**
mark validation, reserve calculation, model risk liaison, P&L reserve booking

**典型对接方：**
trader, model owner, finance controller, regulator

**区分点：**
和 Product Control 的区别：VC 关注价格正确性；PC 关注 P&L attribution 和 reporting。

---

### Product Control / P&L Reporting

**日常工作：**
daily P&L production, attribution analysis, month-end close, finance reporting

**典型对接方：**
desk head, finance, risk, external auditor

---

### Structured Credit / Credit Analytics

**日常工作：**
credit risk modeling, portfolio analysis, stress testing, credit monitoring

**典型对接方：**
credit desk, risk management, structuring team

---

### Risk Analytics / Automation / Data

**日常工作：**
build/maintain risk data pipelines, automate reports, data quality

**典型对接方：**
risk managers, tech, quant

**注意：**
这个 role category 经常和其他 category 混合出现，需要判断主职能。

---

### Model Risk / Model Validation

**日常工作：**
independent model validation, model documentation review, challenge model assumptions

**典型对接方：**
model owners, risk, quant, regulator

---

### Stress Testing / Scenario Analysis

**日常工作：**
design stress scenarios, run stress tests, report to regulator, capital planning

---

### Treasury / ALM / Liquidity

**日常工作：**
liquidity reporting, FTP calculation, IRRBB monitoring, balance sheet analysis
