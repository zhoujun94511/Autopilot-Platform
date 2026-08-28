/**
 * 设备占用表单弹窗的状态桥。
 *
 * 业务表单弹窗不走 useNotify 的瞬时交互三件套（confirm / prompt / copy）：
 * 一次动作要采集多个字段时，必须是一个表单，不能串联多次 promptDialog。
 */
import { shallowRef } from "vue";

/** 用途标签需与后端 `services/devices.py::_RESERVE_PURPOSE_TAGS` 保持一致 */
export const RESERVE_PURPOSES = [
  {
    id: "debug",
    label: "手工调试",
    tag: "[手工调试]",
    placeholder: "例如：复现登录闪退",
  },
  {
    id: "remote",
    label: "远控预留",
    tag: "[远控预留]",
    placeholder: "例如：给异地同事远控使用",
  },
  {
    id: "demo",
    label: "演示联调",
    tag: "[演示联调]",
    placeholder: "例如：客户演示前预留",
  },
  { id: "other", label: "其他", tag: "", placeholder: "例如：联调某某模块" },
] as const;

export type ReservePurposeId = (typeof RESERVE_PURPOSES)[number]["id"];

export const RESERVE_DURATION_PRESETS = [30, 60, 120, 240];
export const RESERVE_MIN_MINUTES = 1;
export const RESERVE_MAX_MINUTES = 1440;
export const RESERVE_DEFAULT_MINUTES = 60;

export function durationLabel(minutes: number): string {
  if (minutes >= 60 && minutes % 60 === 0) return `${minutes / 60} 小时`;
  return `${minutes} 分钟`;
}

export type ReserveDialogRequest = {
  /** 标题用的人类可读设备名（营销名优先，勿用裸 UDID） */
  deviceLabel: string;
  udid: string;
};

export type ReserveDialogResult = {
  durationMinutes: number;
  /** 已按 `[用途]说明` 约定拼好，可直接提交 */
  reason: string;
};

type ReserveDialogState = ReserveDialogRequest & {
  resolve: (value: ReserveDialogResult | null) => void;
};

export const reserveDialogState = shallowRef<ReserveDialogState | null>(null);

export function openReserveDialog(
  req: ReserveDialogRequest,
): Promise<ReserveDialogResult | null> {
  return new Promise((resolve) => {
    reserveDialogState.value = {
      ...req,
      resolve: (value) => {
        reserveDialogState.value = null;
        resolve(value);
      },
    };
  });
}
