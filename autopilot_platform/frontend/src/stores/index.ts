/**
 * Pinia 入口（AUD-P2-009）。
 * 各域 store 与 mc*State 共用同一批 ref；启动接线见 composables/platformRuntime.ts（useMcStore.ts 仅 re-export）。
 */
import { createPinia } from "pinia";

export const pinia = createPinia();

export default pinia;
