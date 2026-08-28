<script setup lang="ts">
/** IDE 同源品牌标：resources/branding → public/brand（tools/export_icon.py） */
defineProps<{
  size?: number;
  large?: boolean;
}>();
</script>

<template>
  <img
    class="ap-mark"
    :class="{ large }"
    :src="'/brand/autopilot.png'"
    alt="AutoPilot"
    :width="size || 22"
    :height="size || 22"
    draggable="false"
  />
</template>

<style scoped>
.ap-mark {
  display: inline-block;
  flex-shrink: 0;
  vertical-align: middle;
  object-fit: contain;
  line-height: 0;
}
</style>
