# Execution Kill Switch

## Quy ước tên

Tên dễ gây nhầm, nên nói rõ một lần:

| `engaged` | `ExecutionState` | Hệ quả |
| --- | --- | --- |
| `True` | `DISABLED` | `NEW_ENTRY_BLOCKED`, `DCA_BLOCKED` |
| `False` | `ENABLED` | các kiểm tra còn lại của guard quyết định |

`EXECUTION_KILL_SWITCH=true` là **mặc định**, nên hệ thống xuất xưởng ở trạng thái chặn.

Dashboard hiển thị `EXECUTION BLOCKED` hoặc `EXECUTION ENABLED`.

## Không bao giờ tự bật lại

Không timeout, không retry counter, không auto-recovery. Nhả kill switch cần một lời gọi `release(reason)` tường minh, và **reason là bắt buộc** — chuỗi rỗng bị từ chối.

`status()["auto_release"]` luôn là `False`.

## Phân biệt với kill switch của Paper

| | `paper.GlobalKillSwitch` | `execution.mt5.ExecutionKillSwitch` |
| --- | --- | --- |
| Phạm vi | paper simulation | DEMO execution qua MT5 |
| Mặc định | không engage | **engage** |
| Alert | `RISK_BLOCK` | `KILL_SWITCH_TRIGGERED` |

Hai đối tượng độc lập; thay đổi cái này không ảnh hưởng cái kia.

## API

```text
GET  /execution/kill-switch            trạng thái + lịch sử
POST /execution/kill-switch/engage     {"reason": "..."}   chặn — luôn được phép
POST /execution/kill-switch/release    {"reason": "..."}   nhả — tường minh, có lý do
```

Mọi chuyển trạng thái ghi một dòng vào `kill_switch_events` và phát alert `KILL_SWITCH_TRIGGERED` (CRITICAL khi engage).
