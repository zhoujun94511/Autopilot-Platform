import { customRef, ref, watch, type Ref } from "vue";

/** 输入即时更新，回调 debounce 后触发（用于搜索框）。 */
export function useDebouncedValue(initial = "", delayMs = 300): {
  value: Ref<string>;
  debounced: Ref<string>;
} {
  const debounced = ref(initial);
  let timer: ReturnType<typeof setTimeout> | undefined;

  const value = customRef<string>((track, trigger) => {
    let inner = initial;
    return {
      get() {
        track();
        return inner;
      },
      set(v: string) {
        inner = v;
        trigger();
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => {
          debounced.value = v;
        }, delayMs);
      },
    };
  });

  return { value, debounced };
}

/** 监听多个源，任意变化时重置 page=1 并触发 reload。 */
export function watchListFilters(
  sources: Array<() => unknown>,
  page: Ref<number>,
  reload: () => void,
) {
  watch(
    sources,
    () => {
      if (page.value !== 1) {
        page.value = 1;
      } else {
        reload();
      }
    },
    { flush: "post" },
  );
  watch(page, () => reload());
}
