<script setup lang="ts">
import { AvatarImage } from 'reka-ui'

const props = defineProps<{
  src: string
  alt?: string
}>()
</script>

<template>
  <AvatarImage :src="props.src" :alt="props.alt" class="size-full object-cover" />
</template>
