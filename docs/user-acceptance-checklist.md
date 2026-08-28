# MOMO Studio 软件用户验收清单

版本：`0.1.0-rc1`

本清单用于用户亲自验收软件产品体验。所有运动、Home、Playback 和 Vision Follow
检查都必须使用默认 `DRY_RUN` 与 Synthetic Vision；不得为本清单启用真实硬件。

验收前请确认使用 Draft PR #1 的最终候选 HEAD，并从仓库根目录启动：

```bash
make install
cp config/default.yaml config/local.yaml
make dev-backend LOCAL_CONFIG=config/local.yaml
```

在第二个终端运行：

```bash
make dev-frontend
```

## A. 启动

- [ ] Backend 正常启动。
- [ ] Frontend 正常启动。
- [ ] UI 显示 Backend Online。
- [ ] 默认模式显示 `DRY RUN`。
- [ ] Hardware access 显示 disabled。
- [ ] Real Motion 与 Commissioning Motion Test 均未自动授权。

## B. Control — V2 Dry Run

- [ ] 连接 V2 Dry Run robot。
- [ ] Joint 列表只显示 `j10`–`j15`。
- [ ] `j10` 显示为 prismatic，单位为 `mm`。
- [ ] `j11`–`j15` 单位为 `deg`。
- [ ] 单步 Joint Jog 正常。
- [ ] Continuous Jog 仅在按住时运行，释放后停止。
- [ ] Move Joints 正常完成。
- [ ] FK 显示确定性 TCP 结果。
- [ ] IK 对可达目标给出结果与 residual。
- [ ] Cartesian Jog 正常。
- [ ] Base/Tool 增量方向可切换且行为符合界面说明。
- [ ] Move Pose 正常。
- [ ] Home 在 Dry Run 中正常。
- [ ] Stop 能终止当前 Dry Run 动作。
- [ ] Robot status 持续更新且不会产生未处理错误。

## C. Control — V1 Dry Run

- [ ] 断开 V2。
- [ ] 切换并连接 V1。
- [ ] Joint 列表只显示 `j11`–`j15`。
- [ ] V1 页面不显示 `j10`。
- [ ] V1 Joint、FK/IK、Cartesian 和 Stop Dry Run 操作正常。

## D. Pose Library

- [ ] 从当前 Dry Run 状态 Capture Pose。
- [ ] Rename Pose。
- [ ] 添加、搜索和移除 Tag。
- [ ] Duplicate Pose 产生独立 UUID/revision。
- [ ] Goto 使用兼容的嵌入 Snapshot。
- [ ] Delete 需要明确确认且只删除目标 Pose。

## E. Motion Library

- [ ] 创建至少含两个 Keyframe 的 Motion。
- [ ] 编辑名称、描述或 Tag。
- [ ] Motion 保存完整嵌入 Snapshot，不依赖后续 Pose 修改。
- [ ] Duplicate Motion 产生独立实体。
- [ ] Delete 需要明确确认且只删除目标 Motion。

## F. Studio

- [ ] 新建或打开 Draft。
- [ ] Add Pose。
- [ ] Capture Keyframe。
- [ ] Reorder Keyframes。
- [ ] 修改 Duration。
- [ ] 修改 Hold。
- [ ] 设置 `JOINT` transition。
- [ ] 设置 `CARTESIAN_LINEAR` transition。
- [ ] 修改 Easing。
- [ ] Undo 恢复上一步编辑。
- [ ] Redo 重新应用编辑。
- [ ] Save 产生或更新正式 Motion。
- [ ] Save As 创建独立 Motion 且不覆盖原对象。

## G. Playback

- [ ] Preflight 成功显示完整计划与警告。
- [ ] Play 在 Dry Run 中开始。
- [ ] Pause 保持当前位置。
- [ ] Resume 从暂停状态继续。
- [ ] Stop 终止当前 Playback。
- [ ] Rate 调整影响 Dry Run 进度。
- [ ] Loop 行为与设置一致。
- [ ] Progress 与当前状态持续更新。

## H. Cartesian trajectory

- [ ] `CARTESIAN_LINEAR` Motion 可通过 Dry Run Preflight。
- [ ] Dry Run Playback 完成。
- [ ] TCP 路径图和执行结果符合预期。
- [ ] 界面仍明确显示 Kinematics 为 provisional，未声称 Real verified。

## I. Vision

- [ ] Source 为 Synthetic。
- [ ] Synthetic frame 正常加载。
- [ ] 可创建与更新 frame-bound ROI。
- [ ] Tracker overlay 与目标状态更新。
- [ ] Dry Run Follow 可启动并持续更新。
- [ ] Dead Zone 调整生效。
- [ ] EMA/filter 调整生效。
- [ ] Target Lost 会自动停止 Follow lease。
- [ ] Real Vision Follow 仍显示结构化 blocked reasons。

## J. Settings

- [ ] Profile 显示正确 Variant 与 enabled joints。
- [ ] Calibration 状态和 template/compatibility 信息清楚。
- [ ] Profile、Calibration、Device、Kinematics Fingerprint 可识别。
- [ ] Diagnostics 状态清楚且没有自动访问硬件。
- [ ] Commissioning progress 分阶段显示。
- [ ] Physical Stop 显示 Field Verification Required/Pending。
- [ ] Real Joint、Cartesian、Playback、Vision 均显示具体 blocked reasons。
- [ ] 三种 Session purpose 清楚分离且没有自动授权。

## K. Responsive layout

- [ ] Desktop 尺寸可正常使用。
- [ ] Laptop 尺寸可正常使用。
- [ ] Mobile 尺寸可正常使用。
- [ ] 各页面无整体横向溢出。
- [ ] 主要按钮、状态和错误信息在窄屏仍可访问。

## L. Failure states

- [ ] Backend Offline 显示清楚且不会假装命令成功。
- [ ] Stale State 显示并阻止不安全操作。
- [ ] IK unreachable 返回结构化原因和最佳 residual，不执行运动。
- [ ] Motion preflight failure 阻止 Playback。
- [ ] Revision conflict 不覆盖远端或原实体。
- [ ] Vision target lost 自动停止 Follow。
- [ ] Real-hardware blocked state 不可由前端按钮绕过。

## 验收结果

- [ ] **ACCEPT**
- [ ] **ACCEPT WITH ISSUES**
- [ ] **REJECT**

Notes:

```text

```

Real hardware acceptance is a separate field procedure. See
[Real-hardware field acceptance](real-hardware-acceptance.md). Do not complete any
physical field-acceptance checkbox as part of this software review.
