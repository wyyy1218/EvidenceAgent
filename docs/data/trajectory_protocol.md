# 轨迹采集协议（S29）

> collection_id: `traj_teacher_s29_0001`  
> 冻结日期：2026-10-26

## 可见性

- 教师／基座只看与学生相同的打包可见状态、工具、预算与 Writer。  
- **gold 仅用于轨迹结束后的离线过滤**，不得进入策略输入。  
- **测试包不参与采集**。

## 教师

- 首选：百炼北京 `qwen3.8-max-0902`，非思考，温度 0.6。  
- 密钥不可用：按原定 **local_base 回退**；本轮 Bailian 为空，使用启发式控制器 + **真实语料／replay 文件读取**（不虚构观察）。  
- API 若不支持固定 seed：记录 `seed=null`，不声称完全确定。

## 过滤

1. 动作合法、候选存在、预算与来源授权。  
2. 答案／拒答达到 gold rubric（中文 Q 阈值）。  
3. 无 gold 泄漏、无测试轨迹、失败未冒充成功。  
4. 合格轨迹拆成 state→action；`state_hash` 去重。

## 产出

- `runs/trajectories/<collection_id>/{raw,accepted,rejected}/`  
- `state_action_candidates.jsonl`  
- `data/manifests/mf_trajectories_s29_0001.json`

## 重建

```bash
python repo/scripts/collect_trajectories.py --root <WORK_ROOT> --limit 40
# 扩量：提高 --limit；配置 BAILIAN_API_KEY 后改接真实教师客户端
```
