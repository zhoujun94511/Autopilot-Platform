<script setup lang="ts">
import DataPager from "../common/DataPager.vue";

const props = withDefaults(
  defineProps<{
    total: number;
    page: number;
    pageSize: number;
    loading?: boolean;
    disabled?: boolean;
  }>(),
  {
    total: 0,
    page: 1,
    pageSize: 20,
    loading: false,
    disabled: false,
  },
);

const emit = defineEmits<{
  "update:page": [page: number];
  "update:pageSize": [size: number];
}>();
</script>

<template>
  <DataPager
    mode="page"
    :total="props.total"
    :page="props.page"
    :page-size="props.pageSize"
    :loading="props.loading"
    :disabled="props.disabled"
    @update:page="emit('update:page', $event)"
    @update:page-size="emit('update:pageSize', $event)"
  />
</template>
