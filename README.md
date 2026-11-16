# 铸星 · 空压站耗电模型择优与排机

从连续小时计量中筛选耗电预测特征，以时间验证比较Ridge正则强度；再把车间逐小时需气批次转成有占用约束、可改排的空压机排机计划，并把解释转成待负责人签核的节能评议。

## 业务场景

铸星制造能源组负责ZX-A01空压站。当前仪表员导出 `ZX-A01_20261101-10_小时计量.xlsx`，工程师在工作簿中试删变量和拟合回归，再用周会文档提出节能动作。三个痛点：随机切分把未来信息带入训练、标准化使用全表、回归系数被误当成可直接兑现的节能收益。

上游是压力/气量/温度/开机台数和电表小时记录，以及各车间汇总的逐小时需气批次；本应用替代时间窗校验、特征配置、模型比选、排机计划占用和评议留痕；下游是工艺负责人安排安全可控的试点。

五页分别为耗电样本、特征方案、模型比选、排机计划、节能评议。四类核心实体为Sample（小时计量）、Run（特征/alpha配置与冻结模型结果）、Plan（排机预览/确认/改排/取消与时段占用，PlanSlot存整点占用）、Review（观察、业务动作和签核）；另有User和Audit。

|角色|权限|典型动作|
|---|---|---|
|admin|全部，独占签核和审计|确认安全边界后签核节能评议|
|analyst|样本修订、提交模型、起草评议、导出|比较含/不含无关噪声的特征方案|
|viewer|业务只读及导出|核对模型时间窗；后端拒绝写入与计算|

## 启动与账号

```sh
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```

前端 [localhost:18209](http://localhost:18209)，后端 [localhost:19209/docs](http://localhost:19209/docs)，MySQL映射17709。演示账号 `admin@demo.local`、`analyst@demo.local`、`viewer@demo.local`，密码均 `Demo123!`。演示凭据仅供本地使用，部署时替换DB_PASSWORD/JWT_SECRET。

`SEED_DEMO=true` 启动自动执行一次seed，生成3账号、240小时计量：2026-11-01 00:00至11-10 23:00，固定随机种子3110。按本地小时自然键幂等，重复执行不新增同小时也不覆盖人工修订。

## 一天的业务剧本

1. 08:50 viewer查看ZX-A01过去240小时计量。
2. 09:00 analyst核对 `ZX-A01_20261101-10_小时计量.xlsx` 的小时连续性。
3. 09:10 录入11月11日00:00：压力6.7bar、气量9m³/min、温度22℃、开机4台、噪声0、耗电203kWh。
4. 09:20 对异常电表读数填写记录ID和完整字段修订，并保留计量说明。
5. 09:30 创建“ZX-A01能耗特征复核”，选择气量、压力、温度、开机台数及候选alpha。
6. 09:40 worker计算完成，模型比选页核对末段RMSE、基线、每折时间和系数单位，导出 `airpower-select-<id>.json`。
7. 09:50 工艺员提交11月12日00:00—23:00冲压/焊装车间逐小时需气CSV；analyst在排机计划页导入，整批校验后计算预览（不占用时段）。
8. 10:00 核对逐小时开机台数、运行/启动耗电与贪心对照，确认后占用这些整点；并发确认重叠计划仅一份成功。
9. 10:10 需求调整：analyst对已确认计划改排，先出预览；新计划确认成功才接管原占用，失败或取消不改动原计划。
10. 10:20 analyst起草“空载复核”，写明模型观察、安全边界和保持产量一致的试点动作。
11. 10:30 admin签核后评议冻结；10:40 viewer下载 `airpower-review-<id>.json`。

## 算法与口径

输入为同站点本地连续整点小时记录：压力bar、气量m³/min、温度℃、开机台数、无关对照噪声和目标kWh。小时唯一且不得缺口；至少60小时；训练段所选列不得为常量；所有数值须有限。目标不会进入特征。

按小时排序，前floor(0.8N)为训练段，最后20%为末段验证。训练段内采用3折扩展窗 `TimeSeriesSplit`；每折新建Pipeline，只用该折训练部分fit `StandardScaler`，然后fit `Ridge`。目标函数为 `||y−Xβ||²+alpha||β||²`，截距不惩罚。候选alpha逐折RMSE取平均，最小者入选，同分优先较小alpha。只对选中alpha在完整训练段重拟合，最后20%用于一次末段评估；并比较“训练目标均值”的基线RMSE。

输出包含每折时间范围/样本量/Scaler均值、训练和验证小时、候选CV RMSE、选中alpha、末段实际/预测/残差、训练均值/标准差、系数和checksum。标准化系数表示特征增加一个训练标准差时的条件预测变化（kWh）；原单位系数=标准化系数/训练标准差；原单位截距=模型截距−原单位系数点乘训练均值。系数是关联，不能直接认定因果节能收益。

所有选择使用提交时冻结输入；修订原始计量不会改写旧版本。反复查看末段指标选择特征后，该末段不再是独立最终测试集，实际落地需另设未见时间窗。没有自动控制空压机或在线模型部署。

### 排机口径

输入批次行：`hour,workshop,demand,pressure,temperature,available_machines`（CSV含表头或JSON行数组）。同一小时可有多车间，需气按小时汇总；同小时的压力、温度、可用台数必须一致。小时必须连续、车间在同小时唯一、可用台数为0–50整数。任一行不合法、重复或缺小时即整批拒绝，不做部分导入；前端预检与后端二次校验使用同一规则。

选一份已成功且包含 `machines` 特征的Ridge模型，用其原单位系数快照估算该小时开m台的运行耗电：`max(0, 原单位截距 + Σ系数×特征)`，其中气量取该小时汇总需气，模型若含对照噪声按0代入，m=0记0。供气约束为 `m×单台供气上限 ≥ 汇总需气`，且 `m ≤ 该小时可用台数`。总耗电=Σ运行耗电+Σ(每增开台数×单台启动耗电)；增开按相邻小时台数差计，从给定初始台数起算，整段累计增开台次不得超过上限。

求解用动态规划，状态为(上一小时台数, 已用增开台次)，转移逐小时枚举可行台数并计入启动耗电，覆盖整段取最低总耗电；同耗电同增开台次时优先较少台数。这避免“每小时只开最低台数”的贪心在启停边界失手：少开一台省下的运行电可能小于下一次再增开的启动电。页面并列展示该贪心对照及其差值，作为检验案例。

生命周期：`preview` 只计算、不占时段，输入与模型快照此时固化；`confirm` 以 `plan_slots.hour` 唯一约束一次性写入整段占用，并发确认重叠计划仅一份成功，失败回滚不留半份占用，重复确认幂等。确认后 `params`/`input`/模型系数快照冻结，只能改排或取消；取消释放占用，取消预览不释放任何时段。`reschedule` 从已确认计划复制冻结批次出改排预览，确认时在同一事务内先校验并写入新计划占用，再释放原计划占用并把原计划标记 `superseded`；新计划确认失败则原计划状态与占用不变。中断时数据库事务整体回滚，恢复后只有已提交的 `confirmed` 计划持有占用。

## 工程说明

Python3.11/FastAPI/SQLAlchemy/scikit-learn/NumPy、原生ES modules/CSS、Nginx、MySQL8、Redis7。恰好五服务frontend/backend/worker/db/redis；全部有健康检查；后端等数据库/Redis，worker还等后端，前端等后端。worker真实消费Redis模型任务，心跳`/tmp/heartbeat`，结果写共享`/artifacts`卷；重启恢复queued/running任务。数据库、Redis和结果均命名卷。

Nginx `/api/`转后端根路由，前端SPA回落。仅前端、后端和数据库映射宿主端口。用 `docker compose down -v --remove-orphans`清理本项目测试数据。

目录：backend/src按models/schemas/services/controllers/routes/middlewares/config/constants/utils分工；frontend/src按api/stores/types/components/common/hooks/pages/router/utils/constants分工。共用表格、表单、状态标签；表单hooks/HTML转义utils；请求ID和安全头中间件，全局异常处理，写操作审计。首次表结构由ORM创建，migrations提供实测数据库导出的初始DDL，未带在线迁移执行器。

本地开发可先启动db/redis，backend安装requirements并设DATABASE_URL/REDIS_URL/JWT_SECRET后运行 `uvicorn src.main:app --reload`；前端使用Nginx或同源代理。依赖固定在requirements.txt。

变量见.env.example：COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、DB_PASSWORD、JWT_SECRET、SEED_DEMO、NETWORK_SUBNET。独立子网10.253.110.0/24规避当前机器地址池耗尽，迁移可调整。角色ROLES、任务STATES、特征FEATURES、评议REVIEW_STATES和计划PLAN_STATES分别定义在后端src/constants/enums.py与前端src/constants/enums.js，schema校验在backend/src/schemas/business.py，排机算法在backend/src/services/schedule.py与plans.py，持久化列见models/entities.py。

## 范围与交付

逐条表单/API录入及完整字段修订；车间需气支持CSV/JSON批次导入与整批拒绝，不做XLSX解析、部分导入、删除或分页。排机时段最多14天（336小时），单批最多5000行。固定站点ZX-A01，无自动仪表采集；排机为计划占用与耗电估算，不下发设备指令；单worker；评议站内签核，没有外部通知或设备控制。Google Fonts离线时回退serif/sans-serif。测试脚本、截图、真实结果和已知差异在 `../../test-artifacts/gb-3110/TESTING.md`，源码不放截图或测试报告。MIT License，见LICENSE。
