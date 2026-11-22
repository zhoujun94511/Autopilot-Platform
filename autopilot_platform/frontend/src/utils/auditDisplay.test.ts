import { describe, expect, it } from "vitest";
import { auditActionLabel, auditResourceLabel, formatAuditDetail, formatAuditRow } from "./auditDisplay";

describe("auditDisplay", () => {
  it("translates device and remote session actions and resource types into Chinese", () => {
    expect(auditActionLabel("device.reserve")).toBe("占用设备");
    expect(auditActionLabel("device.reservation.release")).toBe("释放设备占用");
    expect(auditActionLabel("device.reservation_release")).toBe("释放设备占用");
    expect(auditActionLabel("device.remote_session_start")).toBe("开启远程调试");
    expect(auditActionLabel("device.remote_session_stop")).toBe("关闭远程调试");
    expect(auditActionLabel("device.remote_session.start")).toBe("开启远程调试");
    expect(auditActionLabel("device.remote_session.stop")).toBe("关闭远程调试");
    expect(auditActionLabel("device.remote_command.accessibility")).toBe("远控无障碍操作");
    expect(auditActionLabel("device.remote_command.stream.configure")).toBe("调整远控画质流");

    expect(auditResourceLabel("device")).toBe("设备");
    expect(auditResourceLabel("device_remote_session")).toBe("远控会话");
  });

  it("summarizes raw login, IP/UA, device remote and reservation details cleanly in Chinese", () => {
    expect(formatAuditDetail("auth.login", "password")).toBe("账号密码登录");
    expect(
      formatAuditDetail(
        "auth.login_failed",
        "ip=127.0.0.1 ua=Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/157.0.0.0",
      ),
    ).toBe("来源 IP 127.0.0.1 · 浏览器");
    expect(
      formatAuditDetail("auth.login_failed", "ip=127.0.0.1 ua=Python-urllib/3.12"),
    ).toBe("来源 IP 127.0.0.1 · 脚本/API 客户端");
    expect(
      formatAuditDetail(
        "device.remote_session.start",
        "device_id=3911e625c63a4faab3a92b5288e83615;udid=R5CN30EQKNM;platform=android",
      ),
    ).toBe("安卓 · 设备编号 R5CN30EQKNM");
    expect(
      formatAuditDetail(
        "device.reserve",
        "reservation_id=7b9e5ea75c3b49d398ae0ab6a1f88015 expires_at=2026-11-22T06:18:58 reason=[手工调试]",
      ),
    ).toBe("用途：手工调试 · 占用单 7b9e5ea7…");
    expect(
      formatAuditDetail(
        "device.remote_command.accessibility",
        "request_id=48900219-7dc2-49cb-8210-1d116417a7c7",
      ),
    ).toBe("指令编号 48900219…");
  });

  it("formats complete audit row for table display", () => {
    const row = formatAuditRow({
      id: "1",
      action: "device.remote_session.stop",
      actor: "admin",
      actor_kind: "user",
      resource_type: "device_remote_session",
      resource_id: "832a75261234567890abcdefd774",
      detail: "device_id=7535029ac1bb4258a36ec942f6d6e57f;status=closed",
      created_at: "2026-11-22T05:22:21Z",
    });
    expect(row.actionLabel).toBe("关闭远程调试");
    expect(row.resourceSummary).toBe("远控会话 832a7526…d774");
    expect(row.detailSummary).toBe("已关闭");
  });
});
