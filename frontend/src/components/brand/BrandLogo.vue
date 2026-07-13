<script setup lang="ts">
/**
 * Hansight 品牌 Logo
 *
 * 名称由来：Han（Hanson）+ Sight（洞察）= 智能文档洞察
 *
 * 设计语言：
 * - 外形为 almond/eye 轮廓（洞察之眼），象征"看见"文档中的知识
 * - 内部三道水平线条象征文档解析后的结构化数据
 * - 右侧焦点圆点象征知识节点 / 洞察聚焦点
 * - 蓝色渐变传达技术、专业的 B2B SaaS 气质
 *
 * 通过 `size` 属性控制尺寸，可适配侧边栏（30px）与登录页（56px）等多场景。
 */
withDefaults(defineProps<{
  size?: number | string
}>(), {
  size: 32,
})
</script>

<template>
  <svg
    class="brand-logo"
    :width="size"
    :height="size"
    viewBox="0 0 40 40"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <defs>
      <linearGradient id="hsGrad" x1="4" y1="4" x2="36" y2="36" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#3B82F6" />
        <stop offset="1" stop-color="#1D4ED8" />
      </linearGradient>
    </defs>

    <!-- 洞察之眼：almond 轮廓 -->
    <path
      d="M3 20C8 11 14 8 20 8s12 3 17 12c-5 9-11 12-17 12S8 29 3 20z"
      fill="url(#hsGrad)"
    />

    <!-- 内部文档结构线条 -->
    <rect x="11" y="16" width="12" height="2" rx="1" fill="#FFFFFF" fill-opacity="0.9" />
    <rect x="11" y="20" width="9" height="2" rx="1" fill="#FFFFFF" fill-opacity="0.7" />
    <rect x="11" y="24" width="11" height="2" rx="1" fill="#FFFFFF" fill-opacity="0.5" />

    <!-- 焦点圆点：洞察聚焦 -->
    <circle cx="27" cy="20" r="4" fill="#FFFFFF" />
    <circle cx="27" cy="20" r="4.5" stroke="#1D4ED8" stroke-width="0.8" stroke-opacity="0.2" />
    <circle cx="27" cy="20" r="1.6" fill="#1D4ED8" />
  </svg>
</template>

<style scoped>
.brand-logo {
  display: block;
  flex-shrink: 0;
}
</style>
